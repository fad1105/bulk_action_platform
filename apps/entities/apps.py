from django.apps import AppConfig


class EntitiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.entities"

    def ready(self) -> None:
        """Register entity models with the EntityRegistry."""
        import apps.entities.registry  # noqa: F401
