"""Facility counts, retained decisions and evidence links."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .inventory_models import ImmutableRecord


class OpnameAuthority(models.Model):
    facility = models.ForeignKey("items.Facility", on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    review_count = models.BooleanField(default=False)
    approve_adjustment = models.BooleanField(default=False)
    correct_receipt = models.BooleanField(default=False)
    reopen_count = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("facility", "user"), name="pkopname_authority_facility_user"),
        ]

    def __str__(self):
        return f"{self.facility} / {self.user}"


class OpnameActivation(ImmutableRecord):
    facility = models.OneToOneField("items.Facility", on_delete=models.PROTECT)
    first_month = models.DateField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)


class FacilityOpname(ImmutableRecord):
    facility = models.ForeignKey("items.Facility", on_delete=models.PROTECT)
    cutoff = models.DateField()
    roster = models.JSONField()
    initial_comparison = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("facility", "cutoff"), name="pkopname_facility_cutoff"),
        ]


class OpnameRevision(ImmutableRecord):
    class State(models.TextChoices):
        COUNTING = "COUNTING", "Penghitungan"
        CLOSED_OPEN = "CLOSED_OPEN", "Ditutup dengan selisih"
        RECONCILED = "RECONCILED", "Direkonsiliasi"

    count = models.ForeignKey(FacilityOpname, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=12, choices=State.choices)
    observations = models.JSONField(default=dict)
    comparison = models.JSONField(default=dict)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    actor_label = models.CharField(max_length=255)
    reason = models.CharField(max_length=1000, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("count", "number"), name="pkopname_revision_number"),
        ]


class OpnameCaseNote(ImmutableRecord):
    count = models.ForeignKey(FacilityOpname, on_delete=models.PROTECT, related_name="case_notes")
    revision = models.ForeignKey(OpnameRevision, on_delete=models.PROTECT)
    case_key = models.CharField(max_length=64)
    evidence = models.CharField(max_length=1000)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)


class OpnameAction(ImmutableRecord):
    class Kind(models.TextChoices):
        ADJUST = "ADJUST", "Pengurangan karena hilang atau rusak"
        RECEIPT = "RECEIPT", "Koreksi kelebihan penerimaan"
        REVERSE = "REVERSE", "Pembalikan penyesuaian"
        REOPEN = "REOPEN", "Pembukaan ulang"

    key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    count = models.ForeignKey(FacilityOpname, on_delete=models.PROTECT, related_name="actions")
    revision = models.ForeignKey(OpnameRevision, on_delete=models.PROTECT)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    case_key = models.CharField(max_length=64, blank=True)
    journal_digest = models.CharField(max_length=64)
    layer = models.ForeignKey("puskesmas.PuskesmasInventoryLayer", on_delete=models.PROTECT, null=True, blank=True)
    reverses = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)
    add_location = models.ForeignKey("puskesmas.PuskesmasSubunit", on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    incident_date = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=1000)
    reference = models.CharField(max_length=255)
    expected_change = models.CharField(max_length=1000, blank=True)
    preparer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)


class OpnameDecision(ImmutableRecord):
    action = models.OneToOneField(OpnameAction, on_delete=models.PROTECT, related_name="decision")
    approved = models.BooleanField()
    reason = models.CharField(max_length=1000, blank=True)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    posting = models.OneToOneField("puskesmas.PuskesmasInventoryPosting", on_delete=models.PROTECT, null=True, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)


class LPLPOOpnameLink(ImmutableRecord):
    lplpo = models.ForeignKey("lplpo.LPLPO", on_delete=models.PROTECT, related_name="opname_links")
    revision = models.ForeignKey(OpnameRevision, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
