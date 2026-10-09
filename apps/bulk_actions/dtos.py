from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class BulkActionCreateDTO:
    """DTO carrying validated parameters to create a BulkAction."""

    account_id: str
    entity_type: str
    action_type: str
    payload: dict[str, Any]
    scheduled_at: Optional[datetime] = None
    chunk_size: Optional[int] = None


@dataclass(frozen=True)
class EntityLogEntryDTO:
    """DTO representing the result log for an individual entity."""

    entity_id: str
    status: str
    error_message: Optional[str] = None


@dataclass(frozen=True)
class StrategyResultDTO:
    """DTO returning the outcome of an action strategy execution."""

    success_count: int
    failure_count: int
    skipped_count: int
    logs: list[EntityLogEntryDTO] = field(default_factory=list)


@dataclass(frozen=True)
class ChunkExecutionDTO:
    """DTO summarizing the result of executing a single chunk."""

    chunk_id: int
    bulk_action_id: str
    status: str
    success_count: int
    failure_count: int
    skipped_count: int
    error_message: Optional[str] = None


@dataclass(frozen=True)
class BulkActionStatsDTO:
    """DTO reporting current counts and progress for an action."""

    id: str
    status: str
    total_count: int
    success_count: int
    failure_count: int
    skipped_count: int
    progress_percentage: float
    chunks_total: int
    chunks_completed: int
    chunks_failed: int
    chunks_running: int
    chunks_pending: int
