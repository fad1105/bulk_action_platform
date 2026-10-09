import uuid

from django.core.management.base import BaseCommand

from apps.entities.models import Contact


class Command(BaseCommand):
    """Seed sample contacts for bulk action testing."""

    help = "Seed database with contacts for bulk testing."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--count",
            type=int,
            default=1000,
            help="Number of contacts to seed (default: 1000).",
        )

    def handle(self, *args, **options) -> None:
        count = options["count"]
        self.stdout.write(f"Generating {count} sample contacts...")

        batch_size = 2000
        total_created = 0

        for batch_start in range(0, count, batch_size):
            batch_count = min(batch_size, count - batch_start)
            batch = [
                Contact(
                    name=f"Contact_{batch_start + i}",
                    email=f"contact_{uuid.uuid4().hex[:8]}_{batch_start + i}@example.com",
                    age=20 + ((batch_start + i) % 60),
                    status="active",
                )
                for i in range(batch_count)
            ]
            Contact.objects.bulk_create(batch)
            total_created += len(batch)
            self.stdout.write(f"  Persisted {total_created}/{count} contacts...")

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {total_created} contacts."))
