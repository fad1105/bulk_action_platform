import pytest

from apps.bulk_actions.models import BulkAction, BulkActionChunk, BulkActionLog, BulkActionStatus, ChunkStatus
from apps.bulk_actions.services.chunk_execution_service import ChunkExecutionService
from apps.entities.models import Contact


@pytest.mark.django_db
class TestIdempotency:
    """Test idempotency guarantees for chunk execution."""

    def test_rerunning_completed_chunk_does_not_duplicate_results(self) -> None:
        c1 = Contact.objects.create(name="User 1", email="user1@idemp.com", status="initial")
        c2 = Contact.objects.create(name="User 2", email="user2@idemp.com", status="initial")

        action = BulkAction.objects.create(
            account_id="acc_idemp_1",
            entity_type="contact",
            action_type="bulk_update",
            payload={"fields": {"status": "completed_status"}},
            total_count=2,
            status=BulkActionStatus.RUNNING,
        )
        chunk = BulkActionChunk.objects.create(
            bulk_action=action,
            chunk_index=0,
            start_index=0,
            end_index=1,
            entity_ids=[c1.id, c2.id],
            status=ChunkStatus.PENDING,
        )

        chunk_service = ChunkExecutionService()

        # First run: should execute and complete
        result1 = chunk_service.execute_chunk(chunk.id)
        assert result1.status == ChunkStatus.COMPLETED
        assert result1.success_count == 2

        action.refresh_from_db()
        assert action.success_count == 2
        assert BulkActionLog.objects.filter(bulk_action=action).count() == 2

        # Second run: simulate duplicate task delivery from Celery broker
        result2 = chunk_service.execute_chunk(chunk.id)
        assert result2.status == ChunkStatus.COMPLETED
        assert result2.success_count == 0  # No new counts added

        # Assert database counts remain strictly 2, not 4
        action.refresh_from_db()
        assert action.success_count == 2
        assert BulkActionLog.objects.filter(bulk_action=action).count() == 2

    def test_rerunning_failed_chunk_does_not_double_count_when_retried(self) -> None:
        c = Contact.objects.create(name="Retry User", email="retry@idemp.com", status="init")

        action = BulkAction.objects.create(
            account_id="acc_idemp_2",
            entity_type="contact",
            action_type="bulk_update",
            payload={"fields": {"status": "success_status"}},
            total_count=1,
            status=BulkActionStatus.RUNNING,
        )
        chunk = BulkActionChunk.objects.create(
            bulk_action=action,
            chunk_index=0,
            start_index=0,
            end_index=0,
            entity_ids=[c.id],
            status=ChunkStatus.FAILED,
            error_message="Simulated prior failure",
        )

        chunk_service = ChunkExecutionService()
        result = chunk_service.execute_chunk(chunk.id)

        assert result.status == ChunkStatus.COMPLETED
        assert result.success_count == 1

        action.refresh_from_db()
        assert action.success_count == 1
        assert BulkActionLog.objects.filter(bulk_action=action, status="SUCCESS").count() == 1
