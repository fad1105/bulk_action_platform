from rest_framework import serializers

from apps.bulk_actions.dtos import BulkActionCreateDTO, BulkActionStatsDTO
from apps.bulk_actions.models import BulkAction, BulkActionChunk, BulkActionLog


class BulkActionCreateSerializer(serializers.Serializer):
    """Serializer validating incoming bulk action creation requests."""

    account_id = serializers.CharField(max_length=100, required=True)
    entity_type = serializers.CharField(max_length=50, required=True)
    action_type = serializers.CharField(max_length=50, required=True)
    payload = serializers.DictField(required=True)
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    chunk_size = serializers.IntegerField(required=False, min_value=1, default=500)

    def to_dto(self) -> BulkActionCreateDTO:
        """Convert validated serializer data to domain DTO."""
        data = self.validated_data
        return BulkActionCreateDTO(
            account_id=data["account_id"],
            entity_type=data["entity_type"],
            action_type=data["action_type"],
            payload=data["payload"],
            scheduled_at=data.get("scheduled_at"),
            chunk_size=data.get("chunk_size"),
        )


class BulkActionChunkSerializer(serializers.ModelSerializer):
    """Serializer for BulkActionChunk details."""

    class Meta:
        model = BulkActionChunk
        fields = [
            "id",
            "chunk_index",
            "start_index",
            "end_index",
            "status",
            "error_message",
            "created_at",
            "updated_at",
        ]


class BulkActionLogSerializer(serializers.ModelSerializer):
    """Serializer for BulkActionLog entries."""

    class Meta:
        model = BulkActionLog
        fields = [
            "id",
            "bulk_action_id",
            "entity_id",
            "status",
            "error_message",
            "created_at",
        ]


class BulkActionDetailSerializer(serializers.ModelSerializer):
    """Serializer representing BulkAction status and progress."""

    progress_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = BulkAction
        fields = [
            "id",
            "account_id",
            "entity_type",
            "action_type",
            "payload",
            "status",
            "total_count",
            "success_count",
            "failure_count",
            "skipped_count",
            "progress_percentage",
            "scheduled_at",
            "created_at",
            "updated_at",
        ]


class BulkActionStatsSerializer(serializers.Serializer):
    """Serializer for bulk action statistical summary."""

    id = serializers.CharField()
    status = serializers.CharField()
    total_count = serializers.IntegerField()
    success_count = serializers.IntegerField()
    failure_count = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    progress_percentage = serializers.FloatField()
    chunks = serializers.SerializerMethodField()

    def get_chunks(self, obj: BulkActionStatsDTO) -> dict[str, int]:
        return {
            "total": obj.chunks_total,
            "completed": obj.chunks_completed,
            "failed": obj.chunks_failed,
            "running": obj.chunks_running,
            "pending": obj.chunks_pending,
        }
