from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.db import models


class UserManager(DjangoUserManager):
    def _create_user(self, username, email, password, **extra_fields):
        is_superuser = extra_fields.get("is_superuser", False)
        role = extra_fields.get("role")

        if is_superuser:
            extra_fields["role"] = "ADMIN"
            extra_fields["is_staff"] = True
        elif role == "ADMIN":
            raise ValueError(
                "Role Admin hanya dapat dibuat melalui perintah createsuperuser."
            )

        return super()._create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model with role-based access control."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        KEPALA = "KEPALA", "Kepala Instalasi"
        ADMIN_UMUM = "ADMIN_UMUM", "Admin Umum"
        GUDANG = "GUDANG", "Petugas Gudang"
        AUDITOR = "AUDITOR", "Auditor"
        PUSKESMAS = "PUSKESMAS", "Operator Puskesmas"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ADMIN_UMUM,
        verbose_name="Jabatan",
    )
    full_name = models.CharField(max_length=255, blank=True)
    nip = models.CharField(max_length=30, blank=True, verbose_name="NIP")
    facility = models.ForeignKey(
        "items.Facility",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operators",
        help_text="For PUSKESMAS role: the facility this user belongs to",
    )

    objects = UserManager()

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.full_name or self.username

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
            self.is_staff = True
        elif self.role == self.Role.ADMIN:
            if not self.pk:
                raise ValidationError(
                    {"role": "Role Admin hanya dapat dibuat melalui createsuperuser."}
                )

            previous_state = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("role", "is_superuser")
                .first()
            )
            if not previous_state or previous_state != (self.Role.ADMIN, False):
                raise ValidationError(
                    {"role": "Role Admin hanya dapat dibuat melalui createsuperuser."}
                )

        return super().save(*args, **kwargs)


class ModuleAccess(models.Model):
    class Module(models.TextChoices):
        USERS = "users", "Manajemen User"
        ITEMS = "items", "Master Barang"
        STOCK = "stock", "Stok"
        RECEIVING = "receiving", "Penerimaan"
        PROCUREMENT = "procurement", "SPJ / Pengadaan"
        DISTRIBUTION = "distribution", "Distribusi"
        ALLOCATION = "allocation", "Alokasi"
        RECALL = "recall", "Recall / Retur"
        EXPIRED = "expired", "Kadaluarsa"
        STOCK_OPNAME = "stock_opname", "Stock Opname"
        REPORTS = "reports", "Laporan"
        ADMIN_PANEL = "admin_panel", "Admin Panel"
        PUSKESMAS = "puskesmas", "Permintaan Puskesmas"
        LPLPO = "lplpo", "LPLPO"

    class Scope(models.IntegerChoices):
        NONE = 0, "Tidak Ada"
        VIEW = 1, "Lihat"
        OPERATE = 2, "Operasional"
        APPROVE = 3, "Persetujuan"
        MANAGE = 4, "Kelola"

    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="module_accesses",
    )
    module = models.CharField(max_length=30, choices=Module.choices)
    scope = models.PositiveSmallIntegerField(choices=Scope.choices, default=Scope.NONE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_module_accesses"
        verbose_name = "Module Access"
        verbose_name_plural = "Module Accesses"
        unique_together = ("user", "module")

    def __str__(self):
        return f"{self.user.username} - {self.module}: {self.get_scope_display()}"
