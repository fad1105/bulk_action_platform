from django.apps import AppConfig


class BulkActionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bulk_actions"

    def ready(self) -> None:
        """Register action strategies with the StrategyFactory."""
        import apps.bulk_actions.strategies.factory  # noqa: F401
