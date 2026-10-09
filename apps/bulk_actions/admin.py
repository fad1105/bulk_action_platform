from django import forms
from django.contrib import admin, messages

from apps.bulk_actions.dtos import BulkActionCreateDTO
from apps.bulk_actions.models import BulkAction, BulkActionChunk, BulkActionLog
from apps.bulk_actions.services.bulk_action_service import BulkActionService
from apps.entities.registry import EntityRegistry


class BulkActionAdminForm(forms.ModelForm):
    """Admin form for creating and configuring a BulkAction."""

    entity_type = forms.ChoiceField(
        choices=[(k, k.capitalize()) for k in EntityRegistry.get_supported_entities()],
        help_text="Select target entity model.",
    )
    action_type = forms.ChoiceField(
        choices=[("bulk_update", "Bulk Update")],
        help_text="Select strategy to execute.",
    )
    payload = forms.JSONField(
        initial={"fields": {"status": "inactive"}},
        help_text='JSON configuration. e.g. {"fields": {"status": "inactive"}} or {"entity_ids": [1, 2], "fields": {"status": "active"}}',
    )
    chunk_size = forms.IntegerField(
        initial=500,
        min_value=1,
        required=False,
        help_text="Number of records per chunk (Celery task). Default: 500.",
    )

    class Meta:
        model = BulkAction
        fields = [
            "account_id",
            "entity_type",
            "action_type",
            "payload",
            "chunk_size",
            "scheduled_at",
        ]


class BulkActionChunkInline(admin.TabularInline):
    """Inline view of chunks associated with a bulk action."""

    model = BulkActionChunk
    extra = 0
    can_delete = False
    readonly_fields = (
        "chunk_index",
        "start_index",
        "end_index",
        "status",
        "error_message",
        "created_at",
    )
    fields = (
        "chunk_index",
        "start_index",
        "end_index",
        "status",
        "error_message",
        "created_at",
    )


@admin.register(BulkAction)
class BulkActionAdmin(admin.ModelAdmin):
    """Admin interface for BulkAction lifecycle management."""

    form = BulkActionAdminForm
    list_display = (
        "id",
        "account_id",
        "entity_type",
        "action_type",
        "status",
        "progress_display",
        "total_count",
        "success_count",
        "failure_count",
        "skipped_count",
        "scheduled_at",
        "created_at",
    )
    list_filter = ("status", "entity_type", "action_type", "created_at")
    search_fields = ("id", "account_id")
    ordering = ("-created_at",)
    inlines = [BulkActionChunkInline]
    actions = ["trigger_scheduled_now"]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            # Editing existing action: protect operational fields
            return (
                "id",
                "account_id",
                "entity_type",
                "action_type",
                "payload",
                "status",
                "progress_display",
                "total_count",
                "success_count",
                "failure_count",
                "skipped_count",
                "scheduled_at",
                "created_at",
                "updated_at",
            )
        return (
            "progress_display",
            "total_count",
            "success_count",
            "failure_count",
            "skipped_count",
            "created_at",
            "updated_at",
        )

    def save_model(self, request, obj, form, change) -> None:
        """When creating from Admin, orchestrate via BulkActionService."""
        if not change:
            service = BulkActionService()
            chunk_size = form.cleaned_data.get("chunk_size") or 500
            dto = BulkActionCreateDTO(
                account_id=obj.account_id or "admin",
                entity_type=obj.entity_type,
                action_type=obj.action_type,
                payload=obj.payload,
                scheduled_at=obj.scheduled_at,
                chunk_size=chunk_size,
            )
            try:
                created_action = service.create_bulk_action(dto)
                obj.id = created_action.id
                obj.status = created_action.status
                obj.total_count = created_action.total_count
                self.message_user(
                    request,
                    f"Successfully created Bulk Action {created_action.id} with {created_action.chunks.count()} "
                    f"chunk(s) for {created_action.total_count} records.",
                    level=messages.SUCCESS,
                )
            except Exception as exc:
                self.message_user(
                    request,
                    f"Failed to create Bulk Action: {exc}",
                    level=messages.ERROR,
                )
                raise
        else:
            super().save_model(request, obj, form, change)

    @admin.display(description="Progress")
    def progress_display(self, obj: BulkAction) -> str:
        return f"{obj.progress_percentage}%"

    @admin.action(description="Trigger selected actions now")
    def trigger_scheduled_now(self, request, queryset) -> None:
        """Manually trigger selected pending or scheduled bulk actions."""
        service = BulkActionService()
        triggered = service.trigger_scheduled_actions()
        self.message_user(
            request,
            f"Triggered {len(triggered)} scheduled action(s).",
            level=messages.SUCCESS,
        )


@admin.register(BulkActionChunk)
class BulkActionChunkAdmin(admin.ModelAdmin):
    """Admin interface for individual BulkActionChunk records."""

    list_display = (
        "id",
        "bulk_action",
        "chunk_index",
        "start_index",
        "end_index",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("bulk_action__id", "bulk_action__account_id")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(BulkActionLog)
class BulkActionLogAdmin(admin.ModelAdmin):
    """Admin interface for per-entity BulkActionLog records."""

    list_display = (
        "id",
        "bulk_action",
        "entity_id",
        "status",
        "error_message",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("bulk_action__id", "entity_id", "error_message")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)
