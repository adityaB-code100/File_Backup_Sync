from django.urls import path
from storage.views import StorageUsageView

urlpatterns = [
    path('usage/', StorageUsageView.as_view(), name='storage-usage'),
]
