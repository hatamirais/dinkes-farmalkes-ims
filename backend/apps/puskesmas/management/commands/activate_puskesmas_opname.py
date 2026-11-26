from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.items.models import Facility
from apps.puskesmas.opname_lplpo import activate


class Command(BaseCommand):
    help = "Activate the Puskesmas Stock Opname gate for a verified reporting month."

    def add_arguments(self, parser):
        parser.add_argument("--facility-code", required=True)
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)
        parser.add_argument("--actor", required=True, help="Username of the authorizing superuser.")

    def handle(self, *args, **options):
        users = get_user_model()
        try:
            actor = users.objects.get(username=options["actor"], is_active=True, is_superuser=True)
            facility = Facility.objects.get(code=options["facility_code"])
            rollout = activate(user=actor, facility_id=facility.pk, year=options["year"], month=options["month"])
        except users.DoesNotExist as exc:
            raise CommandError("An active superuser is required.") from exc
        except Facility.DoesNotExist as exc:
            raise CommandError("Facility code was not found.") from exc
        except (ValidationError, PermissionDenied) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"{facility.code}: Stock Opname required from {rollout.first_month:%Y-%m}."))
