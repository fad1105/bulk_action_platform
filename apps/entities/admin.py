from django.contrib import admin, messages

from apps.bulk_actions.dtos import BulkActionCreateDTO
from apps.bulk_actions.services.bulk_action_service import BulkActionService
from apps.entities.models import Contact, Lead


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    """Admin interface for Contact entity."""

    list_display = ("id", "name", "email", "age", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "email")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    actions = ["action_bulk_mark_active", "action_bulk_mark_inactive", "action_bulk_mark_archived"]

    def _trigger_bulk_status_update(self, request, queryset, new_status: str) -> None:
        selected_ids = list(queryset.values_list("id", flat=True))
        if not selected_ids:
            return

        service = BulkActionService()
        dto = BulkActionCreateDTO(
            account_id=f"admin_{request.user.username}",
            entity_type="contact",
            action_type="bulk_update",
            payload={"entity_ids": selected_ids, "fields": {"status": new_status}},
            chunk_size=500,
        )
        action = service.create_bulk_action(dto)
        self.message_user(
            request,
            f"Created Bulk Action {action.id} to update {len(selected_ids)} contacts to '{new_status}' across "
            f"{action.chunks.count()} Celery chunk(s).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Bulk update selected to 'active'")
    def action_bulk_mark_active(self, request, queryset) -> None:
        self._trigger_bulk_status_update(request, queryset, "active")

    @admin.action(description="Bulk update selected to 'inactive'")
    def action_bulk_mark_inactive(self, request, queryset) -> None:
        self._trigger_bulk_status_update(request, queryset, "inactive")

    @admin.action(description="Bulk update selected to 'archived'")
    def action_bulk_mark_archived(self, request, queryset) -> None:
        self._trigger_bulk_status_update(request, queryset, "archived")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    """Admin interface for Lead entity."""

    list_display = ("id", "name", "email", "company", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "email", "company")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    actions = ["action_bulk_mark_qualified", "action_bulk_mark_closed"]

    def _trigger_bulk_lead_update(self, request, queryset, new_status: str) -> None:
        selected_ids = list(queryset.values_list("id", flat=True))
        if not selected_ids:
            return

        service = BulkActionService()
        dto = BulkActionCreateDTO(
            account_id=f"admin_{request.user.username}",
            entity_type="lead",
            action_type="bulk_update",
            payload={"entity_ids": selected_ids, "fields": {"status": new_status}},
            chunk_size=500,
        )
        action = service.create_bulk_action(dto)
        self.message_user(
            request,
            f"Created Bulk Action {action.id} to update {len(selected_ids)} leads to '{new_status}' across "
            f"{action.chunks.count()} Celery chunk(s).",
            level=messages.SUCCESS,
        )

    @admin.action(description="Bulk update selected to 'qualified'")
    def action_bulk_mark_qualified(self, request, queryset) -> None:
        self._trigger_bulk_lead_update(request, queryset, "qualified")

    @admin.action(description="Bulk update selected to 'closed'")
    def action_bulk_mark_closed(self, request, queryset) -> None:
        self._trigger_bulk_lead_update(request, queryset, "closed")
