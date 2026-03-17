from django.core.management.base import BaseCommand

from apps.users.access import ensure_default_module_access
from apps.users.models import User
from apps.users.signals import STAFF_ROLES


class Command(BaseCommand):
    help = "Seed/sync module access defaults AND is_staff flag based on user role"

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing scope values with role defaults",
        )

    def handle(self, *args, **options):
        overwrite = options["overwrite"]
        module_total = 0
        staff_fixed = []

        for user in User.objects.all().only("id", "username", "role", "is_staff", "is_superuser"):
            # Sync ModuleAccess rows
            changed = ensure_default_module_access(user, overwrite=overwrite)
            module_total += changed

            # Sync is_staff without triggering post_save signal.
            # Superusers always retain is_staff=True — skip them.
            if not user.is_superuser:
                needs_staff = user.role in STAFF_ROLES
                if user.is_staff != needs_staff:
                    staff_fixed.append(user)
                    user.is_staff = needs_staff

        if staff_fixed:
            User.objects.bulk_update(staff_fixed, ["is_staff"])
            for u in staff_fixed:
                flag = "\u2713 is_staff=True" if u.is_staff else "\u2717 is_staff=False"
                self.stdout.write(f"  {u.username} \u2192 {flag}")

        # Superusers must always have is_staff=True (Django invariant)
        superuser_fixed = User.objects.filter(is_superuser=True, is_staff=False)
        if superuser_fixed.exists():
            names = list(superuser_fixed.values_list("username", flat=True))
            superuser_fixed.update(is_staff=True)
            self.stdout.write(self.style.WARNING(
                f"  Restored is_staff for superusers: {names}"
            ))

        self.stdout.write(
            self.style.SUCCESS(
                f"Module access sync selesai. Records created/updated: {module_total}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"is_staff sync selesai. Users updated: {len(staff_fixed)}"
            )
        )
