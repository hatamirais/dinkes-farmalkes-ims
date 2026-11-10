"""Serialization for IMS account creation (not a global identity constraint)."""

from contextlib import contextmanager

from django.db import transaction

from .models import UserCreationLock


@contextmanager
def serialized_user_creation():
    with transaction.atomic():
        # get_or_create also supports freshly flushed test databases.
        UserCreationLock.objects.get_or_create(pk=1)
        UserCreationLock.objects.select_for_update().get(pk=1)
        yield
