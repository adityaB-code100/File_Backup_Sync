from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

def custom_exception_handler(exc, context):
    """Custom exception handler returning a consistent JSON error shape:
    {"error": "...", "code": "..."}
    """
    response = exception_handler(exc, context)

    if response is not None:
        error_msg = "An error occurred."
        error_code = "ERROR"

        if isinstance(response.data, dict):
            if 'detail' in response.data:
                error_msg = str(response.data['detail'])
                error_code = getattr(exc, 'default_code', 'ERROR').upper()
            else:
                # Combine non-field errors or list of field errors into a readable string
                errors = []
                for field, val in response.data.items():
                    if isinstance(val, list):
                        val_str = " ".join([str(v) for v in val])
                    else:
                        val_str = str(val)
                    errors.append(f"{field}: {val_str}")
                error_msg = "; ".join(errors) if errors else "Validation failed."
                error_code = "VALIDATION_ERROR"
        elif isinstance(response.data, list):
            error_msg = " ".join([str(item) for item in response.data])
            error_code = "VALIDATION_ERROR"

        # Special status overrides
        if response.status_code == status.HTTP_401_UNAUTHORIZED:
            error_code = "UNAUTHORIZED"
        elif response.status_code == status.HTTP_403_FORBIDDEN:
            error_code = "PERMISSION_DENIED"
        elif response.status_code == status.HTTP_404_NOT_FOUND:
            error_code = "NOT_FOUND"
        elif response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            error_code = "RATE_LIMIT_EXCEEDED"
        elif response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE:
            error_code = "STORAGE_QUOTA_EXCEEDED"

        response.data = {
            "error": error_msg,
            "code": error_code
        }

    return response
