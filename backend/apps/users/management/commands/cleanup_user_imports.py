from django.core.management.base import BaseCommand

from apps.users.csv_import import cleanup_expired_imports


class Command(BaseCommand):
    help = "Delete expired user CSV previews and their password hashes."

    def handle(self, *args, **options):
        count = cleanup_expired_imports()
        self.stdout.write(f"Deleted {count} expired user import previews.")
