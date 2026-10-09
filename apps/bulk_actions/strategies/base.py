from abc import ABC, abstractmethod
from typing import Any

from apps.bulk_actions.dtos import StrategyResultDTO
from apps.bulk_actions.models import BulkAction, BulkActionChunk


class ActionStrategy(ABC):
    """
    Abstract Base Class for bulk action execution strategies.

    Follows the Modular Strategy Pattern and enables entity-agnostic bulk operations.
    """

    @abstractmethod
    def get_action_name(self) -> str:
        """Return the unique name for this action strategy (e.g., 'bulk_update')."""
        pass

    @abstractmethod
    def validate_payload(self, entity_type: str, payload: dict[str, Any]) -> None:
        """
        Validate that the payload is valid for the given entity type before scheduling.

        Args:
            entity_type: Target entity identifier.
            payload: Parameters provided in the bulk action request.

        Raises:
            BulkActionValidationException: If payload schema or fields are invalid.
        """
        pass

    @abstractmethod
    def execute(
        self,
        bulk_action: BulkAction,
        chunk: BulkActionChunk,
        entity_ids: list[Any],
        payload: dict[str, Any],
    ) -> StrategyResultDTO:
        """
        Execute strategy on the given chunk of entity IDs.

        Args:
            bulk_action: Parent BulkAction model.
            chunk: BulkActionChunk model being executed.
            entity_ids: List of entity IDs assigned to this chunk.
            payload: Action payload containing parameters/fields.

        Returns:
            StrategyResultDTO summarizing the chunk results and entity logs.
        """
        pass
