import logging

from celery import shared_task

from apps.bulk_actions.services.bulk_action_service import BulkActionService
from apps.bulk_actions.services.chunk_execution_service import ChunkExecutionService
from apps.core.exceptions import ChunkNotFoundException

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
    reject_on_worker_lost=True,
    name="apps.bulk_actions.tasks.process_bulk_action_chunk",
)
def process_bulk_action_chunk(self, chunk_id: int) -> dict:
    """
    Celery task to execute a single BulkActionChunk.

    Guaranteed idempotent: if the task retries or is re-run, already completed
    work will safely be skipped without duplicate counts or updates.
    """
    logger.info("processing_chunk_task_started", extra={"chunk_id": chunk_id, "task_id": self.request.id})
    service = ChunkExecutionService()
    try:
        result = service.execute_chunk(chunk_id)
        return {
            "chunk_id": result.chunk_id,
            "status": result.status,
            "success_count": result.success_count,
            "failure_count": result.failure_count,
            "skipped_count": result.skipped_count,
        }
    except ChunkNotFoundException as exc:
        logger.warning(
            "orphaned_chunk_task_discarded",
            extra={"chunk_id": chunk_id, "error": str(exc)},
        )
        return {"chunk_id": chunk_id, "status": "DISCARDED", "reason": str(exc)}
    except Exception as exc:
        logger.exception("processing_chunk_task_exception", extra={"chunk_id": chunk_id, "error": str(exc)})
        # Retry with exponential backoff on transient errors if applicable
        raise self.retry(exc=exc)


@shared_task(name="apps.bulk_actions.tasks.process_scheduled_actions")
def process_scheduled_actions() -> list[str]:
    """
    Periodic Celery Beat task to trigger actions whose scheduled_at timestamp has arrived.
    """
    logger.debug("checking_scheduled_bulk_actions")
    service = BulkActionService()
    triggered_ids = service.trigger_scheduled_actions()
    if triggered_ids:
        logger.info("scheduled_actions_triggered_by_beat", extra={"action_ids": triggered_ids})
    return triggered_ids
