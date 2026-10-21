import unittest
from unittest.mock import MagicMock, patch
from django.test import RequestFactory, SimpleTestCase
from django.http import HttpResponse
from cloud_storage.middleware import RequestLoggingMiddleware

class RequestLoggingMiddlewareTestCase(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_generates_correlation_id_and_sets_header(self):
        request = self.factory.get('/api/test/')
        get_response = MagicMock(return_value=HttpResponse("OK", status=200))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.info') as mock_log:
            response = middleware(request)

            self.assertEqual(response.status_code, 200)
            self.assertTrue(hasattr(request, 'correlation_id'))
            self.assertEqual(response['X-Correlation-ID'], request.correlation_id)
            self.assertEqual(len(request.correlation_id), 8)
            mock_log.assert_called_once()
            log_arg = mock_log.call_args[0][0]
            self.assertIn(f"[{request.correlation_id}] GET /api/test/ -> 200", log_arg)
            self.assertIn("[User: anonymous]", log_arg)

    def test_preserves_existing_correlation_id(self):
        request = self.factory.get('/api/test/', HTTP_X_CORRELATION_ID='client-cid-999')
        get_response = MagicMock(return_value=HttpResponse("OK", status=200))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.info') as mock_log:
            response = middleware(request)
            self.assertEqual(request.correlation_id, 'client-cid-999')
            self.assertEqual(response['X-Correlation-ID'], 'client-cid-999')
            mock_log.assert_called_once()
            self.assertIn("[client-cid-999]", mock_log.call_args[0][0])

    def test_preserves_request_id_fallback(self):
        request = self.factory.get('/api/test/', HTTP_X_REQUEST_ID='req-id-777')
        get_response = MagicMock(return_value=HttpResponse("OK", status=200))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.info') as mock_log:
            response = middleware(request)
            self.assertEqual(request.correlation_id, 'req-id-777')
            self.assertEqual(response['X-Correlation-ID'], 'req-id-777')
            mock_log.assert_called_once()
            self.assertIn("[req-id-777]", mock_log.call_args[0][0])

    def test_logs_authenticated_user_email(self):
        request = self.factory.get('/api/test/')
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.email = 'engineer@example.com'
        get_response = MagicMock(return_value=HttpResponse("OK", status=200))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.info') as mock_log:
            middleware(request)
            mock_log.assert_called_once()
            self.assertIn("[User: engineer@example.com]", mock_log.call_args[0][0])

    def test_logs_device_id_suffix(self):
        request = self.factory.get('/api/test/', HTTP_X_DEVICE_ID='desktop-vault-client')
        get_response = MagicMock(return_value=HttpResponse("OK", status=200))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.info') as mock_log:
            middleware(request)
            mock_log.assert_called_once()
            self.assertIn("[Device: desktop-vault-client]", mock_log.call_args[0][0])

    def test_warning_level_for_4xx(self):
        request = self.factory.get('/api/not-found/')
        get_response = MagicMock(return_value=HttpResponse("Not Found", status=404))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.warning') as mock_warn:
            response = middleware(request)
            self.assertEqual(response.status_code, 404)
            mock_warn.assert_called_once()
            self.assertIn("-> 404", mock_warn.call_args[0][0])

    def test_error_level_for_5xx(self):
        request = self.factory.get('/api/error/')
        get_response = MagicMock(return_value=HttpResponse("Server Error", status=500))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.error') as mock_err:
            response = middleware(request)
            self.assertEqual(response.status_code, 500)
            mock_err.assert_called_once()
            self.assertIn("-> 500", mock_err.call_args[0][0])

    def test_error_level_and_reraise_on_exception(self):
        request = self.factory.get('/api/crash/')
        get_response = MagicMock(side_effect=RuntimeError("Database down"))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.error') as mock_err:
            with self.assertRaises(RuntimeError):
                middleware(request)
            mock_err.assert_called_once()
            self.assertIn("-> 500", mock_err.call_args[0][0])

    def test_does_not_log_sensitive_data(self):
        request = self.factory.post(
            '/api/auth/login/',
            data={'email': 'user@example.com', 'password': 'SecretPassword123!'},
            HTTP_AUTHORIZATION='Bearer secret_jwt_token',
            content_type='application/json'
        )
        get_response = MagicMock(return_value=HttpResponse('{"access": "top_secret_token"}', status=200))
        middleware = RequestLoggingMiddleware(get_response)

        with patch('cloud_storage.middleware.logger.info') as mock_log:
            middleware(request)
            mock_log.assert_called_once()
            log_msg = mock_log.call_args[0][0]
            self.assertNotIn("SecretPassword123!", log_msg)
            self.assertNotIn("secret_jwt_token", log_msg)
            self.assertNotIn("top_secret_token", log_msg)
            self.assertNotIn("password", log_msg.lower())
