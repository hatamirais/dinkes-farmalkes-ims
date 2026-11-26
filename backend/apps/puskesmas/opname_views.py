import uuid
from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .opname import (
    add_case_evidence, authority, close_count, compare_revision, current_revision, operator, revision_roster, save_location,
    start_count, visible_counts,
)
from .opname_actions import APPROVAL, decide_action, request_action
from .opname_forms import (
    ActionForm, CaseEvidenceForm, CloseCountForm, DecisionForm, LocationForm, ObservationForm,
    RevisionForm, StartCountForm,
)
from .opname_models import OpnameRevision
from .models import PuskesmasReceiptConfirmation


@login_required
def count_list(request):
    counts = visible_counts(request.user).select_related("facility").order_by("-cutoff", "facility__name")
    can_start = operator(request.user, request.user.facility_id)
    if not can_start and not counts.exists():
        raise PermissionDenied
    page = Paginator(counts, 25).get_page(request.GET.get("page"))
    return render(request, "puskesmas/opname_list.html", {"page": page, "can_start": can_start})


@login_required
def count_start(request):
    if not operator(request.user, request.user.facility_id):
        raise PermissionDenied
    today = timezone.localdate()
    form = StartCountForm(request.POST or None, facility_id=request.user.facility_id,
                          initial={"year": today.year, "month": today.month})
    if request.method == "POST" and form.is_valid():
        try:
            count = start_count(user=request.user, year=form.cleaned_data["year"], month=form.cleaned_data["month"],
                                inactive_ids=[location.pk for location in form.cleaned_data["inactive"]])
            return redirect("puskesmas:opname_detail", pk=count.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "puskesmas/opname_form.html", {"title": "Mulai Stock Opname", "form": form})


@login_required
def count_detail(request, pk):
    count = get_object_or_404(visible_counts(request.user).select_related("facility"), pk=pk)
    revision = current_revision(count)
    comparison = compare_revision(count, revision)
    is_operator = operator(request.user, count.facility_id)
    reviewer = authority(request.user, count.facility_id, "review_count") and count.created_by_id != request.user.pk
    has_open = any(row["open"] for row in comparison["rows"])
    can_close = reviewer if has_open else is_operator
    closed_state = OpnameRevision.State.CLOSED_OPEN if has_open else OpnameRevision.State.RECONCILED
    already_closed = revision.state == closed_state and revision.comparison == comparison
    form = CloseCountForm(initial={"revision": revision.pk, "journal": comparison["digest"]})
    if request.method == "POST":
        form = CloseCountForm(request.POST)
        if form.is_valid():
            try:
                close_count(user=request.user, count_id=pk, expected_revision=form.cleaned_data["revision"],
                            expected_journal=form.cleaned_data["journal"])
                messages.success(request, "Perbandingan Stock Opname disimpan.")
                return redirect("puskesmas:opname_detail", pk=pk)
            except ValidationError as exc:
                form.add_error(None, exc)
    actions = count.actions.select_related("preparer", "decision__approver", "decision__posting", "posting").order_by("-pk")
    rights = {kind for kind, grant in APPROVAL.items() if authority(request.user, count.facility_id, grant)}
    return render(request, "puskesmas/opname_detail.html", {
        "count": count, "revision": revision, "comparison": comparison, "form": form,
        "is_operator": is_operator, "can_close": can_close and not already_closed,
        "can_note": is_operator or reviewer, "has_open": has_open,
        "locations": [(location, revision.observations.get(location["key"], {})) for location in revision_roster(count, revision)],
        "actions": [(action, action.kind in rights and action.preparer_id != request.user.pk)
                    for action in actions],
        "revisions": count.revisions.exclude(state=OpnameRevision.State.COUNTING).order_by("-number"),
        "notes": count.case_notes.select_related("actor").order_by("-pk"),
    })


def _input_line(line):
    return {**line, "expiry": date.fromisoformat(line["expiry"]) if line["expiry"] else None,
            "factor": Decimal(line["factor"])}


@login_required
def count_location(request, pk, location_key):
    count = get_object_or_404(visible_counts(request.user), pk=pk)
    if not operator(request.user, count.facility_id):
        raise PermissionDenied
    revision = current_revision(count)
    location = next((row for row in revision_roster(count, revision) if row["key"] == location_key), None)
    if not location:
        raise Http404
    if revision.state != OpnameRevision.State.COUNTING:
        raise PermissionDenied
    saved = revision.observations.get(location_key, {})
    rows = saved.get("lines", [])
    measured = datetime.fromisoformat(saved["counted_at"]) if saved else timezone.now()
    form = LocationForm(initial={"revision": revision.pk, "counted_at": measured,
                                "evidence": saved.get("evidence", ""), "confirmed": saved.get("confirmed", False)})
    if request.method == "POST":
        form = LocationForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                save_location(user=request.user, count_id=pk, expected_revision=data["revision"], location_key=location_key,
                    counted_at=data["counted_at"], evidence=data["evidence"], lines=[_input_line(row) for row in rows],
                    confirmed=data["confirmed"])
                return redirect("puskesmas:opname_detail", pk=pk)
            except ValidationError as exc:
                form.add_error(None, exc)
    return render(request, "puskesmas/opname_location.html", {
        "count": count, "location": location, "rows": rows, "form": form, "revision": revision,
    })


