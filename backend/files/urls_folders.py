from django.urls import path
from files.views_folders import FolderListCreateView, FolderDetailView

urlpatterns = [
    path('', FolderListCreateView.as_view(), name='folder-list-create'),
    path('<str:id>/', FolderDetailView.as_view(), name='folder-detail'),
]
