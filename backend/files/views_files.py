import io
from pathlib import Path
from datetime import datetime
from bson import ObjectId
from django.conf import settings
from django.http import StreamingHttpResponse, Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.throttling import UserRateThrottle, ScopedRateThrottle

from files.models import File, Folder, FileVersion
from files.crypto_utils import (
    get_master_kek,
    compute_sha256_and_save_encrypted,
    decrypt_file_stream
)
import mongoengine as me
from files.lock_service import FileLockService

class UploadRateThrottle(UserRateThrottle):
    scope = 'uploads'

def resolve_parent_folder(parent_id, user):
    if not parent_id or parent_id in ('root', 'null', 'None'):
        return None
    try:
        folder = Folder.objects.get(id=ObjectId(parent_id), owner=user, deleted=False)
        return folder
    except (me.DoesNotExist, Exception):
        raise Http404("Parent folder not found")

class FileListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """List files and folders matching criteria (parent_id, q search, trashed status)."""
        parent_id = request.query_params.get('parent_id')
        q = request.query_params.get('q', '').strip()
        trashed_str = request.query_params.get('trashed', 'false').lower()
        is_trashed = trashed_str in ('true', '1')

        # Filter by trashed status
        folder_qs = Folder.objects(owner=request.user, deleted=is_trashed)
        file_qs = File.objects(owner=request.user, deleted=is_trashed)

        if not is_trashed and not q:
            # Filter by parent_folder
            if parent_id == 'root' or not parent_id:
                folder_qs = folder_qs.filter(parent_folder=None)
                file_qs = file_qs.filter(parent_folder=None)
            elif parent_id:
                try:
                    parent_obj = Folder.objects.get(id=ObjectId(parent_id), owner=request.user)
                    folder_qs = folder_qs.filter(parent_folder=parent_obj)
                    file_qs = file_qs.filter(parent_folder=parent_obj)
                except Exception:
                    return Response({"error": "Parent folder not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        if q:
            folder_qs = folder_qs.filter(name__icontains=q)
            file_qs = file_qs.filter(name__icontains=q)

        # Pagination params
        try:
            limit = int(request.query_params.get('limit', 50))
            offset = int(request.query_params.get('offset', 0))
        except ValueError:
            limit, offset = 50, 0

        folder_list = [f.to_dict() for f in folder_qs]
        file_list = [f.to_dict() for f in file_qs]
        combined = folder_list + file_list

        total_count = len(combined)
        paginated_items = combined[offset:offset+limit]

        return Response({
            "count": total_count,
            "limit": limit,
            "offset": offset,
            "results": paginated_items
        }, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a new file (supports multipart upload OR JSON metadata)."""
        user = request.user
        name = request.data.get('name')
        parent_id = request.data.get('parent_id')

        try:
            parent_folder = resolve_parent_folder(parent_id, user)
        except Http404:
            return Response({"error": "Parent folder not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        file_obj_in_request = request.FILES.get('file')

        if not file_obj_in_request:
            # Metadata-only creation (client will follow up with PUT /api/files/{id}/content/)
            if not name:
                return Response({"error": "File name is required.", "code": "VALIDATION_ERROR"}, status=status.HTTP_400_BAD_REQUEST)

            file_record = File(
                name=name,
                owner=user,
                parent_folder=parent_folder,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            file_record.save()
            return Response(file_record.to_dict(), status=status.HTTP_201_CREATED)

        # Multipart single-shot upload
        filename = name or file_obj_in_request.name
        kek_bytes = get_master_kek()

        # Temporary save to check hash and size
        temp_stream = file_obj_in_request

        # Dummy path to encrypt file to temp location
        import uuid
        temp_filename = f"temp_{uuid.uuid4().hex}"
        temp_dest = settings.STORAGE_ROOT / temp_filename

        content_hash, size_bytes, wrapped_dek, dek_iv, file_iv = compute_sha256_and_save_encrypted(
            temp_stream, temp_dest, kek_bytes
        )

        # Storage quota check
        if user.storage_used_bytes + size_bytes > user.storage_quota_bytes:
            if temp_dest.exists():
                temp_dest.unlink()
            return Response({
                "error": f"Storage quota exceeded. Used: {user.storage_used_bytes}, Limit: {user.storage_quota_bytes}, File: {size_bytes}",
                "code": "STORAGE_QUOTA_EXCEEDED"
            }, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        # Deduplication check
        final_dest = settings.STORAGE_ROOT / f"{content_hash}.enc"
        if final_dest.exists():
            # Blob already exists on disk — deduplicated!
            if temp_dest.exists():
                temp_dest.unlink()
            # Reuse existing FileVersion encryption details if available
            existing_ver = FileVersion.objects(content_hash=content_hash).first()
            if existing_ver:
                wrapped_dek = existing_ver.wrapped_dek
                dek_iv = existing_ver.dek_iv
                file_iv = existing_ver.iv
        else:
            # Move temp file to content-addressed name
            temp_dest.rename(final_dest)
            user.storage_used_bytes += size_bytes
            user.save()

        file_record = File(
            name=filename,
            owner=user,
            parent_folder=parent_folder,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        file_record.save()

        ver_record = FileVersion(
            file=file_record,
            version_number=1,
            content_hash=content_hash,
            size_bytes=size_bytes,
            storage_path=str(final_dest),
            wrapped_dek=wrapped_dek,
            dek_iv=dek_iv,
            iv=file_iv,
            created_at=datetime.utcnow(),
            uploaded_by=user
        )
        ver_record.save()

        file_record.current_version = ver_record
        file_record.save()

        return Response(file_record.to_dict(), status=status.HTTP_201_CREATED)

class FileDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        """Get file metadata."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
            return Response(file_record.to_dict(), status=status.HTTP_200_OK)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, id):
        """Rename or move file (change name or parent_id)."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.headers.get('X-Device-Id') or request.data.get('device_id')
        if not FileLockService.can_modify(file_record, request.user, device_id):
            return Response({"error": "File is currently locked", "code": "FILE_LOCKED"}, status=status.HTTP_423_LOCKED)

        if 'name' in request.data:
            new_name = request.data['name'].strip()
            if new_name:
                file_record.name = new_name

        if 'parent_id' in request.data:
            parent_id = request.data['parent_id']
            try:
                parent_folder = resolve_parent_folder(parent_id, request.user)
                file_record.parent_folder = parent_folder
            except Http404:
                return Response({"error": "Target parent folder not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        file_record.updated_at = datetime.utcnow()
        file_record.save()
        return Response(file_record.to_dict(), status=status.HTTP_200_OK)

    def delete(self, request, id):
        """Soft-delete file (move to trash)."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
            device_id = request.headers.get('X-Device-Id') or request.data.get('device_id')
            if not FileLockService.can_modify(file_record, request.user, device_id):
                return Response({"error": "File is currently locked", "code": "FILE_LOCKED"}, status=status.HTTP_423_LOCKED)
                
            file_record.deleted = True
            file_record.updated_at = datetime.utcnow()
            file_record.save()
            return Response({"detail": "File moved to trash."}, status=status.HTTP_200_OK)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

class FileRestoreView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        """Restore soft-deleted file from trash."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
            device_id = request.headers.get('X-Device-Id') or request.data.get('device_id')
            if not FileLockService.can_modify(file_record, request.user, device_id):
                return Response({"error": "File is currently locked", "code": "FILE_LOCKED"}, status=status.HTTP_423_LOCKED)
                
            file_record.deleted = False
            file_record.updated_at = datetime.utcnow()
            file_record.save()
            return Response(file_record.to_dict(), status=status.HTTP_200_OK)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

class FilePermanentDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, id):
        """Permanently delete file."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
            device_id = request.headers.get('X-Device-Id') or request.data.get('device_id')
            if not FileLockService.can_modify(file_record, request.user, device_id):
                return Response({"error": "File is currently locked", "code": "FILE_LOCKED"}, status=status.HTTP_423_LOCKED)
                
            # Delete file versions
            FileVersion.objects(file=file_record).delete()
            file_record.delete()
            return Response({"detail": "File permanently deleted."}, status=status.HTTP_200_OK)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

class FileContentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        """Download current version's bytes (streaming decrypted response)."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        if not file_record.current_version:
            return Response({"error": "File has no content", "code": "NO_CONTENT"}, status=status.HTTP_404_NOT_FOUND)

        ver = file_record.current_version
        source_path = Path(ver.storage_path)

        if not source_path.exists():
            return Response({"error": "Stored file blob missing from disk", "code": "FILE_MISSING"}, status=status.HTTP_404_NOT_FOUND)

        kek_bytes = get_master_kek()
        stream_gen = decrypt_file_stream(source_path, ver.wrapped_dek, ver.dek_iv, ver.iv, kek_bytes)

        response = StreamingHttpResponse(stream_gen, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{file_record.name}"'
        response['Content-Length'] = str(ver.size_bytes)
        response['X-Content-Hash'] = ver.content_hash
        return response

    def put(self, request, id):
        """Upload new content to an existing file, creating a new FileVersion."""
        user = request.user
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.headers.get('X-Device-Id') or request.data.get('device_id')
        if not FileLockService.can_modify(file_record, request.user, device_id):
            return Response({"error": "File is currently locked", "code": "FILE_LOCKED"}, status=status.HTTP_423_LOCKED)
            
        operation_id = request.data.get('operation_id')
        if operation_id and file_record.last_operation_id == operation_id:
            # Idempotent retry hit! Just return the current state
            return Response(file_record.to_dict(), status=status.HTTP_200_OK)

        expected_version = request.data.get('expected_version')
        if expected_version is not None:
            current_version = file_record.current_version.version_number if file_record.current_version else 0
            if int(expected_version) != current_version:
                return Response({"error": "Version conflict", "code": "CONFLICT"}, status=status.HTTP_409_CONFLICT)

        file_obj = request.FILES.get('file') or request.body
        if not file_obj:
            return Response({"error": "No file content provided.", "code": "VALIDATION_ERROR"}, status=status.HTTP_400_BAD_REQUEST)

        kek_bytes = get_master_kek()

        if isinstance(file_obj, bytes):
            stream = io.BytesIO(file_obj)
        else:
            stream = file_obj

        import uuid
        temp_dest = settings.STORAGE_ROOT / f"temp_{uuid.uuid4().hex}"
        content_hash, size_bytes, wrapped_dek, dek_iv, file_iv = compute_sha256_and_save_encrypted(
            stream, temp_dest, kek_bytes
        )

        if user.storage_used_bytes + size_bytes > user.storage_quota_bytes:
            if temp_dest.exists():
                temp_dest.unlink()
            return Response({
                "error": "Storage quota exceeded.",
                "code": "STORAGE_QUOTA_EXCEEDED"
            }, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        final_dest = settings.STORAGE_ROOT / f"{content_hash}.enc"
        if final_dest.exists():
            if temp_dest.exists():
                temp_dest.unlink()
            existing_ver = FileVersion.objects(content_hash=content_hash).first()
            if existing_ver:
                wrapped_dek = existing_ver.wrapped_dek
                dek_iv = existing_ver.dek_iv
                file_iv = existing_ver.iv
        else:
            temp_dest.rename(final_dest)
            user.storage_used_bytes += size_bytes
            user.save()

        next_ver_num = (file_record.current_version.version_number + 1) if file_record.current_version else 1

        ver_record = FileVersion(
            file=file_record,
            version_number=next_ver_num,
            content_hash=content_hash,
            size_bytes=size_bytes,
            storage_path=str(final_dest),
            wrapped_dek=wrapped_dek,
            dek_iv=dek_iv,
            iv=file_iv,
            created_at=datetime.utcnow(),
            uploaded_by=user
        )
        ver_record.save()

        file_record.current_version = ver_record
        file_record.updated_at = datetime.utcnow()
        if operation_id:
            file_record.last_operation_id = operation_id
        file_record.save()

        return Response(file_record.to_dict(), status=status.HTTP_200_OK)
