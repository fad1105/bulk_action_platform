import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.bulk_actions.models import (
    BulkAction,
    BulkActionChunk,
    BulkActionLog,
    BulkActionStatus,
    ChunkStatus,
    LogStatus,
)
from apps.core.rate_limiter import RedisRateLimiter
from apps.entities.models import Contact


@pytest.mark.django_db
class TestBulkActionAPI:
    """Test REST API endpoints for the Bulk Action Platform."""

    def setup_method(self) -> None:
        self.client = APIClient()
        self.account_id = "api_test_account"
        self.rate_limiter = RedisRateLimiter()
        self.rate_limiter.reset(self.account_id)

    def teardown_method(self) -> None:
        self.rate_limiter.reset(self.account_id)

    def test_post_bulk_action_creates_action_and_chunks(self) -> None:
        c1 = Contact.objects.create(name="Api 1", email="api1@example.com", status="active")
        c2 = Contact.objects.create(name="Api 2", email="api2@example.com", status="active")

        payload = {
            "account_id": self.account_id,
            "entity_type": "contact",
            "action_type": "bulk_update",
            "payload": {
                "entity_ids": [c1.id, c2.id],
                "fields": {"status": "inactive"},
            },
            "chunk_size": 1,
        }

        response = self.client.post("/api/bulk-actions/", data=payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.data
        assert data["account_id"] == self.account_id
        assert data["entity_type"] == "contact"
        assert data["total_count"] == 2
        assert data["status"] in [BulkActionStatus.RUNNING, BulkActionStatus.PENDING]

        # Verify chunks created
        action_id = data["id"]
        chunks = BulkActionChunk.objects.filter(bulk_action_id=action_id)
        assert chunks.count() == 2

    def test_post_bulk_action_rate_limit_exceeded_returns_429(self) -> None:
        # Pre-consume 9,999 from the rate limiter
        self.rate_limiter.check_and_consume(self.account_id, 9999)

        c1 = Contact.objects.create(name="Api Limiter", email="limit1@example.com", status="active")
        c2 = Contact.objects.create(name="Api Limiter 2", email="limit2@example.com", status="active")

        payload = {
            "account_id": self.account_id,
            "entity_type": "contact",
            "action_type": "bulk_update",
            "payload": {
                "entity_ids": [c1.id, c2.id],
                "fields": {"status": "inactive"},
            },
        }

        # Requesting 2 entities when 1 remaining: should return 429
        response = self.client.post("/api/bulk-actions/", data=payload, format="json")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        data = response.data
        assert data["error"] == "Rate limit exceeded"
        assert data["account_id"] == self.account_id
        assert data["limit_per_minute"] == 10000

    def test_get_bulk_actions_list_and_filters(self) -> None:
        a1 = BulkAction.objects.create(
            account_id=self.account_id,
            entity_type="contact",
            action_type="bulk_update",
            status=BulkActionStatus.RUNNING,
            total_count=10,
        )
        _ = BulkAction.objects.create(
            account_id="other_acc",
            entity_type="contact",
            action_type="bulk_update",
            status=BulkActionStatus.COMPLETED,
            total_count=5,
        )

        # List all
        res = self.client.get("/api/bulk-actions/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["count"] == 2

        # Filter by account_id
        res_filtered = self.client.get(f"/api/bulk-actions/?account_id={self.account_id}")
        assert res_filtered.status_code == status.HTTP_200_OK
        assert res_filtered.data["count"] == 1
        assert res_filtered.data["results"][0]["id"] == str(a1.id)

    def test_get_bulk_action_detail_and_progress(self) -> None:
        action = BulkAction.objects.create(
            account_id=self.account_id,
            entity_type="contact",
            action_type="bulk_update",
            status=BulkActionStatus.RUNNING,
            total_count=100,
            success_count=50,
            failure_count=10,
            skipped_count=5,
        )

        res = self.client.get(f"/api/bulk-actions/{action.id}/")
        assert res.status_code == status.HTTP_200_OK
        data = res.data
        assert data["id"] == str(action.id)
        assert data["total_count"] == 100
        assert data["success_count"] == 50
        assert data["failure_count"] == 10
        assert data["skipped_count"] == 5
        assert data["progress_percentage"] == 65.0

    def test_get_bulk_action_stats(self) -> None:
        action = BulkAction.objects.create(
            account_id=self.account_id,
            entity_type="contact",
            action_type="bulk_update",
            status=BulkActionStatus.RUNNING,
            total_count=200,
            success_count=100,
        )
        BulkActionChunk.objects.create(
            bulk_action=action,
            chunk_index=0,
            start_index=0,
            end_index=99,
            status=ChunkStatus.COMPLETED,
        )
        BulkActionChunk.objects.create(
            bulk_action=action,
            chunk_index=1,
            start_index=100,
            end_index=199,
            status=ChunkStatus.RUNNING,
        )

        res = self.client.get(f"/api/bulk-actions/{action.id}/stats/")
        assert res.status_code == status.HTTP_200_OK
        data = res.data
        assert data["id"] == str(action.id)
        assert data["total_count"] == 200
        assert data["success_count"] == 100
        assert data["progress_percentage"] == 50.0
        chunks = data["chunks"]
        assert chunks["total"] == 2
        assert chunks["completed"] == 1
        assert chunks["running"] == 1

    def test_get_bulk_action_logs_paginated_and_filtered(self) -> None:
        action = BulkAction.objects.create(
            account_id=self.account_id,
            entity_type="contact",
            action_type="bulk_update",
            status=BulkActionStatus.COMPLETED,
        )
        BulkActionLog.objects.create(
            bulk_action=action,
            entity_id="101",
            status=LogStatus.SUCCESS,
        )
        BulkActionLog.objects.create(
            bulk_action=action,
            entity_id="102",
            status=LogStatus.SKIPPED,
            error_message="Duplicate email",
        )
        BulkActionLog.objects.create(
            bulk_action=action,
            entity_id="103",
            status=LogStatus.ERROR,
            error_message="Validation error",
        )

        # All logs
        res = self.client.get(f"/api/bulk-actions/{action.id}/logs/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["count"] == 3

        # Filter by SKIPPED
        res_skipped = self.client.get(f"/api/bulk-actions/{action.id}/logs/?status=SKIPPED")
        assert res_skipped.status_code == status.HTTP_200_OK
        assert res_skipped.data["count"] == 1
        assert res_skipped.data["results"][0]["entity_id"] == "102"
        assert res_skipped.data["results"][0]["status"] == "SKIPPED"

    def test_swagger_and_openapi_endpoints(self) -> None:
        """Verify OpenAPI schema, Swagger UI, and Redoc endpoints load successfully."""
        # 1. OpenAPI schema
        schema_res = self.client.get("/api/schema/")
        assert schema_res.status_code == status.HTTP_200_OK
        assert "openapi" in schema_res.content.decode().lower()

        # 2. Swagger UI
        swagger_res = self.client.get("/api/docs/")
        assert swagger_res.status_code == status.HTTP_200_OK
        assert b"swagger-ui" in swagger_res.content

        # 3. Redoc
        redoc_res = self.client.get("/api/redoc/")
        assert redoc_res.status_code == status.HTTP_200_OK
        assert b"redoc" in redoc_res.content
