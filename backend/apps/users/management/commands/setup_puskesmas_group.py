"""
Management command to set up the OPERATOR PUSKESMAS group with appropriate permissions.

Run with: python manage.py setup_puskesmas_group

Permissions granted:
- puskesmas.*  (full CRUD on PuskesmasRequest + PuskesmasRequestItem)
- items: view_item, view_unit, view_category, view_program, view_facility
- distribution: view_distribution, view_distributionitem
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission


class Command(BaseCommand):
    help = "Create/update OPERATOR PUSKESMAS group with correct permissions"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Setting up OPERATOR PUSKESMAS group...\n"))

        group, created = Group.objects.get_or_create(name="OPERATOR PUSKESMAS")
        action = "Created" if created else "Found existing"
        self.stdout.write(f"  {action} group: OPERATOR PUSKESMAS")

        # ── Clear existing permissions to reset cleanly ──
        group.permissions.clear()

        # ── 1. Puskesmas: full CRUD ──
        puskesmas_perms = Permission.objects.filter(
            content_type__app_label="puskesmas"
        )
        group.permissions.add(*puskesmas_perms)
        self.stdout.write(self.style.SUCCESS(
            f"  Added puskesmas: {list(puskesmas_perms.values_list('codename', flat=True))}"
        ))

        # ── 2. Items: view-only for reference data ──
        items_view_perms = Permission.objects.filter(
            content_type__app_label="items",
            codename__in=[
                "view_item",
                "view_unit",
                "view_category",
                "view_program",
                "view_facility",
                "view_fundingsource",
            ],
        )
        group.permissions.add(*items_view_perms)
        self.stdout.write(self.style.SUCCESS(
            f"  Added items (view): {list(items_view_perms.values_list('codename', flat=True))}"
        ))

        # ── 3. Distribution: view-only so they can see linked distributions ──
        dist_view_perms = Permission.objects.filter(
            content_type__app_label="distribution",
            codename__in=[
                "view_distribution",
                "view_distributionitem",
            ],
        )
        group.permissions.add(*dist_view_perms)
        self.stdout.write(self.style.SUCCESS(
            f"  Added distribution (view): {list(dist_view_perms.values_list('codename', flat=True))}"
        ))

        total = group.permissions.count()
        self.stdout.write(self.style.SUCCESS(
            f"\n✅ OPERATOR PUSKESMAS group configured with {total} permissions."
        ))
