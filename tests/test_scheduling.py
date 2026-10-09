from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bulk_actions.dtos import BulkActionCreateDTO
from apps.bulk_actions.models import BulkActionStatus
from apps.bulk_actions.services.bulk_action_service import BulkActionService
from apps.entities.models import Contact


@pytest.mark.django_db
class TestScheduling:
    """Test scheduled bulk action lifecycle and Celery Beat integration."""

    def test_future_scheduled_action_is_not_dispatched_immediately(self) -> None:
        c1 = Contact.objects.create(name="Future Contact", email="future@example.com", status="active")
        dispatched_chunks: list[int] = []

        service = BulkActionService(task_dispatcher=lambda cid: dispatched_chunks.append(cid))

        future_time = timezone.now() + timedelta(hours=2)
        dto = BulkActionCreateDTO(
            account_id="acc_sched_1",
            entity_type="contact",
            action_type="bulk_update",
            payload={"entity_ids": [c1.id], "fields": {"status": "future_updated"}},
            scheduled_at=future_time,
        )

        action = service.create_bulk_action(dto)

        assert action.status == BulkActionStatus.SCHEDULED
        assert action.scheduled_at == future_time
        # No tasks should be dispatched yet
        assert len(dispatched_chunks) == 0

    def test_celery_beat_task_triggers_due_actions(self) -> None:
        c1 = Contact.objects.create(name="Due Contact", email="due@example.com", status="active")
        dispatched_chunks: list[int] = []

        service = BulkActionService(task_dispatcher=lambda cid: dispatched_chunks.append(cid))

        # Schedule 5 minutes in the past so it is due
        past_due_time = timezone.now() - timedelta(minutes=5)
        dto = BulkActionCreateDTO(
            account_id="acc_sched_2",
            entity_type="contact",
            action_type="bulk_update",
            payload={"entity_ids": [c1.id], "fields": {"status": "due_updated"}},
            scheduled_at=past_due_time,
        )
        action = service.create_bulk_action(dto)
        assert action.status == BulkActionStatus.SCHEDULED

        # Celery Beat trigger
        triggered = service.trigger_scheduled_actions()
        assert str(action.id) in triggered

        action.refresh_from_db()
        assert action.status == BulkActionStatus.RUNNING
        assert len(dispatched_chunks) == 1
