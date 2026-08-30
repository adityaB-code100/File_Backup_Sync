from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

class StorageUsageView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Returns storage usage statistics for current user."""
        user = request.user
        used = user.storage_used_bytes
        quota = user.storage_quota_bytes
        percentage = round((used / quota * 100), 2) if quota > 0 else 0.0

        return Response({
            "storage_used_bytes": used,
            "storage_quota_bytes": quota,
            "usage_percentage": percentage
        }, status=status.HTTP_200_OK)
