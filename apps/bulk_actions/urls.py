from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.bulk_actions.views import BulkActionViewSet

router = DefaultRouter()
router.register(r"bulk-actions", BulkActionViewSet, basename="bulk-action")

urlpatterns = [
    path("", include(router.urls)),
]
