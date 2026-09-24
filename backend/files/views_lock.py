from datetime import datetime
from bson import ObjectId
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from files.models import File
from files.lock_service import FileLockService

class FileLockView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        """Get the current lock status of a file."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        FileLockService.check_and_clear_expired(file_record)
        
        return Response({
            "is_locked": file_record.is_locked,
            "lock_owner": str(file_record.lock_owner.id) if file_record.lock_owner else None,
            "lock_device_id": file_record.lock_device_id,
            "lock_expires_at": file_record.lock_expires_at.isoformat() if file_record.lock_expires_at else None
        }, status=status.HTTP_200_OK)

    def post(self, request, id):
        """Acquire a lock on a file."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.headers.get('X-Device-Id') or request.data.get('device_id')
        if not device_id:
            return Response({"error": "device_id is required", "code": "VALIDATION_ERROR"}, status=status.HTTP_400_BAD_REQUEST)

        # check if it can be modified first, before locking? No, acquire_lock handles stealing/re-acquiring gracefully if expired.
        success = FileLockService.acquire_lock(file_record, request.user, device_id)
        if success:
            return Response(file_record.to_dict(), status=status.HTTP_200_OK)
        else:
            return Response({
                "error": "File is locked by another device or user",
                "code": "FILE_LOCKED"
            }, status=status.HTTP_423_LOCKED)

class FileLockRenewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        """Renew a lock on a file."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.headers.get('X-Device-Id') or request.data.get('device_id')
        if not device_id:
            return Response({"error": "device_id is required", "code": "VALIDATION_ERROR"}, status=status.HTTP_400_BAD_REQUEST)

        success = FileLockService.renew_lock(file_record, request.user, device_id)
        if success:
            return Response(file_record.to_dict(), status=status.HTTP_200_OK)
        else:
            return Response({
                "error": "Failed to renew lock. It may have expired or is owned by another device.",
                "code": "FILE_LOCKED"
            }, status=status.HTTP_423_LOCKED)

class FileUnlockView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        """Release a lock on a file."""
        try:
            file_record = File.objects.get(id=ObjectId(id), owner=request.user)
        except Exception:
            return Response({"error": "File not found", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        device_id = request.headers.get('X-Device-Id') or request.data.get('device_id')
        if not device_id:
            return Response({"error": "device_id is required", "code": "VALIDATION_ERROR"}, status=status.HTTP_400_BAD_REQUEST)

        success = FileLockService.release_lock(file_record, request.user, device_id)
        if success:
            return Response(file_record.to_dict(), status=status.HTTP_200_OK)
        else:
            return Response({
                "error": "Failed to release lock. You do not own the lock on this file.",
                "code": "FILE_LOCKED"
            }, status=status.HTTP_423_LOCKED)
