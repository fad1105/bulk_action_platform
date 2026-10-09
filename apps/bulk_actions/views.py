import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.bulk_actions.models import BulkAction
from apps.bulk_actions.repositories import BulkActionRepository
from apps.bulk_actions.serializers import (
    BulkActionCreateSerializer,
    BulkActionDetailSerializer,
    BulkActionLogSerializer,
    BulkActionStatsSerializer,
)
from apps.bulk_actions.services.bulk_action_service import BulkActionService
from apps.core.exceptions import (
    BulkActionValidationException,
    RateLimitExceededException,
    UnsupportedActionTypeException,
    UnsupportedEntityTypeException,
)

logger = logging.getLogger(__name__)


class BulkActionPagination(PageNumberPagination):
    """Standard pagination for bulk action listings and logs."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class BulkActionViewSet(viewsets.ViewSet):
    """
    Thin ViewSet managing Bulk Actions according to layered architecture principles.

    Delegates all domain and orchestration logic to BulkActionService.
    """

    pagination_class = BulkActionPagination
    queryset = BulkAction.objects.none()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.bulk_action_service = BulkActionService()
        self.bulk_action_repo = BulkActionRepository()

    @extend_schema(
        summary="Create a bulk action",
        description="Validates parameters, enforces tenant rate limits (10,000 entities/minute), partitions workload into chunks, and queues Celery tasks.",
        request=BulkActionCreateSerializer,
        responses={
            201: BulkActionDetailSerializer,
            400: OpenApiResponse(description="Validation or unsupported entity/action error"),
            429: OpenApiResponse(description="Rate limit exceeded (10,000 entities per minute per tenant)"),
        },
        tags=["Bulk Actions"],
    )
    def create(self, request) -> Response:
        """
        POST /api/bulk-actions/
        Validate request, enforce rate limits, and initiate/schedule bulk action chunking.
        """
        serializer = BulkActionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dto = serializer.to_dto()
        try:
            bulk_action = self.bulk_action_service.create_bulk_action(dto)
            response_serializer = BulkActionDetailSerializer(bulk_action)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        except RateLimitExceededException as exc:
            return Response(
                {
                    "error": "Rate limit exceeded",
                    "account_id": exc.account_id,
                    "limit_per_minute": exc.limit,
                    "current_usage": exc.current_usage,
                    "requested": exc.requested,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except (
            BulkActionValidationException,
            UnsupportedEntityTypeException,
            UnsupportedActionTypeException,
        ) as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @extend_schema(
        summary="List bulk actions",
        description="List bulk actions with optional filtering by account_id, status, or entity_type.",
        parameters=[
            OpenApiParameter("account_id", str, description="Filter by tenant account identifier"),
            OpenApiParameter(
                "status", str, description="Filter by status (PENDING, RUNNING, COMPLETED, FAILED, SCHEDULED)"
            ),
            OpenApiParameter("entity_type", str, description="Filter by entity type (contact, lead)"),
        ],
        responses={200: BulkActionDetailSerializer(many=True)},
        tags=["Bulk Actions"],
    )
    def list(self, request) -> Response:
        """
        GET /api/bulk-actions/
        List bulk actions with optional filtering.
        """
        account_id = request.query_params.get("account_id")
        status_filter = request.query_params.get("status")
        entity_type = request.query_params.get("entity_type")

        queryset = self.bulk_action_repo.list_actions(
            account_id=account_id,
            status=status_filter,
            entity_type=entity_type,
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = BulkActionDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Retrieve bulk action status & progress",
        description="Retrieve progress percentage, execution status, and counts for a specific bulk action.",
        responses={
            200: BulkActionDetailSerializer,
            404: OpenApiResponse(description="BulkAction not found"),
        },
        tags=["Bulk Actions"],
    )
    def retrieve(self, request, pk=None) -> Response:
        """
        GET /api/bulk-actions/{id}/
        Retrieve bulk action status and overall progress.
        """
        bulk_action = self.bulk_action_repo.get_by_id(pk)
        if not bulk_action:
            return Response(
                {"error": f"BulkAction '{pk}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = BulkActionDetailSerializer(bulk_action)
        return Response(serializer.data)

    @extend_schema(
        summary="Get bulk action statistics summary",
        description="Return statistical summary and chunk breakdown for a bulk action.",
        responses={
            200: BulkActionStatsSerializer,
            404: OpenApiResponse(description="BulkAction not found"),
        },
        tags=["Bulk Actions"],
    )
    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None) -> Response:
        """
        GET /api/bulk-actions/{id}/stats/
        Return statistical summary and chunk breakdown for a bulk action.
        """
        stats_dto = self.bulk_action_service.get_action_stats(pk)
        if not stats_dto:
            return Response(
                {"error": f"BulkAction '{pk}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = BulkActionStatsSerializer(stats_dto)
        return Response(serializer.data)

    @extend_schema(
        summary="Get paginated execution logs",
        description="Paginated list of record execution logs (filter by ?status=SUCCESS|ERROR|SKIPPED).",
        parameters=[
            OpenApiParameter("status", str, description="Filter by log status (SUCCESS, ERROR, SKIPPED)"),
        ],
        responses={
            200: BulkActionLogSerializer(many=True),
            404: OpenApiResponse(description="BulkAction not found"),
        },
        tags=["Bulk Actions"],
    )
    @action(detail=True, methods=["get"])
    def logs(self, request, pk=None) -> Response:
        """
        GET /api/bulk-actions/{id}/logs/
        Paginated list of record execution logs (filter by ?status=SUCCESS|ERROR|SKIPPED).
        """
        bulk_action = self.bulk_action_repo.get_by_id(pk)
        if not bulk_action:
            return Response(
                {"error": f"BulkAction '{pk}' not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        status_filter = request.query_params.get("status")
        logs_qs = self.bulk_action_service.get_action_logs(pk, status=status_filter)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(logs_qs, request)
        serializer = BulkActionLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
