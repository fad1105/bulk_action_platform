import pytest

from apps.bulk_actions.dtos import BulkActionCreateDTO
from apps.bulk_actions.models import BulkActionLog, BulkActionStatus
from apps.bulk_actions.services.bulk_action_service import BulkActionService
from apps.bulk_actions.services.chunk_execution_service import ChunkExecutionService
from apps.entities.models import Contact


@pytest.mark.django_db
class TestHorizontalScalingChunking:
    """Test chunking workload distribution and database efficiency."""

    def test_chunking_splits_workload_into_chunks(self) -> None:
        # Create 1,250 contacts efficiently with bulk_create
        contacts = [
            Contact(
                name=f"Contact {i}",
                email=f"contact_{i}@example.com",
                age=20 + (i % 50),
                status="active",
            )
            for i in range(1250)
        ]
        Contact.objects.bulk_create(contacts)
        contact_ids = list(Contact.objects.order_by("id").values_list("id", flat=True))

        dispatched_chunk_ids: list[int] = []

        def mock_dispatcher(chunk_id: int) -> None:
            dispatched_chunk_ids.append(chunk_id)

        service = BulkActionService(task_dispatcher=mock_dispatcher, default_chunk_size=500)

        dto = BulkActionCreateDTO(
            account_id="acc_chunk_test",
            entity_type="contact",
            action_type="bulk_update",
            payload={
                "entity_ids": contact_ids,
                "fields": {"status": "inactive"},
            },
            chunk_size=500,
        )

        bulk_action = service.create_bulk_action(dto)

        assert bulk_action.total_count == 1250
        assert bulk_action.status == BulkActionStatus.RUNNING

        # Verify chunks created
        chunks = list(bulk_action.chunks.order_by("chunk_index"))
        assert len(chunks) == 3

        # Chunk 0: 0 to 499 (500 records)
        assert chunks[0].chunk_index == 0
        assert chunks[0].start_index == 0
        assert chunks[0].end_index == 499
        assert len(chunks[0].entity_ids) == 500

        # Chunk 1: 500 to 999 (500 records)
        assert chunks[1].chunk_index == 1
        assert chunks[1].start_index == 500
        assert chunks[1].end_index == 999
        assert len(chunks[1].entity_ids) == 500

        # Chunk 2: 1000 to 1249 (250 records)
        assert chunks[2].chunk_index == 2
        assert chunks[2].start_index == 1000
        assert chunks[2].end_index == 1249
        assert len(chunks[2].entity_ids) == 250

        # Verify dispatcher was called for each chunk
        assert len(dispatched_chunk_ids) == 3
        assert dispatched_chunk_ids == [c.id for c in chunks]

    def test_chunk_execution_and_atomic_increments(self) -> None:
        """Verify execution of chunks updates DB, logs, and increments counters atomically."""
        contacts = [
            Contact(
                name=f"User {i}",
                email=f"user_{i}@example.com",
                age=25,
                status="active",
            )
            for i in range(50)
        ]
        Contact.objects.bulk_create(contacts)
        contact_ids = list(Contact.objects.order_by("id").values_list("id", flat=True))

        dispatched_chunk_ids: list[int] = []
        bulk_service = BulkActionService(
            task_dispatcher=lambda cid: dispatched_chunk_ids.append(cid),
            default_chunk_size=20,
        )

        dto = BulkActionCreateDTO(
            account_id="acc_exec_test",
            entity_type="contact",
            action_type="bulk_update",
            payload={
                "entity_ids": contact_ids,
                "fields": {"status": "verified"},
            },
            chunk_size=20,
        )
        bulk_action = bulk_service.create_bulk_action(dto)

        # Chunks: 20 + 20 + 10 = 3 chunks
        assert len(dispatched_chunk_ids) == 3

        chunk_service = ChunkExecutionService()
        for chunk_id in dispatched_chunk_ids:
            chunk_service.execute_chunk(chunk_id)

        bulk_action.refresh_from_db()
        assert bulk_action.status == BulkActionStatus.COMPLETED
        assert bulk_action.success_count == 50
        assert bulk_action.failure_count == 0
        assert bulk_action.skipped_count == 0

        # Verify all contacts updated
        assert Contact.objects.filter(status="verified").count() == 50

        # Verify all logs created
        assert BulkActionLog.objects.filter(bulk_action=bulk_action, status="SUCCESS").count() == 50
