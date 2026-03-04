"""
Management command to fix Django group permissions based on reviewed recommendations.

Run with: python manage.py fix_group_permissions

Changes applied:
1. KEPALA INSTALASI: Remove stock/transaction add/change/delete (keep view only)
2. GUDANG: Add recall.* permissions
3. GUDANG: Add receiving document permissions
4. GUDANG: Restrict items to view-only
5. GUDANG: Remove delete_stock, delete_transaction
6. ADMIN UMUM: Add receiving.* permissions
7. ADMIN UMUM: Add distribution.* permissions
8. ADMIN UMUM: Add view_stock, view_transaction
9. ADMIN UMUM: Remove contenttypes CRUD (keep view only)
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType


class Command(BaseCommand):
    help = 'Fix group permissions based on review recommendations'

    def _get_perms(self, app_label, model=None, actions=None):
        """Get permissions by app_label, optional model, optional action list."""
        qs = Permission.objects.filter(content_type__app_label=app_label)
        if model:
            qs = qs.filter(content_type__model=model)
        if actions:
            codenames = []
            for action in actions:
                if model:
                    codenames.append(f'{action}_{model}')
                else:
                    codenames.append(action)
            qs = qs.filter(codename__in=codenames)
        return qs

    def _get_perms_by_codenames(self, app_label, codenames):
        """Get permissions by exact codenames."""
        return Permission.objects.filter(
            content_type__app_label=app_label,
            codename__in=codenames,
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Fixing group permissions...\n'))

        # ── 1. KEPALA INSTALASI ─────────────────────────────────────
        try:
            kepala = Group.objects.get(name='KEPALA INSTALASI')
            self.stdout.write('=== KEPALA INSTALASI ===')

            # Remove add/change/delete for stock and transaction (keep view)
            to_remove = self._get_perms_by_codenames('stock', [
                'add_stock', 'change_stock', 'delete_stock',
                'add_transaction', 'change_transaction', 'delete_transaction',
            ])
            removed = list(to_remove.values_list('codename', flat=True))
            kepala.permissions.remove(*to_remove)
            self.stdout.write(self.style.WARNING(f'  Removed: {removed}'))

        except Group.DoesNotExist:
            self.stdout.write(self.style.ERROR('  Group "KEPALA INSTALASI" not found!'))

        # ── 2-5. GUDANG ─────────────────────────────────────────────
        try:
            gudang = Group.objects.get(name='GUDANG')
            self.stdout.write('\n=== GUDANG ===')

            # 2. Add recall.* permissions
            recall_perms = self._get_perms('recall')
            gudang.permissions.add(*recall_perms)
            self.stdout.write(self.style.SUCCESS(
                f'  Added recall: {list(recall_perms.values_list("codename", flat=True))}'
            ))

            # 3. Add receiving document permissions
            doc_perms = self._get_perms_by_codenames('receiving', [
                'add_receivingdocument', 'change_receivingdocument',
                'delete_receivingdocument', 'view_receivingdocument',
            ])
            gudang.permissions.add(*doc_perms)
            self.stdout.write(self.style.SUCCESS(
                f'  Added receiving docs: {list(doc_perms.values_list("codename", flat=True))}'
            ))

            # 4. Restrict items to view-only (remove add/change/delete)
            items_models = [
                'category', 'facility', 'fundingsource', 'item',
                'location', 'program', 'supplier', 'unit',
            ]
            items_to_remove = []
            for model_name in items_models:
                for action in ['add', 'change', 'delete']:
                    items_to_remove.append(f'{action}_{model_name}')

            items_remove_perms = self._get_perms_by_codenames('items', items_to_remove)
            removed = list(items_remove_perms.values_list('codename', flat=True))
            gudang.permissions.remove(*items_remove_perms)
            self.stdout.write(self.style.WARNING(f'  Removed items write: {removed}'))

            # 5. Remove delete_stock, delete_transaction
            stock_remove = self._get_perms_by_codenames('stock', [
                'delete_stock', 'delete_transaction',
            ])
            removed = list(stock_remove.values_list('codename', flat=True))
            gudang.permissions.remove(*stock_remove)
            self.stdout.write(self.style.WARNING(f'  Removed: {removed}'))

        except Group.DoesNotExist:
            self.stdout.write(self.style.ERROR('  Group "GUDANG" not found!'))

        # ── 6-9. ADMIN UMUM ─────────────────────────────────────────
        try:
            admin_umum = Group.objects.get(name='ADMIN UMUM')
            self.stdout.write('\n=== ADMIN UMUM ===')

            # 6. Add receiving.* permissions
            receiving_perms = self._get_perms('receiving')
            admin_umum.permissions.add(*receiving_perms)
            self.stdout.write(self.style.SUCCESS(
                f'  Added receiving: {list(receiving_perms.values_list("codename", flat=True))}'
            ))

            # 7. Add distribution.* permissions
            dist_perms = self._get_perms('distribution')
            admin_umum.permissions.add(*dist_perms)
            self.stdout.write(self.style.SUCCESS(
                f'  Added distribution: {list(dist_perms.values_list("codename", flat=True))}'
            ))

            # 8. Add view_stock, view_transaction
            stock_view = self._get_perms_by_codenames('stock', [
                'view_stock', 'view_transaction',
            ])
            admin_umum.permissions.add(*stock_view)
            self.stdout.write(self.style.SUCCESS(
                f'  Added stock view: {list(stock_view.values_list("codename", flat=True))}'
            ))

            # 9. Remove contenttypes add/change/delete (keep view)
            ct_remove = self._get_perms_by_codenames('contenttypes', [
                'add_contenttype', 'change_contenttype', 'delete_contenttype',
            ])
            removed = list(ct_remove.values_list('codename', flat=True))
            admin_umum.permissions.remove(*ct_remove)
            self.stdout.write(self.style.WARNING(f'  Removed contenttypes: {removed}'))

        except Group.DoesNotExist:
            self.stdout.write(self.style.ERROR('  Group "ADMIN UMUM" not found!'))

        self.stdout.write(self.style.SUCCESS('\n✅ All group permissions fixed!'))
