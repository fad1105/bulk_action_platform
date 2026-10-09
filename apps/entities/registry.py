from dataclasses import dataclass
from typing import Optional, Type

from django.db.models import Model

from apps.core.exceptions import UnsupportedEntityTypeException
from apps.entities.repositories import BaseEntityRepository, ContactRepository, LeadRepository


@dataclass(frozen=True)
class EntityMetadata:
    """Metadata and repository configuration for an entity type."""

    entity_type: str
    model_class: Type[Model]
    repository: BaseEntityRepository
    email_field: Optional[str] = "email"
    identifier_field: str = "id"


class EntityRegistry:
    """
    Registry for entities supported by the Bulk Action Platform.

    Makes the system entity-agnostic by decoupling action execution from specific models.
    """

    _registry: dict[str, EntityMetadata] = {}

    @classmethod
    def register(
        cls,
        entity_type: str,
        repository: BaseEntityRepository,
        email_field: Optional[str] = "email",
        identifier_field: str = "id",
    ) -> None:
        """
        Register a new entity type.

        Args:
            entity_type: Unique identifier string for entity (e.g. 'contact').
            repository: Repository instance handling DB access.
            email_field: Name of the email or deduplication key field.
            identifier_field: Name of the primary key field.
        """
        normalized_type = entity_type.lower()
        metadata = EntityMetadata(
            entity_type=normalized_type,
            model_class=repository.get_model_class(),
            repository=repository,
            email_field=email_field,
            identifier_field=identifier_field,
        )
        cls._registry[normalized_type] = metadata

    @classmethod
    def get(cls, entity_type: str) -> EntityMetadata:
        """
        Retrieve metadata for an entity type.

        Args:
            entity_type: The entity type name.

        Returns:
            EntityMetadata for the entity.

        Raises:
            UnsupportedEntityTypeException: If the entity is not registered.
        """
        normalized_type = entity_type.lower()
        if normalized_type not in cls._registry:
            raise UnsupportedEntityTypeException(
                f"Entity type '{entity_type}' is not supported. Supported types: {list(cls._registry.keys())}"
            )
        return cls._registry[normalized_type]

    @classmethod
    def get_repository(cls, entity_type: str) -> BaseEntityRepository:
        """Return the repository for the given entity type."""
        return cls.get(entity_type).repository

    @classmethod
    def is_registered(cls, entity_type: str) -> bool:
        """Check if an entity type is registered."""
        return entity_type.lower() in cls._registry

    @classmethod
    def get_supported_entities(cls) -> list[str]:
        """Return list of all registered entity names."""
        return list(cls._registry.keys())


# Register core entities
EntityRegistry.register("contact", ContactRepository(), email_field="email")
EntityRegistry.register("lead", LeadRepository(), email_field="email")
