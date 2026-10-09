import logging
from typing import Optional

from django.db import transaction

from apps.bulk_actions.dtos import ChunkExecutionDTO
from apps.bulk_actions.models import BulkActionLog, ChunkStatus
from apps.bulk_actions.repositories import (
    BulkActionChunkRepository,
    BulkActionLogRepository,
    BulkActionRepository,
)
from apps.bulk_actions.strategies.factory import StrategyFactory
from apps.core.exceptions import ChunkNotFoundException, ChunkProcessingException

logger = logging.getLogger(__name__)


class ChunkExecutionService:
    """
    Service responsible for executing an individual BulkActionChunk idempotently.
    """

    def __init__(
        self,
        bulk_action_repo: Optional[BulkActionRepository] = None,
        chunk_repo: Optional[BulkActionChunkRepository] = None,
        log_repo: Optional[BulkActionLogRepository] = None,
    ) -> None:
        """Initialize dependencies via constructor injection."""
        self.bulk_action_repo = bulk_action_repo or BulkActionRepository()
        self.chunk_repo = chunk_repo or BulkActionChunkRepository()
        self.log_repo = log_repo or BulkActionLogRepository()

    def execute_chunk(self, chunk_id: int) -> ChunkExecutionDTO:
        """
        Execute an action chunk with idempotency guarantees.

        If a worker fails or restarts, re-executing a completed chunk is a safe no-op.

        Args:
            chunk_id: Primary key of the BulkActionChunk.

        Returns:
            ChunkExecutionDTO summarizing results.

        Raises:
            ChunkProcessingException: If execution fails fatally.
        """
        # Step 1: Idempotency check with row-level lock
        with transaction.atomic():
            chunk = self.chunk_repo.get_by_id_for_update(chunk_id)
            if not chunk:
                logger.warning("chunk_not_found_in_database", extra={"chunk_id": chunk_id})
                raise ChunkNotFoundException(f"Chunk {chunk_id} not found in database.")

            if chunk.status == ChunkStatus.COMPLETED:
                logger.info(
                    "chunk_already_completed_idempotent_skip",
                    extra={"chunk_id": chunk_id, "bulk_action_id": str(chunk.bulk_action_id)},
                )
                return ChunkExecutionDTO(
                    chunk_id=chunk.id,
                    bulk_action_id=str(chunk.bulk_action_id),
                    status=chunk.status,
                    success_count=0,
                    failure_count=0,
                    skipped_count=0,
                )

            # Mark chunk as RUNNING
            self.chunk_repo.update_status(chunk.id, ChunkStatus.RUNNING)

        bulk_action = chunk.bulk_action

        # Step 2: Resolve strategy from factory
        try:
            strategy = StrategyFactory.get(bulk_action.action_type)
        except Exception as exc:
            logger.error(
                "strategy_resolution_failed",
                extra={"chunk_id": chunk_id, "action_type": bulk_action.action_type, "error": str(exc)},
            )
            self.chunk_repo.update_status(chunk.id, ChunkStatus.FAILED, error_message=str(exc))
            self.bulk_action_repo.evaluate_and_finalize_status(bulk_action.id)
            raise ChunkProcessingException(str(exc)) from exc

        # Step 3: Execute strategy
        try:
            result = strategy.execute(
                bulk_action=bulk_action,
                chunk=chunk,
                entity_ids=chunk.entity_ids,
                payload=bulk_action.payload,
            )
        except Exception as exc:
            logger.exception(
                "chunk_execution_failed",
                extra={"chunk_id": chunk_id, "bulk_action_id": str(bulk_action.id), "error": str(exc)},
            )
            self.chunk_repo.update_status(chunk.id, ChunkStatus.FAILED, error_message=str(exc))
            self.bulk_action_repo.evaluate_and_finalize_status(bulk_action.id)
            raise ChunkProcessingException(f"Chunk execution failed: {exc}") from exc

        # Step 4: Atomically persist logs, increment counters using F(), and mark completed
        with transaction.atomic():
            # Database efficiency: bulk_create for execution logs
            logs_to_create = [
                BulkActionLog(
                    bulk_action_id=bulk_action.id,
                    entity_id=entry.entity_id,
                    status=entry.status,
                    error_message=entry.error_message,
                )
                for entry in result.logs
            ]
            self.log_repo.bulk_create_logs(logs_to_create)

            # Database efficiency: Django F() atomic increments
            self.bulk_action_repo.atomic_increment_counts(
                bulk_action_id=bulk_action.id,
                success_count=result.success_count,
                failure_count=result.failure_count,
                skipped_count=result.skipped_count,
            )

            # Transition chunk to COMPLETED
            self.chunk_repo.update_status(chunk.id, ChunkStatus.COMPLETED)

        # Step 5: Check if bulk action as a whole is completed
        self.bulk_action_repo.evaluate_and_finalize_status(bulk_action.id)

        logger.info(
            "chunk_completed_successfully",
            extra={
                "chunk_id": chunk.id,
                "bulk_action_id": str(bulk_action.id),
                "success_count": result.success_count,
                "failure_count": result.failure_count,
                "skipped_count": result.skipped_count,
            },
        )

        return ChunkExecutionDTO(
            chunk_id=chunk.id,
            bulk_action_id=str(bulk_action.id),
            status=ChunkStatus.COMPLETED,
            success_count=result.success_count,
            failure_count=result.failure_count,
            skipped_count=result.skipped_count,
        )
