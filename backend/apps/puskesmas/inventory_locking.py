"""Shared facility mutex for receipt checkpoints and editable LPLPO periods."""
from functools import wraps

from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.contrib import messages
from django.shortcuts import redirect
from apps.users.access import is_super_admin


def serialize_facility_document(model_label):
    """Lock before a view binds a mutable form or reads period status."""
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            model = apps.get_model(model_label)
            pk = kwargs.get("pk")
            facility_id = model.objects.filter(pk=pk).values_list("facility_id", flat=True).first() if pk else None
            if not facility_id and request.method == "POST":
                facility_id = request.POST.get("facility") if is_super_admin(request.user) else request.user.facility_id
            try:
                facility_id = int(facility_id) if facility_id else None
            except (ValueError, TypeError):
                facility_id = None  # The bound form owns invalid IDs.
            if not facility_id:
                return view(request, *args, **kwargs)
            from apps.items.models import Facility
            from .inventory import locked_actor
            with transaction.atomic():
                request.user = locked_actor(request.user)
                from apps.users.access import has_module_permission
                # Decorators ran before locking. Repeat the action permission with
                # the fresh actor so revocation cannot race form binding/posting.
                if not request.user.is_active:
                    raise PermissionDenied
                if request.method == "POST" and not request.user.is_superuser:
                    if model_label == "puskesmas.PuskesmasReceiptConfirmation":
                        action = "delete" if "delete" in view.__name__ else "change" if pk else "add"
                        perms = [f"puskesmas.{action}_puskesmasreceiptconfirmation", f"puskesmas.{action}_puskesmassbbk"]
                    else:
                        action = "add" if not pk else "change"
                        perms = [f"lplpo.{action}_lplpo"]
                    if not any(request.user.has_perm(perm) or has_module_permission(request.user, perm) for perm in perms):
                        raise PermissionDenied
                Facility.objects.select_for_update().filter(pk=facility_id).first()
                if pk:
                    document = model.objects.select_for_update().filter(pk=pk).first()
                    if (request.method == "POST" and model_label == "puskesmas.PuskesmasReceiptConfirmation"
                            and document and document.inventory_posting_exists()):
                        # Preserve the owning view's role/facility checks before exposing a message.
                        from .views import _check_puskesmas_receiving_creator_access, _check_receiving_facility_access
                        _check_puskesmas_receiving_creator_access(request)
                        _check_receiving_facility_access(request, document)
                        messages.error(request, "Penerimaan sudah diposting; perubahan dan penghapusan dikunci.")
                        return redirect("puskesmas:receiving_detail", pk=pk)
                return view(request, *args, **kwargs)
        return wrapped
    return decorate


def assert_receipt_mutable(receipt_id, *, new_facility_id=None, new_date=None):
    """Caller holds an atomic block. Also used by model/QuerySet entry points."""
    Receipt = apps.get_model("puskesmas.PuskesmasReceiptConfirmation")
    Posting = apps.get_model("puskesmas.PuskesmasInventoryPosting")
    Account = apps.get_model("puskesmas.PuskesmasInventoryAccount")
    Facility = apps.get_model("items.Facility")
    old = Receipt.objects.filter(pk=receipt_id).values("facility_id", "received_date").first()
    ids = sorted({value for value in [old["facility_id"] if old else None, new_facility_id] if value})
    list(Facility.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    if Posting.objects.filter(receipt_id=receipt_id).exists():
        raise ValidationError("Penerimaan yang sudah diposting tidak dapat diubah/dihapus.")
    if old:
        account = Account.objects.filter(facility_id=old["facility_id"]).first()
        if account and (
            (new_facility_id and new_facility_id != old["facility_id"]) or
            (new_date and (not hasattr(new_date, "year") or
             (new_date < account.effective_date) != (old["received_date"] < account.effective_date)))
        ):
            raise ValidationError("Perubahan tidak boleh memindahkan penerimaan melewati batas saldo awal.")


class ReceiptQuerySet(models.QuerySet):
    def _lock_and_check(self, **changes):
        is_header = self.model._meta.model_name == "puskesmasreceiptconfirmation"
        ids = list(self.values_list("pk" if is_header else "sbbk_id", flat=True).distinct())
        for receipt_id in sorted(ids):
            assert_receipt_mutable(receipt_id,
                new_facility_id=changes.get("facility_id") or getattr(changes.get("facility"), "pk", None),
                new_date=changes.get("received_date"))
        if not is_header and ("sbbk_id" in changes or "sbbk" in changes):
            target = changes.get("sbbk_id") or getattr(changes.get("sbbk"), "pk", None)
            if not isinstance(target, int):
                raise ValidationError("Perubahan induk penerimaan harus menggunakan ID yang valid.")
            assert_receipt_mutable(target)

    def update(self, **kwargs):
        with transaction.atomic():
            self._lock_and_check(**kwargs)
            return super().update(**kwargs)

    def delete(self):
        with transaction.atomic():
            self._lock_and_check()
            return super().delete()

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Upsert penerimaan tidak diizinkan; gunakan layanan konfirmasi.")
        objs = list(objs)
        with transaction.atomic():
            for obj in objs:
                if hasattr(obj, "sbbk_id"):
                    assert_receipt_mutable(obj.sbbk_id)
            return super().bulk_create(objs, **kwargs)
