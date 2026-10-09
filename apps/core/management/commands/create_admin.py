from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    """Create a default superuser if it doesn't already exist."""

    help = "Create an admin superuser."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--username", type=str, default="admin", help="Superuser username")
        parser.add_argument("--email", type=str, default="admin@example.com", help="Superuser email")
        parser.add_argument("--password", type=str, default="admin123", help="Superuser password")

    def handle(self, *args, **options) -> None:
        username = options["username"]
        email = options["email"]
        password = options["password"]

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"Superuser '{username}' already exists."))
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created successfully (password: {password})."))
