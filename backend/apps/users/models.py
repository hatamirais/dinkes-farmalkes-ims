from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model with role-based access control."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        KEPALA = "KEPALA", "Kepala Instalasi"
        ADMIN_UMUM = "ADMIN_UMUM", "Admin Umum"
        GUDANG = "GUDANG", "Petugas Gudang"
        AUDITOR = "AUDITOR", "Auditor"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ADMIN_UMUM,
        verbose_name="Jabatan",
    )
    full_name = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.full_name or self.username


class ModuleAccess(models.Model):
    class Module(models.TextChoices):
        USERS = "users", "Manajemen User"
        ITEMS = "items", "Master Barang"
        STOCK = "stock", "Stok"
        RECEIVING = "receiving", "Penerimaan"
        DISTRIBUTION = "distribution", "Distribusi"
        RECALL = "recall", "Recall / Retur"
        EXPIRED = "expired", "Kadaluarsa"
        STOCK_OPNAME = "stock_opname", "Stock Opname"
        REPORTS = "reports", "Laporan"
        ADMIN_PANEL = "admin_panel", "Admin Panel"

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
