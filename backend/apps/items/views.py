import logging
from urllib.parse import urlsplit, urlunsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from apps.core.decorators import perm_required
from apps.core.rate_limits import item_mutation_ratelimit
from .exports import export_items_excel
from .forms import (
    CategoryForm,
    ItemForm,
    ProgramForm,
    TherapeuticClassForm,
    UnitForm,
)
from .models import (
    Category,
    Facility,
    Item,
    Program,
    TherapeuticClass,
    Unit,
)

logger = logging.getLogger(__name__)


def _get_safe_next_path(request):
    next_url = request.POST.get("next") or request.GET.get("next")
    if not next_url:
        return ""

    if not url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return ""

    parsed_next = urlsplit(next_url)
    if not parsed_next.path.startswith("/"):
        return ""
    if parsed_next.path.startswith("//"):
        return ""

    return urlunsplit(("", "", parsed_next.path, parsed_next.query, ""))


def _redirect_next_or_default(request, fallback_url_name):
    next_path = _get_safe_next_path(request)
    if next_path:
        return redirect(next_path)
    return redirect(fallback_url_name)


def _json_form_errors(form):
    errors = []
    for field_errors in form.errors.values():
        errors.extend(field_errors)
    return " ".join(errors) or "Data tidak valid."


def _get_default_program():
    return (
        Program.objects.filter(code__iexact="DEFAULT").first()
        or Program.objects.filter(name__iexact="DEFAULT").first()
        or None
    )


def _get_filtered_items(request):
    queryset = (
        Item.objects.select_related("satuan", "kategori", "program")
        .prefetch_related("therapeutic_classes")
        .filter(is_active=True)
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(kode_barang__icontains=search)
            | Q(nama_barang__icontains=search)
            | Q(program__name__icontains=search)
            | Q(program__code__icontains=search)
            | Q(therapeutic_classes__name__icontains=search)
            | Q(therapeutic_classes__code__icontains=search)
        )

    kategori = request.GET.get("kategori", "")
    if kategori:
        queryset = queryset.filter(kategori_id=kategori)

    program = request.GET.get("program", "")
    if program == "1":
        queryset = queryset.filter(is_program_item=True)
    elif program == "0":
        queryset = queryset.filter(is_program_item=False)

    essential = request.GET.get("essential", "")
    if essential == "1":
        queryset = queryset.filter(is_essential=True)
    elif essential == "0":
        queryset = queryset.filter(is_essential=False)

    therapeutic_class = request.GET.get("therapeutic_class", "")
    if therapeutic_class:
        queryset = queryset.filter(therapeutic_classes__id=therapeutic_class)

    return queryset.distinct().order_by("kode_barang"), {
        "search": search,
        "kategori": kategori,
        "program": program,
        "essential": essential,
        "therapeutic_class": therapeutic_class,
    }


@login_required
@perm_required("items.view_item")
def item_list(request):
    queryset, filters = _get_filtered_items(request)
    kategori = filters["kategori"]
    program = filters["program"]
    essential = filters["essential"]
    therapeutic_class = filters["therapeutic_class"]

    paginator = Paginator(queryset, 25)
    page = request.GET.get("page")
    items = paginator.get_page(page)

    categories = [
        {
            "id": cat.id,
            "name": cat.name,
            "selected": "selected" if kategori == str(cat.id) else "",
        }
        for cat in Category.objects.order_by("sort_order", "name")
    ]
    therapeutic_classes = [
        {
            "id": tc.id,
            "name": tc.name,
            "selected": "selected" if therapeutic_class == str(tc.id) else "",
        }
        for tc in TherapeuticClass.objects.filter(is_active=True).order_by("name")
    ]

    return render(
        request,
        "items/item_list.html",
        {
            "items": items,
            "categories": categories,
            "therapeutic_classes": therapeutic_classes,
            "search": filters["search"],
            "selected_kategori": kategori or "",
            "selected_program": program or "",
            "selected_essential": essential or "",
            "selected_therapeutic_class": therapeutic_class or "",
            "program_1_selected": "selected" if program == "1" else "",
            "program_0_selected": "selected" if program == "0" else "",
            "essential_1_selected": "selected" if essential == "1" else "",
            "essential_0_selected": "selected" if essential == "0" else "",
            "default_program": _get_default_program(),
        },
    )


@login_required
@perm_required("items.view_item")
@require_GET
def item_export(request):
    queryset, _filters = _get_filtered_items(request)
    return export_items_excel(queryset, default_program=_get_default_program())


@login_required
@perm_required("items.add_item")
@item_mutation_ratelimit
def item_create(request):
    if request.method == "POST":
        form = ItemForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                item = form.save()
            logger.info(
                "Created item",
                extra={"item_id": item.pk, "user_id": request.user.pk},
            )
            messages.success(request, "Barang berhasil ditambahkan.")
            return redirect("items:item_list")
    else:
        form = ItemForm()

    return render(
        request, "items/item_form.html", {"form": form, "title": "Tambah Barang"}
    )


