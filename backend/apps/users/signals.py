"""
Signals for the users app.

Auto-syncs Django Groups and is_staff flag based on the User.role field,
so that setting a user's role automatically assigns the correct group,
its permissions, and the appropriate Admin panel access.
"""

from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db.models.deletion import ProtectedError
from django.db.models.signals import post_save
from django.dispatch import receiver

from .access import ensure_default_module_access
from .models import AuthorityExercise


# Maps User.role values → Django Group names
ROLE_GROUP_MAP = {
    "ADMIN": "ADMIN",
    "KEPALA": "KEPALA INSTALASI",
    "ADMIN_UMUM": "ADMIN UMUM",
    "GUDANG": "GUDANG",
    "AUDITOR": "AUDITOR",
    "PUSKESMAS": "OPERATOR PUSKESMAS",
}

# Roles that should have Django Admin panel access (is_staff=True)
STAFF_ROLES = {"ADMIN"}


@receiver(post_save, sender="users.User")
def sync_user_group(sender, instance, **kwargs):
    """
    When a User is saved:
    1. Assign them to the Django Group matching their role (remove others).
    2. Sync is_staff so ADMIN-role users can access the Django Admin panel.
    3. Seed ModuleAccess defaults for dashboard feature gating.

    Uses queryset.update() for is_staff to avoid re-triggering this signal.
    """
    group_name = ROLE_GROUP_MAP.get(instance.role)
    if not group_name:
        return

    # ── 1. Sync Django Group ──────────────────────────────────────────────
    all_role_groups = Group.objects.filter(name__in=ROLE_GROUP_MAP.values())
    instance.groups.remove(*all_role_groups)
    group, _ = Group.objects.get_or_create(name=group_name)
    instance.groups.add(group)

    # ── 2. Sync is_staff (Django Admin access) ────────────────────────────
    # Superusers always keep is_staff=True regardless of role; skip them.
    # Use queryset.update() instead of instance.save() to avoid signal loop.
    if not instance.is_superuser:
        needs_staff = instance.role in STAFF_ROLES
        if instance.is_staff != needs_staff:
            sender.objects.filter(pk=instance.pk).update(is_staff=needs_staff)

    # ── 3. Seed ModuleAccess defaults ────────────────────────────────────
    ensure_default_module_access(instance)


def protect_authority_exercise_target(sender, instance, **kwargs):
    """Prevent hard deletion from orphaning append-only authority evidence."""
    content_type = ContentType.objects.get_for_model(
        instance,
        for_concrete_model=False,
    )
    exercises = AuthorityExercise.objects.filter(
        content_type=content_type,
        object_id=instance.pk,
    )
    if exercises.exists():
        raise ProtectedError(
            "Dokumen tidak dapat dihapus karena memiliki riwayat penggunaan "
            "delegasi wewenang.",
            exercises,
        )
