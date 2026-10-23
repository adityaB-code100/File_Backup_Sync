from django.urls import path, include
from django.contrib import admin


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/files/', include('files.urls_files')),
    path('api/folders/', include('files.urls_folders')),
    path('api/storage/', include('storage.urls')),
]
