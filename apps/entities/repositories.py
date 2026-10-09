from abc import ABC, abstractmethod
from typing import Any, Generic, Sequence, TypeVar

from django.db.models import Model, QuerySet

from apps.entities.models import Contact, Lead

T = TypeVar("T", bound=Model)


class BaseEntityRepository(ABC, Generic[T]):
    """
    Abstract base repository defining database access operations for entities.
    """

    @abstractmethod
    def get_model_class(self) -> type[T]:
        """Return the Django model class handled by this repository."""
        pass

    def get_by_ids(self, ids: Sequence[Any]) -> QuerySet[T]:
        """
        Fetch entities in a single query using id__in, preventing N+1 queries.

        Args:
            ids: List of entity primary keys.

        Returns:
            QuerySet of matching entity instances.
        """
        return self.get_model_class().objects.filter(id__in=ids)

    def get_all_ids(self) -> list[Any]:
        """
        Retrieve all entity IDs ordered by ID.

        Returns:
            List of primary keys.
        """
        return list(self.get_model_class().objects.order_by("id").values_list("id", flat=True))

    def filter_ids(self, **filters: Any) -> list[Any]:
        """
        Retrieve entity IDs matching query filters.

        Args:
            **filters: Django ORM filter expressions.

        Returns:
            List of matching primary keys.
        """
        return list(self.get_model_class().objects.filter(**filters).order_by("id").values_list("id", flat=True))

    def bulk_update(self, entities: Sequence[T], fields: Sequence[str]) -> int:
        """
        Efficiently update multiple entity instances using bulk_update.

        Args:
            entities: Sequence of model instances with modified fields.
            fields: List of field names to update in the database.

        Returns:
            Number of rows updated.
        """
        if not entities or not fields:
            return 0
        return self.get_model_class().objects.bulk_update(entities, fields)

    def get_valid_field_names(self) -> set[str]:
        """
        Return the set of writable field names defined on the model.

        Returns:
            Set of field names excluding auto/primary keys.
        """
        model = self.get_model_class()
        return {
            field.name
            for field in model._meta.get_fields()
            if hasattr(field, "name")
            and not getattr(field, "primary_key", False)
            and not getattr(field, "auto_created", False)
            and not getattr(field, "is_relation", False)
        }


class ContactRepository(BaseEntityRepository[Contact]):
    """Repository for Contact entity database operations."""

    def get_model_class(self) -> type[Contact]:
        return Contact


class LeadRepository(BaseEntityRepository[Lead]):
    """Repository for Lead entity database operations."""

    def get_model_class(self) -> type[Lead]:
        return Lead
