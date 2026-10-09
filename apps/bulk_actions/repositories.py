from datetime import datetime
from typing import Any, Optional, Sequence

from django.db.models import F, QuerySet

from apps.bulk_actions.models import (
    BulkAction,
    BulkActionChunk,
    BulkActionLog,
    BulkActionStatus,
    ChunkStatus,
)


class BulkActionRepository:
    """Repository handling all database interactions for BulkAction model."""

    def create(
        self,
        account_id: str,
        entity_type: str,
        action_type: str,
        payload: dict[str, Any],
        total_count: int,
        status: str = BulkActionStatus.PENDING,
        scheduled_at: Optional[datetime] = None,
    ) -> BulkAction:
        """Create and persist a new BulkAction instance."""
        return BulkAction.objects.create(
            account_id=account_id,
            entity_type=entity_type,
            action_type=action_type,
            payload=payload,
            total_count=total_count,
            status=status,
            scheduled_at=scheduled_at,
        )

    def get_by_id(self, action_id: Any) -> Optional[BulkAction]:
        """Fetch BulkAction by primary key."""
        try:
            return BulkAction.objects.get(id=action_id)
        except BulkAction.DoesNotExist:
            return None

    def get_by_id_for_update(self, action_id: Any) -> Optional[BulkAction]:
        """Fetch BulkAction by ID acquiring row-level database lock."""
        try:
            return BulkAction.objects.select_for_update().get(id=action_id)
        except BulkAction.DoesNotExist:
            return None

    def list_actions(
        self,
        account_id: Optional[str] = None,
        status: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> QuerySet[BulkAction]:
        """List BulkActions with optional filters."""
        qs = BulkAction.objects.all().order_by("-created_at")
        if account_id:
            qs = qs.filter(account_id=account_id)
        if status:
            qs = qs.filter(status=status)
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        return qs

    def atomic_increment_counts(
        self,
        bulk_action_id: Any,
        success_count: int = 0,
        failure_count: int = 0,
        skipped_count: int = 0,
    ) -> None:
        """
        Atomically increment execution counters using Django F() expressions.

        Prevents race conditions when multiple worker chunks update the parent bulk action.
        """
        updates: dict[str, Any] = {}
        if success_count > 0:
            updates["success_count"] = F("success_count") + success_count
        if failure_count > 0:
            updates["failure_count"] = F("failure_count") + failure_count
        if skipped_count > 0:
            updates["skipped_count"] = F("skipped_count") + skipped_count

        if updates:
            BulkAction.objects.filter(id=bulk_action_id).update(**updates)

    def update_status(self, bulk_action_id: Any, status: str) -> None:
        """Update BulkAction lifecycle status."""
        BulkAction.objects.filter(id=bulk_action_id).update(status=status)

    def get_due_scheduled_actions(self, now: datetime) -> QuerySet[BulkAction]:
        """Query actions in SCHEDULED state whose scheduled_at time has arrived."""
        return BulkAction.objects.filter(
            status=BulkActionStatus.SCHEDULED,
            scheduled_at__lte=now,
        ).order_by("scheduled_at")

    def evaluate_and_finalize_status(self, bulk_action_id: Any) -> Optional[str]:
        """
        Check if all chunks have finished. If so, update BulkAction to COMPLETED or FAILED.

        Returns:
            The final status string if finalized, else None.
        """
        action = self.get_by_id(bulk_action_id)
        if not action:
            return None

        # Check if there are any non-terminal chunks
        has_pending_chunks = BulkActionChunk.objects.filter(
            bulk_action_id=bulk_action_id,
            status__in=[ChunkStatus.PENDING, ChunkStatus.RUNNING],
        ).exists()

        if not has_pending_chunks:
            total_failed = BulkActionChunk.objects.filter(
                bulk_action_id=bulk_action_id,
                status=ChunkStatus.FAILED,
            ).count()
            total_chunks = BulkActionChunk.objects.filter(
                bulk_action_id=bulk_action_id,
            ).count()

            # If all chunks failed, mark action as FAILED, otherwise COMPLETED
            new_status = (
                BulkActionStatus.FAILED
                if total_chunks > 0 and total_failed == total_chunks
                else BulkActionStatus.COMPLETED
            )
            self.update_status(bulk_action_id, new_status)
            return new_status

        return None


class BulkActionChunkRepository:
    """Repository handling database operations for BulkActionChunk."""

    def bulk_create_chunks(self, chunks: Sequence[BulkActionChunk]) -> list[BulkActionChunk]:
        """Persist a list of chunks efficiently using bulk_create."""
        return BulkActionChunk.objects.bulk_create(chunks)

    def get_by_id(self, chunk_id: int) -> Optional[BulkActionChunk]:
        """Fetch BulkActionChunk by ID."""
        try:
            return BulkActionChunk.objects.select_related("bulk_action").get(id=chunk_id)
        except BulkActionChunk.DoesNotExist:
            return None

    def get_by_id_for_update(self, chunk_id: int) -> Optional[BulkActionChunk]:
        """Fetch BulkActionChunk by ID with row lock for idempotency checks."""
        try:
            return BulkActionChunk.objects.select_for_update().select_related("bulk_action").get(id=chunk_id)
        except BulkActionChunk.DoesNotExist:
            return None

    def get_chunks_for_action(self, bulk_action_id: Any) -> QuerySet[BulkActionChunk]:
        """Retrieve all chunks belonging to an action."""
        return BulkActionChunk.objects.filter(bulk_action_id=bulk_action_id).order_by("chunk_index")

    def update_status(
        self,
        chunk_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Update chunk status and optional error message."""
        BulkActionChunk.objects.filter(id=chunk_id).update(
            status=status,
            error_message=error_message,
        )

    def count_by_status(self, bulk_action_id: Any) -> dict[str, int]:
        """Return counts of chunks grouped by status."""
        chunks = BulkActionChunk.objects.filter(bulk_action_id=bulk_action_id).values_list("status", flat=True)
        counts = {
            "total": len(chunks),
            ChunkStatus.COMPLETED.value: 0,
            ChunkStatus.FAILED.value: 0,
            ChunkStatus.RUNNING.value: 0,
            ChunkStatus.PENDING.value: 0,
        }
        for st in chunks:
            if st in counts:
                counts[st] += 1
        return counts


class BulkActionLogRepository:
    """Repository handling database operations for BulkActionLog."""

    def bulk_create_logs(self, logs: Sequence[BulkActionLog]) -> list[BulkActionLog]:
        """Persist execution log entries using bulk_create."""
        if not logs:
            return []
        return BulkActionLog.objects.bulk_create(logs)

    def get_logs_for_action(
        self,
        bulk_action_id: Any,
        status: Optional[str] = None,
    ) -> QuerySet[BulkActionLog]:
        """Query paginated execution logs for a bulk action."""
        qs = BulkActionLog.objects.filter(bulk_action_id=bulk_action_id).order_by("id")
        if status:
            qs = qs.filter(status=status)
        return qs

    def exists_for_action_and_entity(self, bulk_action_id: Any, entity_id: str) -> bool:
        """Check if a log entry already exists for the entity in this action."""
        return BulkActionLog.objects.filter(
            bulk_action_id=bulk_action_id,
            entity_id=entity_id,
        ).exists()
