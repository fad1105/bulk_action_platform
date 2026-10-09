import pytest

from apps.bulk_actions.models import BulkAction, BulkActionChunk
from apps.bulk_actions.strategies.bulk_update import BulkUpdateStrategy
from apps.bulk_actions.strategies.factory import StrategyFactory
from apps.core.exceptions import BulkActionValidationException
from apps.entities.models import Contact, Lead


@pytest.mark.django_db
class TestModularStrategyPattern:
    """Test Modular Strategy Pattern and Entity-Agnostic design."""

    def setup_method(self) -> None:
        self.strategy = BulkUpdateStrategy()

    def test_factory_resolves_bulk_update_strategy(self) -> None:
        resolved = StrategyFactory.get("bulk_update")
        assert isinstance(resolved, BulkUpdateStrategy)
        assert resolved.get_action_name() == "bulk_update"

    def test_validate_payload_rejects_missing_fields(self) -> None:
        with pytest.raises(BulkActionValidationException, match="must contain a 'fields' dictionary"):
            self.strategy.validate_payload("contact", {})

    def test_validate_payload_rejects_invalid_model_fields(self) -> None:
        with pytest.raises(BulkActionValidationException, match="Invalid fields"):
            self.strategy.validate_payload("contact", {"fields": {"non_existent_column": "val"}})

    def test_bulk_update_contact_updates_any_field(self) -> None:
        # Create contacts
        c1 = Contact.objects.create(name="Alice", email="alice@example.com", age=30, status="active")
        c2 = Contact.objects.create(name="Bob", email="bob@example.com", age=25, status="active")

        action = BulkAction.objects.create(
            account_id="acc_strat_1",
            entity_type="contact",
            action_type="bulk_update",
            payload={"fields": {"status": "archived", "age": 40}},
            total_count=2,
        )
        chunk = BulkActionChunk.objects.create(
            bulk_action=action,
            chunk_index=0,
            start_index=0,
            end_index=1,
            entity_ids=[c1.id, c2.id],
        )

        result = self.strategy.execute(
            bulk_action=action,
            chunk=chunk,
            entity_ids=[c1.id, c2.id],
            payload={"fields": {"status": "archived", "age": 40}},
        )

        assert result.success_count == 2
        assert result.failure_count == 0
        assert result.skipped_count == 0

        c1.refresh_from_db()
        c2.refresh_from_db()
        assert c1.status == "archived"
        assert c1.age == 40
        assert c2.status == "archived"
        assert c2.age == 40

    def test_bulk_update_entity_agnostic_lead(self) -> None:
        """Verify that BulkUpdateStrategy executes seamlessly on Lead entity without code changes."""
        lead = Lead.objects.create(
            name="Charlie",
            email="charlie@company.com",
            company="Acme Corp",
            status="new",
        )

        action = BulkAction.objects.create(
            account_id="acc_strat_2",
            entity_type="lead",
            action_type="bulk_update",
            payload={"fields": {"status": "qualified", "company": "Acme Global"}},
            total_count=1,
        )
        chunk = BulkActionChunk.objects.create(
            bulk_action=action,
            chunk_index=0,
            start_index=0,
            end_index=0,
            entity_ids=[lead.id],
        )

        result = self.strategy.execute(
            bulk_action=action,
            chunk=chunk,
            entity_ids=[lead.id],
            payload={"fields": {"status": "qualified", "company": "Acme Global"}},
        )

        assert result.success_count == 1
        lead.refresh_from_db()
        assert lead.status == "qualified"
        assert lead.company == "Acme Global"
