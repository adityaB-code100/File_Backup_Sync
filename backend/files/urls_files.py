from django.urls import path
from files.views_files import (
    FileListCreateView, FileDetailView, FileRestoreView, FilePermanentDeleteView, FileContentView
)
from files.views_revisions import (
    RevisionListView, RevisionContentView, RevisionRestoreView
)
from files.views_sync import FileChangesView
from files.views_lock import FileLockView, FileLockRenewView, FileUnlockView

urlpatterns = [
    path('', FileListCreateView.as_view(), name='file-list-create'),
    path('changes/', FileChangesView.as_view(), name='file-changes'),
    path('<str:id>/', FileDetailView.as_view(), name='file-detail'),
    path('<str:id>/restore/', FileRestoreView.as_view(), name='file-restore'),
    path('<str:id>/permanent/', FilePermanentDeleteView.as_view(), name='file-permanent-delete'),
    path('<str:id>/content/', FileContentView.as_view(), name='file-content'),
    path('<str:id>/revisions/', RevisionListView.as_view(), name='revision-list'),
    path('<str:id>/revisions/<str:vid>/content/', RevisionContentView.as_view(), name='revision-content'),
    path('<str:id>/revisions/<str:vid>/restore/', RevisionRestoreView.as_view(), name='revision-restore'),
    path('<str:id>/lock/', FileLockView.as_view(), name='file-lock'),
    path('<str:id>/lock/renew/', FileLockRenewView.as_view(), name='file-lock-renew'),
    path('<str:id>/unlock/', FileUnlockView.as_view(), name='file-unlock'),
]
