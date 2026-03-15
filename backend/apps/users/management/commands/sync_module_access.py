from django.core.management.base import BaseCommand

from apps.users.access import ensure_default_module_access
from apps.users.models import User


class Command(BaseCommand):
    help = "Seed/sync module access defaults based on user title role"

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing scope values with role defaults",
        )

    def handle(self, *args, **options):
        overwrite = options["overwrite"]
        total = 0

        for user in User.objects.all().only("id", "username", "role"):
            changed = ensure_default_module_access(user, overwrite=overwrite)
            total += changed

        self.stdout.write(
            self.style.SUCCESS(
                f"Module access sync selesai. Records created/updated: {total}"
            )
        )
