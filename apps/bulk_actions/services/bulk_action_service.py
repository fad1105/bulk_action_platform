import logging
from typing import Any, Callable, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bulk_actions.dtos import (
    BulkActionCreateDTO,
    BulkActionStatsDTO,
)
from apps.bulk_actions.models import (
    BulkAction,
    BulkActionChunk,
    BulkActionStatus,
    ChunkStatus,
)
from apps.bulk_actions.repositories import (
    BulkActionChunkRepository,
    BulkActionLogRepository,
    BulkActionRepository,
)
from apps.bulk_actions.strategies.factory import StrategyFactory
from apps.core.exceptions import (
    BulkActionValidationException,
    RateLimitExceededException,
)
from apps.core.rate_limiter import RedisRateLimiter
from apps.entities.registry import EntityRegistry

logger = logging.getLogger(__name__)


def _default_chunk_task_dispatcher(chunk_id: int) -> None:
    """Default Celery task dispatcher for chunks."""
    from apps.bulk_actions.tasks import process_bulk_action_chunk

    process_bulk_action_chunk.delay(chunk_id)


class BulkActionService:
    """
    Main orchestration service for bulk actions.

    Handles creation, validation, rate limiting, chunking, and scheduling.
    """

    def __init__(
        self,
        bulk_action_repo: Optional[BulkActionRepository] = None,
        chunk_repo: Optional[BulkActionChunkRepository] = None,
        log_repo: Optional[BulkActionLogRepository] = None,
        rate_limiter: Optional[RedisRateLimiter] = None,
        task_dispatcher: Optional[Callable[[int], None]] = None,
        default_chunk_size: Optional[int] = None,
    ) -> None:
        """Initialize service dependencies via constructor injection."""
        self.bulk_action_repo = bulk_action_repo or BulkActionRepository()
        self.chunk_repo = chunk_repo or BulkActionChunkRepository()
        self.log_repo = log_repo or BulkActionLogRepository()
        self.rate_limiter = rate_limiter or RedisRateLimiter()
        self.task_dispatcher = task_dispatcher or _default_chunk_task_dispatcher
        self.default_chunk_size = default_chunk_size or getattr(settings, "DEFAULT_CHUNK_SIZE", 500)

    def create_bulk_action(self, dto: BulkActionCreateDTO) -> BulkAction:
        """
        Create and initialize a bulk action, chunking the target records.

        Performs:
        1. Entity registration verification.
        2. Action strategy resolution and payload validation.
        3. Entity resolution (target ID collection).
        4. Rate limiting check (10,000 entities/minute per account_id).
        5. Workload chunking into 500-item chunks.
        6. Immediate dispatch or schedule for future execution.

        Args:
            dto: BulkActionCreateDTO with validated creation parameters.

        Returns:
            Created BulkAction model instance.

        Raises:
            RateLimitExceededException: If account exceeds throughput limits.
            BulkActionValidationException: If validation fails.
        """
        # Step 1: Validate entity type
        if not EntityRegistry.is_registered(dto.entity_type):
            raise BulkActionValidationException(
                f"Entity '{dto.entity_type}' is not supported. "
                f"Supported entities: {EntityRegistry.get_supported_entities()}"
            )

        # Step 2: Validate strategy and payload
        strategy = StrategyFactory.get(dto.action_type)
        strategy.validate_payload(dto.entity_type, dto.payload)

        # Step 3: Resolve entity IDs
        entity_ids = self._resolve_entity_ids(dto.entity_type, dto.payload)
        total_count = len(entity_ids)

        if total_count == 0:
            raise BulkActionValidationException("No entities found to process for this bulk action.")

        # Step 4: Rate Limiting & Scheduling check
        is_scheduled = dto.scheduled_at is not None

        if not is_scheduled:
            allowed, current_usage, limit = self.rate_limiter.check_and_consume(
                account_id=dto.account_id,
                count=total_count,
            )
            if not allowed:
                raise RateLimitExceededException(
                    account_id=dto.account_id,
                    limit=limit,
                    current_usage=current_usage,
                    requested=total_count,
                )

        initial_status = BulkActionStatus.SCHEDULED if is_scheduled else BulkActionStatus.PENDING

        chunk_size = dto.chunk_size or self.default_chunk_size
        chunk_size = max(1, chunk_size)

        # Step 5: Chunking & Atomic Persistence
        with transaction.atomic():
            bulk_action = self.bulk_action_repo.create(
                account_id=dto.account_id,
                entity_type=dto.entity_type,
                action_type=dto.action_type,
                payload=dto.payload,
                total_count=total_count,
                status=initial_status,
                scheduled_at=dto.scheduled_at,
            )

            # Split entity IDs into chunks of size chunk_size (e.g. 500 each)
            chunks_to_create: list[BulkActionChunk] = []
            for i in range(0, total_count, chunk_size):
                chunk_slice = entity_ids[i : i + chunk_size]
                chunk_index = i // chunk_size
                chunk = BulkActionChunk(
                    bulk_action=bulk_action,
                    chunk_index=chunk_index,
                    start_index=i,
                    end_index=i + len(chunk_slice) - 1,
                    entity_ids=chunk_slice,
                    status=ChunkStatus.PENDING,
                )
                chunks_to_create.append(chunk)

            created_chunks = self.chunk_repo.bulk_create_chunks(chunks_to_create)

        logger.info(
            "bulk_action_created",
            extra={
                "bulk_action_id": str(bulk_action.id),
                "account_id": dto.account_id,
                "entity_type": dto.entity_type,
                "total_count": total_count,
                "total_chunks": len(created_chunks),
                "status": initial_status,
            },
        )

        # Step 6: Dispatch chunks if immediate
        if not is_scheduled:
            self.bulk_action_repo.update_status(bulk_action.id, BulkActionStatus.RUNNING)
            bulk_action.status = BulkActionStatus.RUNNING
            for chunk in created_chunks:
                self.task_dispatcher(chunk.id)

        return bulk_action

    def _resolve_entity_ids(self, entity_type: str, payload: dict[str, Any]) -> list[Any]:
        """
        Extract entity IDs either explicitly provided in payload or resolved via repository.

        Args:
            entity_type: Entity type name.
            payload: Action payload.

        Returns:
            List of entity primary keys.
        """
        repository = EntityRegistry.get_repository(entity_type)

        if "entity_ids" in payload and isinstance(payload["entity_ids"], list):
            return payload["entity_ids"]

        if "filters" in payload and isinstance(payload["filters"], dict):
            return repository.filter_ids(**payload["filters"])

        # Fallback: all entity IDs
        return repository.get_all_ids()

    def trigger_scheduled_actions(self) -> list[str]:
        """
        Trigger actions whose scheduled_at time has arrived.

        Invoked periodically by Celery Beat.

        Returns:
            List of triggered BulkAction IDs.
        """
        now = timezone.now()
        due_actions = self.bulk_action_repo.get_due_scheduled_actions(now)
        triggered_ids: list[str] = []

        for action in due_actions:
            # Check rate limit before queuing scheduled tasks
            allowed, current_usage, limit = self.rate_limiter.check_and_consume(
                account_id=action.account_id,
                count=action.total_count,
            )
            if not allowed:
                logger.warning(
                    "scheduled_action_rate_limited",
                    extra={
                        "bulk_action_id": str(action.id),
                        "account_id": action.account_id,
                        "limit": limit,
                        "current_usage": current_usage,
                    },
                )
                # Postpone or leave scheduled for next cycle
                continue

            # Update status to RUNNING
            self.bulk_action_repo.update_status(action.id, BulkActionStatus.RUNNING)

            chunks = self.chunk_repo.get_chunks_for_action(action.id)
            for chunk in chunks:
                if chunk.status == ChunkStatus.PENDING:
                    self.task_dispatcher(chunk.id)

            triggered_ids.append(str(action.id))
            logger.info("scheduled_action_triggered", extra={"bulk_action_id": str(action.id)})

        return triggered_ids

    def get_action_stats(self, bulk_action_id: Any) -> Optional[BulkActionStatsDTO]:
        """
        Calculate statistics and progress for a BulkAction.

        Args:
            bulk_action_id: ID of the BulkAction.

        Returns:
            BulkActionStatsDTO or None if not found.
        """
        action = self.bulk_action_repo.get_by_id(bulk_action_id)
        if not action:
            return None

        chunk_counts = self.chunk_repo.count_by_status(bulk_action_id)

        return BulkActionStatsDTO(
            id=str(action.id),
            status=action.status,
            total_count=action.total_count,
            success_count=action.success_count,
            failure_count=action.failure_count,
            skipped_count=action.skipped_count,
            progress_percentage=action.progress_percentage,
            chunks_total=chunk_counts.get("total", 0),
            chunks_completed=chunk_counts.get(ChunkStatus.COMPLETED.value, 0),
            chunks_failed=chunk_counts.get(ChunkStatus.FAILED.value, 0),
            chunks_running=chunk_counts.get(ChunkStatus.RUNNING.value, 0),
            chunks_pending=chunk_counts.get(ChunkStatus.PENDING.value, 0),
        )

    def get_action_logs(self, bulk_action_id: Any, status: Optional[str] = None):
        """Return QuerySet of logs for a bulk action."""
        return self.log_repo.get_logs_for_action(bulk_action_id, status=status)
