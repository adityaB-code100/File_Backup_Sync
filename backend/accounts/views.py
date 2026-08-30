from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.models import User
from accounts.auth import get_tokens_for_user
import mongoengine as me

class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {"error": "Email and password are required.", "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects(email=email).first():
            return Response(
                {"error": "User with this email already exists.", "code": "USER_EXISTS"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User(email=email)
        user.set_password(password)
        user.save()

        tokens = get_tokens_for_user(user)

        return Response({
            "user": user.to_dict(),
            "access": tokens['access'],
            "refresh": tokens['refresh']
        }, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {"error": "Email and password are required.", "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects(email=email).first()
        if not user or not user.check_password(password):
            return Response(
                {"error": "Invalid email or password.", "code": "INVALID_CREDENTIALS"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        tokens = get_tokens_for_user(user)

        return Response({
            "access": tokens['access'],
            "refresh": tokens['refresh'],
            "user": user.to_dict()
        }, status=status.HTTP_200_OK)

class RefreshTokenView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        refresh_str = request.data.get('refresh')
        if not refresh_str:
            return Response(
                {"error": "Refresh token is required.", "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            refresh = RefreshToken(refresh_str)
            user_id = refresh.payload.get('user_id')
            user = User.objects.get(id=user_id)
            new_tokens = get_tokens_for_user(user)
            return Response({
                "access": new_tokens['access'],
                "refresh": new_tokens['refresh']
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": f"Invalid or expired refresh token: {str(e)}", "code": "UNAUTHORIZED"},
                status=status.HTTP_401_UNAUTHORIZED
            )

class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass  # Blacklisting optional or ignored if not enabled
        return Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)

class UserMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(request.user.to_dict(), status=status.HTTP_200_OK)
