import time
import uuid
import logging

logger = logging.getLogger("cloud_storage.request")

class RequestLoggingMiddleware:
    """
    Structured API request logging middleware.
    Logs HTTP method, endpoint, status code, duration, correlation ID,
    and authenticated user identity without exposing credentials, JWTs, or keys.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        headers = getattr(request, "headers", {})
        correlation_id = (
            (headers.get("X-Correlation-ID") if hasattr(headers, "get") else None)
            or (headers.get("X-Request-ID") if hasattr(headers, "get") else None)
            or uuid.uuid4().hex[:8]
        )
        request.correlation_id = correlation_id
        start_time = time.perf_counter()

        try:
            response = self.get_response(request)
        except Exception:
            duration_ms = (time.perf_counter() - start_time) * 1000
            user_repr = self._get_user_repr(request)
            device_suffix = self._get_device_suffix(request)
            log_msg = (
                f"[{correlation_id}] {request.method} {request.get_full_path()} "
                f"-> 500 ({duration_ms:.1f}ms) [User: {user_repr}]{device_suffix}"
            )
            logger.error(log_msg)
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000
        user_repr = self._get_user_repr(request)
        device_suffix = self._get_device_suffix(request)

        status_code = response.status_code
        log_msg = (
            f"[{correlation_id}] {request.method} {request.get_full_path()} "
            f"-> {status_code} ({duration_ms:.1f}ms) [User: {user_repr}]{device_suffix}"
        )

        if status_code >= 500:
            logger.error(log_msg)
        elif status_code >= 400:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        response["X-Correlation-ID"] = correlation_id
        return response

    def _get_user_repr(self, request):
        user = getattr(request, "user", None)
        if user and getattr(user, "is_authenticated", False):
            return getattr(user, "email", str(getattr(user, "id", "authenticated")))
        return "anonymous"

    def _get_device_suffix(self, request):
        headers = getattr(request, "headers", {})
        device_id = headers.get("X-Device-Id") if hasattr(headers, "get") else None
        return f" [Device: {device_id}]" if device_id else ""
