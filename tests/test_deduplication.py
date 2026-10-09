import pytest

from apps.bulk_actions.dtos import BulkActionCreateDTO
from apps.bulk_actions.models import BulkActionLog, LogStatus
from apps.bulk_actions.services.bulk_action_service import BulkActionService
from apps.bulk_actions.services.chunk_execution_service import ChunkExecutionService
from apps.entities.models import Contact


@pytest.mark.django_db
class TestDeduplication:
    """Test deduplication within a bulk action based on email field."""

    def test_deduplication_skips_duplicate_emails_and_logs_skipped(self) -> None:
        # Note: In Contact model, email is unique in the database.
        # But if the bulk action payload provides duplicate entity IDs (or duplicate records in Lead model, or entity_ids with duplicates)
        c1 = Contact.objects.create(name="Primary Contact", email="shared@domain.com", status="active")
        c2 = Contact.objects.create(name="Other Contact", email="other@domain.com", status="active")

        # Test: If payload specifies [c1.id, c1.id, c2.id] (same email referenced multiple times in bulk action)
        dispatched_chunks: list[int] = []
        service = BulkActionService(task_dispatcher=lambda cid: dispatched_chunks.append(cid))

        dto = BulkActionCreateDTO(
            account_id="acc_dedup_1",
            entity_type="contact",
            action_type="bulk_update",
            payload={
                "entity_ids": [c1.id, c1.id, c2.id],
                "fields": {"status": "updated"},
            },
            chunk_size=10,
        )
        action = service.create_bulk_action(dto)

        chunk_service = ChunkExecutionService()
        for cid in dispatched_chunks:
            chunk_service.execute_chunk(cid)

        action.refresh_from_db()
        assert action.success_count == 2
        assert action.skipped_count == 1
        assert action.failure_count == 0

        # Verify logs
        logs = list(BulkActionLog.objects.filter(bulk_action=action).order_by("id"))
        assert len(logs) == 3
        # First c1: SUCCESS
        assert logs[0].entity_id == str(c1.id)
        assert logs[0].status == LogStatus.SUCCESS
        # Duplicate c1: SKIPPED
        assert logs[1].entity_id == str(c1.id)
        assert logs[1].status == LogStatus.SKIPPED
        assert "Duplicate entity with email" in logs[1].error_message
        # c2: SUCCESS
        assert logs[2].entity_id == str(c2.id)
        assert logs[2].status == LogStatus.SUCCESS

    def test_deduplication_scope_is_per_bulk_action(self) -> None:
        """Verify that deduplication in Action 1 does not suppress emails in Action 2."""
        c = Contact.objects.create(name="Single Contact", email="reuse@example.com", status="initial")

        chunk_service = ChunkExecutionService()

        # Action 1
        dispatched_1: list[int] = []
        s1 = BulkActionService(task_dispatcher=lambda cid: dispatched_1.append(cid))
        action1 = s1.create_bulk_action(
            BulkActionCreateDTO(
                account_id="acc_scope_1",
                entity_type="contact",
                action_type="bulk_update",
                payload={"entity_ids": [c.id], "fields": {"status": "step1"}},
            )
        )
        for cid in dispatched_1:
            chunk_service.execute_chunk(cid)

        action1.refresh_from_db()
        assert action1.success_count == 1
        assert action1.skipped_count == 0

        # Action 2 (same email should succeed, not be skipped)
        dispatched_2: list[int] = []
        s2 = BulkActionService(task_dispatcher=lambda cid: dispatched_2.append(cid))
        action2 = s2.create_bulk_action(
            BulkActionCreateDTO(
                account_id="acc_scope_1",
                entity_type="contact",
                action_type="bulk_update",
                payload={"entity_ids": [c.id], "fields": {"status": "step2"}},
            )
        )
        for cid in dispatched_2:
            chunk_service.execute_chunk(cid)

        action2.refresh_from_db()
        assert action2.success_count == 1
        assert action2.skipped_count == 0
