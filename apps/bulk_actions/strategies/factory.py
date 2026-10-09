from typing import Dict

from apps.bulk_actions.strategies.base import ActionStrategy
from apps.bulk_actions.strategies.bulk_update import BulkUpdateStrategy
from apps.core.exceptions import UnsupportedActionTypeException


class StrategyFactory:
    """
    Factory for resolving action strategies based on action_type.
    """

    _strategies: Dict[str, ActionStrategy] = {}

    @classmethod
    def register(cls, action_name: str, strategy: ActionStrategy) -> None:
        """
        Register a new action strategy.

        Args:
            action_name: Action type string (e.g., 'bulk_update').
            strategy: ActionStrategy instance.
        """
        cls._strategies[action_name.lower()] = strategy

    @classmethod
    def get(cls, action_name: str) -> ActionStrategy:
        """
        Retrieve registered strategy for action_name.

        Args:
            action_name: Action type identifier.

        Returns:
            ActionStrategy implementation.

        Raises:
            UnsupportedActionTypeException: If action is not registered.
        """
        key = action_name.lower()
        if key not in cls._strategies:
            raise UnsupportedActionTypeException(
                f"Action type '{action_name}' is not supported. Supported actions: {list(cls._strategies.keys())}"
            )
        return cls._strategies[key]

    @classmethod
    def get_supported_actions(cls) -> list[str]:
        """Return list of all registered action names."""
        return list(cls._strategies.keys())


# Register core strategies
StrategyFactory.register("bulk_update", BulkUpdateStrategy())