@login_required
@perm_required("items.change_item")
@item_mutation_ratelimit
def item_update(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.method == "POST":
        form = ItemForm(request.POST, instance=item)
        if form.is_valid():
            with transaction.atomic():
                item = form.save()
            logger.info(
                "Updated item",
                extra={"item_id": item.pk, "user_id": request.user.pk},
            )
            messages.success(request, "Barang berhasil diperbarui.")
            return redirect("items:item_list")
    else:
        form = ItemForm(instance=item)

    return render(
        request,
        "items/item_form.html",
        {"form": form, "title": "Edit Barang", "item": item},
    )


@login_required
@perm_required("items.delete_item")
@item_mutation_ratelimit
def item_delete(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.method == "POST":
        item.is_active = False
        item.save(update_fields=["is_active", "updated_at"])
        logger.info(
            "Soft deleted item",
            extra={"item_id": item.pk, "user_id": request.user.pk},
        )
        messages.success(request, f'Barang "{item.nama_barang}" berhasil dihapus.')
        return redirect("items:item_list")
    return render(request, "items/item_confirm_delete.html", {"item": item})


@login_required
@perm_required("items.add_unit")
@item_mutation_ratelimit
def unit_create(request):
    next_url = _get_safe_next_path(request)
    if request.method == "POST":
        form = UnitForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Satuan berhasil ditambahkan.")
            return _redirect_next_or_default(request, "items:item_create")
    else:
        form = UnitForm()

    return render(
        request,
        "items/lookup_form.html",
        {
            "form": form,
            "title": "Tambah Satuan",
            "next_url": next_url,
        },
    )


@login_required
@perm_required("items.add_category")
@item_mutation_ratelimit
def category_create(request):
    next_url = _get_safe_next_path(request)
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Kategori berhasil ditambahkan.")
            return _redirect_next_or_default(request, "items:item_create")
    else:
        form = CategoryForm()

    return render(
        request,
        "items/lookup_form.html",
        {
            "form": form,
            "title": "Tambah Kategori",
            "next_url": next_url,
        },
    )


@login_required
@perm_required("items.add_program")
@item_mutation_ratelimit
def program_create(request):
    next_url = _get_safe_next_path(request)
    if request.method == "POST":
        form = ProgramForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Program berhasil ditambahkan.")
            return _redirect_next_or_default(request, "items:item_create")
    else:
        form = ProgramForm()

    return render(
        request,
        "items/lookup_form.html",
        {
            "form": form,
            "title": "Tambah Program",
            "next_url": next_url,
        },
    )


@login_required
@perm_required("items.add_therapeuticclass")
@item_mutation_ratelimit
def therapeutic_class_create(request):
    next_url = _get_safe_next_path(request)
    if request.method == "POST":
        form = TherapeuticClassForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Terapi obat berhasil ditambahkan.")
            return _redirect_next_or_default(request, "items:item_create")
    else:
        form = TherapeuticClassForm()

    return render(
        request,
        "items/lookup_form.html",
        {
            "form": form,
            "title": "Tambah Terapi Obat",
            "next_url": next_url,
        },
    )


# -- AJAX Quick-Create Views -------------------------------------------------


@login_required
@perm_required("items.add_unit")
@item_mutation_ratelimit
@require_POST
def quick_create_unit(request):
    code = request.POST.get("code", "")
    name = request.POST.get("name", "")
    description = request.POST.get("description", "")

    form = UnitForm({"code": code, "name": name, "description": description})
    if not form.is_valid():
        return JsonResponse({"error": _json_form_errors(form)}, status=400)

    unit = form.save()
    return JsonResponse({"id": unit.pk, "text": unit.name})


@login_required
@perm_required("items.add_category")
@item_mutation_ratelimit
@require_POST
def quick_create_category(request):
    code = request.POST.get("code", "")
    name = request.POST.get("name", "")
    sort_order = request.POST.get("sort_order", "0")

    form = CategoryForm({"code": code, "name": name, "sort_order": sort_order})
    if not form.is_valid():
        return JsonResponse({"error": _json_form_errors(form)}, status=400)

    category = form.save()
    return JsonResponse({"id": category.pk, "text": category.name})


@login_required
@perm_required("items.add_program")
@item_mutation_ratelimit
@require_POST
def quick_create_program(request):
    code = request.POST.get("code", "")
    name = request.POST.get("name", "")
    description = request.POST.get("description", "")

    form = ProgramForm(
        {
            "code": code,
            "name": name,
            "description": description,
            "is_active": True,
        }
    )
    if not form.is_valid():
        return JsonResponse({"error": _json_form_errors(form)}, status=400)

    program = form.save()
    return JsonResponse({"id": program.pk, "text": program.name})


@login_required
@perm_required("items.add_therapeuticclass")
@item_mutation_ratelimit
@require_POST
def quick_create_therapeutic_class(request):
    code = request.POST.get("code", "")
    name = request.POST.get("name", "")
    description = request.POST.get("description", "")

    form = TherapeuticClassForm(
        {
            "code": code,
            "name": name,
            "description": description,
            "is_active": True,
        }
    )
    if not form.is_valid():
        return JsonResponse({"error": _json_form_errors(form)}, status=400)

    therapeutic_class = form.save()
    return JsonResponse({"id": therapeutic_class.pk, "text": therapeutic_class.name})


@login_required
@perm_required("items.add_facility")
@item_mutation_ratelimit
@require_POST
def quick_create_facility(request):
    code = request.POST.get("code", "").strip().upper()
    name = request.POST.get("name", "").strip()
    address = request.POST.get("address", "").strip()
    phone = request.POST.get("phone", "").strip()
    facility_type = (
        request.POST.get("facility_type", "").strip() or Facility.FacilityType.PUSKESMAS
    )

    if not code or not name:
        return JsonResponse({"error": "Kode dan Nama wajib diisi."}, status=400)
    if Facility.objects.filter(code=code).exists():
        return JsonResponse(
            {"error": f'Fasilitas dengan kode "{code}" sudah ada.'}, status=400
        )
    valid_types = {choice[0] for choice in Facility.FacilityType.choices}
    if facility_type not in valid_types:
        return JsonResponse({"error": "Tipe fasilitas tidak valid."}, status=400)

    facility = Facility.objects.create(
        code=code,
        name=name,
        address=address,
        phone=phone,
        facility_type=facility_type,
    )
    return JsonResponse({"id": facility.pk, "text": str(facility)})
