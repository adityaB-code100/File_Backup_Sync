from django.urls import path, include

urlpatterns = [
    path('api/auth/', include('accounts.urls')),
    path('api/files/', include('files.urls_files')),
    path('api/folders/', include('files.urls_folders')),
    path('api/storage/', include('storage.urls')),
]
