from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


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


APPROVAL_MODULE_CHOICES = (
    (ModuleAccess.Module.RECEIVING, ModuleAccess.Module.RECEIVING.label),
    (ModuleAccess.Module.PROCUREMENT, ModuleAccess.Module.PROCUREMENT.label),
    (ModuleAccess.Module.DISTRIBUTION, ModuleAccess.Module.DISTRIBUTION.label),
    (ModuleAccess.Module.ALLOCATION, ModuleAccess.Module.ALLOCATION.label),
    (ModuleAccess.Module.RECALL, ModuleAccess.Module.RECALL.label),
    (ModuleAccess.Module.EXPIRED, ModuleAccess.Module.EXPIRED.label),
    (ModuleAccess.Module.STOCK_OPNAME, ModuleAccess.Module.STOCK_OPNAME.label),
    (ModuleAccess.Module.PUSKESMAS, ModuleAccess.Module.PUSKESMAS.label),
    (ModuleAccess.Module.LPLPO, ModuleAccess.Module.LPLPO.label),
)


class TsTzRange(models.Func):
    """PostgreSQL half-open timezone-aware range used by the overlap constraint."""

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class AuthorityDelegation(models.Model):
    class Authority(models.TextChoices):
        KEPALA_APPROVAL = "KEPALA_APPROVAL", "Persetujuan Kepala Instalasi"

    authority = models.CharField(
        max_length=30,
        choices=Authority.choices,
        default=Authority.KEPALA_APPROVAL,
    )
    module = models.CharField(max_length=30, choices=APPROVAL_MODULE_CHOICES)
    delegate = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="authority_delegations",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=500)
    granted_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="granted_authority_delegations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="revoked_authority_delegations",
        null=True,
        blank=True,
    )
    revocation_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "user_authority_delegations"
        verbose_name = "Authority Delegation"
        verbose_name_plural = "Authority Delegations"
        ordering = ("-starts_at", "module", "pk")
        indexes = [
            models.Index(
                fields=("delegate", "revoked_at"),
                name="auth_del_delegate_active_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at"))
                ),
                name="authority_delegation_valid_period",
            ),
            ExclusionConstraint(
                name="authority_delegation_no_overlap",
                expressions=(
                    (
                        TsTzRange("starts_at", "ends_at", RangeBoundary()),
                        RangeOperators.OVERLAPS,
                    ),
                    ("authority", RangeOperators.EQUAL),
                    ("module", RangeOperators.EQUAL),
                ),
                condition=Q(revoked_at__isnull=True),
                violation_error_message=(
                    "Sudah ada delegasi aktif atau terjadwal yang bertumpang tindih "
                    "untuk modul ini."
                ),
            ),
        ]

    def __str__(self):
        period_end = (
            f"{self.ends_at:%Y-%m-%d %H:%M}"
            if self.ends_at
            else "sampai dicabut"
        )
        return (
            f"{self.delegate} - {self.get_module_display()} "
            f"({self.starts_at:%Y-%m-%d %H:%M}–{period_end})"
        )


class AuthorityExercise(models.Model):
    """Append-only evidence that a workflow action used delegated authority."""

    delegation = models.ForeignKey(
        AuthorityDelegation,
        on_delete=models.PROTECT,
        related_name="exercises",
    )
    actor = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="authority_exercises",
    )
    module = models.CharField(max_length=30, choices=APPROVAL_MODULE_CHOICES)
    action = models.CharField(max_length=50)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    exercised_at = models.DateTimeField()
    actor_name_snapshot = models.CharField(max_length=255)
    actor_nip_snapshot = models.CharField(max_length=30, blank=True)
    authority_title_snapshot = models.CharField(
        max_length=100,
        default="Plh. Kepala Instalasi",
    )
    delegation_starts_at_snapshot = models.DateTimeField()
    delegation_ends_at_snapshot = models.DateTimeField(null=True, blank=True)
    grantor_name_snapshot = models.CharField(max_length=255)
    reason_snapshot = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_authority_exercises"
        verbose_name = "Authority Exercise"
        verbose_name_plural = "Authority Exercises"
        ordering = ("-exercised_at", "-pk")
        indexes = [
            models.Index(
                fields=("content_type", "object_id"),
                name="auth_exercise_target_idx",
            ),
        ]

    def __str__(self):
        return f"{self.actor} - {self.module}.{self.action} @ {self.exercised_at}"
