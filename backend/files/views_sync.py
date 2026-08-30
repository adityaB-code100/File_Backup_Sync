from datetime import datetime
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from files.models import File, Folder
from dateutil.parser import parse as parse_date

class FileChangesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Returns files & folders updated since timestamp (ISO string or unix timestamp)."""
        since_param = request.query_params.get('since')
        if not since_param:
            return Response({"error": "'since' query parameter is required.", "code": "VALIDATION_ERROR"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Try float/int timestamp
            if since_param.isdigit() or '.' in since_param:
                since_dt = datetime.utcfromtimestamp(float(since_param))
            else:
                since_dt = parse_date(since_param)
                if since_dt.tzinfo is not None:
                    since_dt = since_dt.astimezone().replace(tzinfo=None)
        except Exception as e:
            return Response({"error": f"Invalid timestamp format: {str(e)}", "code": "VALIDATION_ERROR"}, status=status.HTTP_400_BAD_REQUEST)

        # Retrieve modified files and folders
        changed_files = File.objects(owner=request.user, updated_at__gte=since_dt)
        changed_folders = Folder.objects(owner=request.user, created_at__gte=since_dt)

        file_items = [f.to_dict() for f in changed_files]
        folder_items = [f.to_dict() for f in changed_folders]

        return Response({
            "since": since_dt.isoformat(),
            "changes": folder_items + file_items
        }, status=status.HTTP_200_OK)
