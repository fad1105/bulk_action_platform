import uuid

from django.db import models


class BulkActionStatus(models.TextChoices):
    """Lifecycle statuses for a BulkAction."""

    PENDING = "PENDING", "Pending"
    SCHEDULED = "SCHEDULED", "Scheduled"
    RUNNING = "RUNNING", "Running"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class ChunkStatus(models.TextChoices):
    """Lifecycle statuses for a BulkActionChunk."""

    PENDING = "PENDING", "Pending"
    RUNNING = "RUNNING", "Running"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"


class LogStatus(models.TextChoices):
    """Result statuses for individual entity execution logs."""

    SUCCESS = "SUCCESS", "Success"
    ERROR = "ERROR", "Error"
    SKIPPED = "SKIPPED", "Skipped"


class BulkAction(models.Model):
    """
    Main entity tracking bulk operation lifecycle, progress, and configuration.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account_id = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=50, db_index=True)
    action_type = models.CharField(max_length=50)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=BulkActionStatus.choices,
        default=BulkActionStatus.PENDING,
        db_index=True,
    )
    total_count = models.IntegerField(default=0)
    success_count = models.IntegerField(default=0)
    failure_count = models.IntegerField(default=0)
    skipped_count = models.IntegerField(default=0)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bulk_actions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account_id", "status"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self) -> str:
        return f"BulkAction {self.id} ({self.entity_type}:{self.action_type} - {self.status})"

    @property
    def progress_percentage(self) -> float:
        """Calculate overall progress percentage."""
        if self.total_count == 0:
            return 100.0 if self.status == BulkActionStatus.COMPLETED else 0.0
        processed = self.success_count + self.failure_count + self.skipped_count
        return round(min(100.0, (processed / self.total_count) * 100), 2)


class BulkActionChunk(models.Model):
    """
    Represents an independently executable batch of records within a bulk action.
    """

    id = models.BigAutoField(primary_key=True)
    bulk_action = models.ForeignKey(
        BulkAction,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    chunk_index = models.IntegerField(default=0)
    start_index = models.IntegerField()
    end_index = models.IntegerField()
    entity_ids = models.JSONField(default=list)
    status = models.CharField(
        max_length=20,
        choices=ChunkStatus.choices,
        default=ChunkStatus.PENDING,
        db_index=True,
    )
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bulk_action_chunks"
        ordering = ["bulk_action", "chunk_index"]
        indexes = [
            models.Index(fields=["bulk_action", "status"]),
        ]

    def __str__(self) -> str:
        return f"Chunk {self.chunk_index} for Action {self.bulk_action_id} ({self.status})"


class BulkActionLog(models.Model):
    """
    Per-entity execution result log within a bulk action.
    """

    id = models.BigAutoField(primary_key=True)
    bulk_action = models.ForeignKey(
        BulkAction,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    entity_id = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=LogStatus.choices,
        db_index=True,
    )
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bulk_action_logs"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["bulk_action", "status"]),
            models.Index(fields=["bulk_action", "entity_id"]),
        ]

    def __str__(self) -> str:
        return f"Log {self.id} for Action {self.bulk_action_id}: {self.entity_id} -> {self.status}"
