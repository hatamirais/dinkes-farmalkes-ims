"""
Signals for the users app.

Auto-syncs Django Groups based on the User.role field, so that setting
a user's role automatically assigns the correct group and its permissions.
"""

from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from .access import ensure_default_module_access


# Maps User.role values → Django Group names
ROLE_GROUP_MAP = {
    "ADMIN": "ADMIN",
    "KEPALA": "KEPALA INSTALASI",
    "ADMIN_UMUM": "ADMIN UMUM",
    "GUDANG": "GUDANG",
    "AUDITOR": "AUDITOR",
}


@receiver(post_save, sender="users.User")
def sync_user_group(sender, instance, **kwargs):
    """
    When a User is saved, automatically assign them to the Django Group
    that matches their role (and remove them from other role groups).

    This ensures that permissions configured in the Admin → Groups panel
    are automatically applied to the user based on their role.
    """
    group_name = ROLE_GROUP_MAP.get(instance.role)
    if not group_name:
        return

    # Get all role-related groups
    all_role_groups = Group.objects.filter(name__in=ROLE_GROUP_MAP.values())

    # Remove user from all role groups first
    instance.groups.remove(*all_role_groups)

    # Add to the correct group (create if it doesn't exist yet)
    group, _ = Group.objects.get_or_create(name=group_name)
    instance.groups.add(group)

    # Ensure module access defaults are seeded for this user
    ensure_default_module_access(instance)
