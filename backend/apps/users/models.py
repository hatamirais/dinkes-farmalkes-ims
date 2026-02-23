from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model with role-based access control."""

    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        KEPALA = 'KEPALA', 'Kepala Instalasi'
        ADMIN_UMUM = 'ADMIN_UMUM', 'Admin Umum'
        GUDANG = 'GUDANG', 'Petugas Gudang'
        KEUANGAN = 'KEUANGAN', 'Petugas Keuangan'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ADMIN_UMUM,
    )
    full_name = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.full_name or self.username