@login_required
def count_observation(request, pk, location_key, row=None):
    count = get_object_or_404(visible_counts(request.user), pk=pk)
    if not operator(request.user, count.facility_id):
        raise PermissionDenied
    revision = current_revision(count)
    location = next((entry for entry in revision_roster(count, revision) if entry["key"] == location_key), None)
    if not location:
        raise Http404
    if revision.state != OpnameRevision.State.COUNTING:
        raise PermissionDenied
    saved = revision.observations.get(location_key, {})
    lines = [_input_line(line) for line in saved.get("lines", [])]
    if row is not None and row >= len(lines):
        raise Http404
    deleting = request.method == "POST" and request.POST.get("action") == "delete"
    initial = {**(lines[row] if row is not None else {}), "revision": revision.pk}
    form = (RevisionForm(request.POST) if deleting else ObservationForm(request.POST or None, count=count, initial=initial))
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        if deleting:
            if row is None:
                raise Http404
            del lines[row]
        else:
            entry = {**data, "item": data["item"].pk, "layer": data["layer"].pk if data["layer"] else None}
            if row is None:
                lines.append(entry)
            else:
                lines[row] = entry
        try:
            save_location(user=request.user, count_id=pk, expected_revision=data["revision"], location_key=location_key,
                counted_at=datetime.fromisoformat(saved["counted_at"]) if saved else timezone.now(),
                evidence=saved.get("evidence", ""), lines=lines, confirmed=False)
            return redirect("puskesmas:opname_location", pk=pk, location_key=location_key)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "puskesmas/opname_form.html", {"title": f"Rincian hitung · {location['name']}",
        "form": form, "count": count, "location": location})


@login_required
def count_case(request, pk, case_key):
    count = get_object_or_404(visible_counts(request.user), pk=pk)
    if not (operator(request.user, count.facility_id) or authority(request.user, count.facility_id, "review_count")):
        raise PermissionDenied
    revision = current_revision(count)
    form = CaseEvidenceForm(request.POST or None, initial={"revision": revision.pk, "case_key": case_key})
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["case_key"] != case_key:
            raise PermissionDenied
        try:
            add_case_evidence(user=request.user, count_id=pk, expected_revision=form.cleaned_data["revision"],
                              case_key=case_key, evidence=form.cleaned_data["evidence"])
            return redirect("puskesmas:opname_detail", pk=pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "puskesmas/opname_form.html", {"title": "Bukti selisih", "form": form, "count": count})


@login_required
def count_action(request, pk, receipt_id=None):
    count = get_object_or_404(visible_counts(request.user), pk=pk)
    if not operator(request.user, count.facility_id):
        raise PermissionDenied
    revision = current_revision(count)
    receipt = None
    if receipt_id is not None:
        receipt = get_object_or_404(PuskesmasReceiptConfirmation.objects.filter(
            facility_id=count.facility_id, inventory_posting__isnull=False,
            received_date__year=count.cutoff.year, received_date__month=count.cutoff.month,
        ), pk=receipt_id)
    form = ActionForm(request.POST or None, count=count, comparison=compare_revision(count, revision), revision=revision,
                      receipt=receipt, initial={"key": uuid.uuid4(), "revision": revision.pk})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            request_action(user=request.user, count_id=pk, expected_revision=data["revision"], key=data["key"],
                kind=data["kind"], reason=data["reason"], reference=data["reference"], expected_change=data["expected_change"],
                case_key=data["case_key"], layer_id=data["layer"].pk if data["layer"] else None,
                quantity=data["quantity"], incident_date=data["incident_date"], reverse_id=data["reverse_id"],
                add_location_id=data["add_location"].pk if data["add_location"] else None)
            return redirect("puskesmas:opname_detail", pk=pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    title = "Ajukan koreksi penerimaan diposting" if receipt else "Ajukan tindakan rekonsiliasi"
    return render(request, "puskesmas/opname_form.html", {
        "title": title, "form": form, "count": count, "receipt": receipt,
    })


@login_required
def count_decide(request, pk, action_id):
    count = get_object_or_404(visible_counts(request.user), pk=pk)
    action = get_object_or_404(count.actions.select_related("preparer", "revision"), pk=action_id)
    if not authority(request.user, count.facility_id, APPROVAL[action.kind]) or action.preparer_id == request.user.pk:
        raise PermissionDenied
    form = DecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            decide_action(user=request.user, count_id=pk, action_id=action_id, **form.cleaned_data)
            return redirect("puskesmas:opname_detail", pk=pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, "puskesmas/opname_form.html", {"title": action.get_kind_display(), "form": form,
        "count": count, "action": action})


@login_required
def count_print(request, pk, number):
    count = get_object_or_404(visible_counts(request.user).select_related("facility"), pk=pk)
    revision = get_object_or_404(count.revisions.exclude(state=OpnameRevision.State.COUNTING), number=number)
    return render(request, "puskesmas/opname_print.html", {"count": count, "revision": revision,
        "comparison": revision.comparison, "locations": [
            (location, revision.observations.get(location["key"], {})) for location in revision_roster(count, revision)]})
