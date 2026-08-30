from django.urls import path
from accounts.views import RegisterView, LoginView, RefreshTokenView, LogoutView, UserMeView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='auth-register'),
    path('login/', LoginView.as_view(), name='auth-login'),
    path('refresh/', RefreshTokenView.as_view(), name='auth-refresh'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('me/', UserMeView.as_view(), name='auth-me'),
]
