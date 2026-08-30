from pathlib import Path
from datetime import datetime
from bson import ObjectId
from django.http import StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from files.models import File, FileVersion
from files.crypto_utils import get_master_kek, decrypt_file_stream

class RevisionListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        """List all versions for a file."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        revisions = FileVersion.objects(file=file_record).order_by('-version_number')
        return Response([r.to_dict() for r in revisions], status=status.HTTP_200_OK)

class RevisionContentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id, vid):
        """Download a specific past version."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        try:
            ver = FileVersion.objects.get(id=ObjectId(vid), file=file_record)
        except Exception:
            return Response({"error": "Revision not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        source_path = Path(ver.storage_path)
        if not source_path.exists():
            return Response({"error": "Stored file blob missing from disk", "code": "FILE_MISSING"}, status=status.HTTP_404_NOT_FOUND)

        kek_bytes = get_master_kek()
        stream_gen = decrypt_file_stream(source_path, ver.wrapped_dek, ver.dek_iv, ver.iv, kek_bytes)

        response = StreamingHttpResponse(stream_gen, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{file_record.name}.v{ver.version_number}"'
        response['Content-Length'] = str(ver.size_bytes)
        response['X-Content-Hash'] = ver.content_hash
        return response

class RevisionRestoreView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id, vid):
        """Restore a past version: creates a new FileVersion entry pointing at the old version's content/blob."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        try:
            target_ver = FileVersion.objects.get(id=ObjectId(vid), file=file_record)
        except Exception:
            return Response({"error": "Revision not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        current_ver_num = file_record.current_version.version_number if file_record.current_version else 0
        new_ver_num = current_ver_num + 1

        new_ver = FileVersion(
            file=file_record,
            version_number=new_ver_num,
            content_hash=target_ver.content_hash,
            size_bytes=target_ver.size_bytes,
            storage_path=target_ver.storage_path,
            wrapped_dek=target_ver.wrapped_dek,
            dek_iv=target_ver.dek_iv,
            iv=target_ver.iv,
            created_at=datetime.utcnow(),
            uploaded_by=request.user
        )
        new_ver.save()

        file_record.current_version = new_ver
        file_record.updated_at = datetime.utcnow()
        file_record.save()

        return Response({
            "detail": f"Restored version {target_ver.version_number} as new version {new_ver_num}.",
            "file": file_record.to_dict(),
            "version": new_ver.to_dict()
        }, status=status.HTTP_200_OK)
