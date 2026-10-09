import logging
from typing import Any, Optional

import redis
from django.conf import settings

from apps.bulk_actions.dtos import EntityLogEntryDTO, StrategyResultDTO
from apps.bulk_actions.models import BulkAction, BulkActionChunk, LogStatus
from apps.bulk_actions.strategies.base import ActionStrategy
from apps.core.exceptions import BulkActionValidationException
from apps.entities.registry import EntityRegistry

logger = logging.getLogger(__name__)


class BulkUpdateStrategy(ActionStrategy):
    """
    Strategy for executing bulk updates on any registered entity model.

    Updates arbitrary fields using repository bulk_update() and performs
    distributed deduplication on email field using Redis sets.
    """

    def __init__(self, redis_client: Optional[redis.Redis] = None) -> None:
        """
        Initialize strategy with Redis client dependency.

        Args:
            redis_client: Optional Redis client for email deduplication.
        """
        self.redis_client = redis_client or redis.Redis.from_url(
            getattr(settings, "REDIS_URL", "redis://localhost:6379/2"),
            decode_responses=True,
        )

    def get_action_name(self) -> str:
        return "bulk_update"

    def validate_payload(self, entity_type: str, payload: dict[str, Any]) -> None:
        """
        Validate that payload contains 'fields' mapping and that fields exist on entity.

        Args:
            entity_type: Target entity identifier.
            payload: Parameters provided in the bulk action request.

        Raises:
            BulkActionValidationException: If fields are invalid.
        """
        if "fields" not in payload or not isinstance(payload["fields"], dict):
            raise BulkActionValidationException(
                "Payload for 'bulk_update' must contain a 'fields' dictionary of field:value pairs."
            )

        fields_to_update = payload["fields"]
        if not fields_to_update:
            raise BulkActionValidationException("Payload 'fields' cannot be empty.")

        metadata = EntityRegistry.get(entity_type)
        valid_fields = metadata.repository.get_valid_field_names()

        invalid_fields = set(fields_to_update.keys()) - valid_fields
        if invalid_fields:
            raise BulkActionValidationException(
                f"Invalid fields {list(invalid_fields)} for entity '{entity_type}'. "
                f"Allowed writable fields: {sorted(list(valid_fields))}"
            )

    def execute(
        self,
        bulk_action: BulkAction,
        chunk: BulkActionChunk,
        entity_ids: list[Any],
        payload: dict[str, Any],
    ) -> StrategyResultDTO:
        """
        Execute bulk updates for the given chunk of entity IDs.

        - Uses id__in to fetch entities in a single query (no N+1).
        - Skips duplicate entities by email across the bulk action using Redis sets.
        - Updates entities using repository.bulk_update().
        - Logs outcomes (SUCCESS, SKIPPED, ERROR).

        Args:
            bulk_action: Parent BulkAction instance.
            chunk: Current chunk being executed.
            entity_ids: Entity IDs assigned to this chunk.
            payload: Payload containing fields dictionary.

        Returns:
            StrategyResultDTO summarizing the chunk results.
        """
        metadata = EntityRegistry.get(bulk_action.entity_type)
        repository = metadata.repository
        email_field = metadata.email_field
        fields_to_update = payload.get("fields", {})

        # Fetch entities in batch using id__in (No N+1 queries)
        entities = list(repository.get_by_ids(entity_ids))
        entity_map = {entity.id: entity for entity in entities}

        logs: list[EntityLogEntryDTO] = []
        success_count = 0
        failure_count = 0
        skipped_count = 0

        entities_to_persist: dict[Any, Any] = {}
        dedup_redis_key = f"bulk_action:{bulk_action.id}:seen_emails"

        # Iterate over entity_ids in sequence to handle input order and duplicates
        for entity_id in entity_ids:
            entity = entity_map.get(entity_id)
            if entity is None:
                # Fallback to string matching for UUID/int compatibility
                for eid, candidate in entity_map.items():
                    if str(eid) == str(entity_id):
                        entity = candidate
                        break

            if entity is None:
                logs.append(
                    EntityLogEntryDTO(
                        entity_id=str(entity_id),
                        status=LogStatus.ERROR,
                        error_message=f"Entity with ID {entity_id} not found in database.",
                    )
                )
                failure_count += 1
                continue

            # Deduplication check on email
            if email_field and hasattr(entity, email_field):
                raw_email = getattr(entity, email_field)
                if raw_email:
                    normalized_email = str(raw_email).strip().lower()
                    # Atomically check and add to Redis set
                    is_new = self.redis_client.sadd(dedup_redis_key, normalized_email)
                    self.redis_client.expire(dedup_redis_key, 86400)  # 24hr TTL

                    if is_new == 0:
                        # Email duplicate detected within this bulk action!
                        logs.append(
                            EntityLogEntryDTO(
                                entity_id=str(entity_id),
                                status=LogStatus.SKIPPED,
                                error_message=f"Duplicate entity with email '{raw_email}' skipped.",
                            )
                        )
                        skipped_count += 1
                        continue

            # Apply field mutations
            try:
                for field_name, value in fields_to_update.items():
                    setattr(entity, field_name, value)

                entities_to_persist[entity.id] = entity
                logs.append(
                    EntityLogEntryDTO(
                        entity_id=str(entity_id),
                        status=LogStatus.SUCCESS,
                    )
                )
                success_count += 1
            except Exception as exc:
                logger.error(
                    "entity_mutation_failed",
                    extra={
                        "bulk_action_id": str(bulk_action.id),
                        "entity_id": str(entity_id),
                        "error": str(exc),
                    },
                )
                logs.append(
                    EntityLogEntryDTO(
                        entity_id=str(entity_id),
                        status=LogStatus.ERROR,
                        error_message=str(exc),
                    )
                )
                failure_count += 1

        # Database efficiency: bulk_update in single query
        if entities_to_persist and fields_to_update:
            repository.bulk_update(list(entities_to_persist.values()), list(fields_to_update.keys()))

        return StrategyResultDTO(
            success_count=success_count,
            failure_count=failure_count,
            skipped_count=skipped_count,
            logs=logs,
        )
