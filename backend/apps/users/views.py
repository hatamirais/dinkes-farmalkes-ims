import csv

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .access import ROLE_DEFAULT_SCOPES, has_module_scope
from .forms import UserCreateForm, UserUpdateForm
from .models import ModuleAccess, User


def _role_defaults_json():
    """Return role default scopes in a shape safe for json_script."""
    return {
        role: {module: scope for module, scope in modules.items()}
        for role, modules in ROLE_DEFAULT_SCOPES.items()
    }


def _can_view_users(user):
    return has_module_scope(user, ModuleAccess.Module.USERS, ModuleAccess.Scope.VIEW)


def _can_manage_users(user):
    return has_module_scope(user, ModuleAccess.Module.USERS, ModuleAccess.Scope.MANAGE)


def _forbidden_manage_user(request, message):
    messages.error(request, message)
    return redirect("dashboard")


def _effective_scope_rows(user_obj):
    scope_labels = {
        ModuleAccess.Scope.NONE: "Tidak Ada",
        ModuleAccess.Scope.VIEW: "Lihat",
        ModuleAccess.Scope.OPERATE: "Operasional",
        ModuleAccess.Scope.APPROVE: "Persetujuan",
        ModuleAccess.Scope.MANAGE: "Kelola",
    }
    module_scopes = {
        access.module: access.scope
        for access in user_obj.module_accesses.all()
    }
    rows = []
    for module_code, module_label in ModuleAccess.Module.choices:
        if not module_code:
            continue
        scope_value = module_scopes.get(
            module_code, ROLE_DEFAULT_SCOPES.get(user_obj.role, {}).get(module_code, 0)
        )
        rows.append(
            {
                "module": module_label,
                "scope_value": scope_value,
                "scope_label": scope_labels.get(
                    ModuleAccess.Scope(scope_value), "Tidak Ada"
                ),
            }
        )
    return rows


@login_required
def user_list(request):
    if not _can_view_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk membuka manajemen user.",
        )

    queryset = User.objects.select_related("facility") \
        .only(
            "id", "username", "full_name", "nip", "email",
            "role", "is_active", "last_login", "facility_id", "facility__name",
        )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = (
            queryset.filter(username__icontains=search)
            | queryset.filter(full_name__icontains=search)
            | queryset.filter(email__icontains=search)
        )

    jabatan = request.GET.get("jabatan", "").strip()
    if not jabatan:
        jabatan = request.GET.get("role", "").strip()
    if jabatan:
        queryset = queryset.filter(role=jabatan)

    active = request.GET.get("active", "1")
    if active == "1":
        queryset = queryset.filter(is_active=True)
    elif active == "0":
        queryset = queryset.filter(is_active=False)

    sort = request.GET.get("sort", "").strip()
    order = request.GET.get("order", "asc").strip()
    allowed_sorts = ["username", "full_name", "role", "is_active", "last_login"]
    sort_icon = {}
    if sort in allowed_sorts:
        direction = "" if order == "asc" else "-"
        queryset = queryset.order_by(f"{direction}{sort}")
        for col in allowed_sorts:
            if col == sort:
                sort_icon[col] = "bi-arrow-down" if order == "asc" else "bi-arrow-up"
            else:
                sort_icon[col] = None
    else:
        queryset = queryset.order_by("-date_joined")

    total_count = queryset.count()
    paginator = Paginator(queryset, 25)
    users = paginator.get_page(request.GET.get("page"))

    filter_params = request.GET.copy()
    if "page" in filter_params:
        del filter_params["page"]

    return render(
        request,
        "users/user_list.html",
        {
            "users": users,
            "total_count": total_count,
            "search": search,
            "selected_jabatan": jabatan,
            "selected_active": active,
            "jabatan_choices": User.Role.choices,
            "sort": sort,
            "order": order,
            "sort_icon": sort_icon,
            "filter_params": filter_params.urlencode(),
            "can_add_user": _can_manage_users(request.user),
            "can_change_user": _can_manage_users(request.user),
            "can_delete_user": _can_manage_users(request.user),
        },
    )


@login_required
def user_create(request):
    if not _can_manage_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk menambah user.",
        )

    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User {user.username} berhasil ditambahkan.")
            return redirect("users:user_list")
    else:
        form = UserCreateForm()

    return render(
        request,
        "users/user_form.html",
        {
            "form": form,
            "title": "Tambah User",
            "role_defaults_json": _role_defaults_json(),
        },
    )


@login_required
def user_update(request, pk):
    if not _can_manage_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk mengubah user.",
        )

    target_user = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = UserUpdateForm(request.POST, instance=target_user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User {user.username} berhasil diperbarui.")
            return redirect("users:user_list")
    else:
        form = UserUpdateForm(instance=target_user)

    return render(
        request,
        "users/user_form.html",
        {
            "form": form,
            "title": f"Edit User {target_user.username}",
            "target_user": target_user,
            "effective_scopes": _effective_scope_rows(target_user),
            "role_defaults_json": _role_defaults_json(),
        },
    )


@login_required
def user_toggle_active(request, pk):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not _can_manage_users(request.user):
        if is_ajax:
            return JsonResponse({"success": False, "error": "Tidak memiliki izin."}, status=403)
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk mengubah status user.",
        )

    target_user = get_object_or_404(User, pk=pk)
    if request.method != "POST":
        if is_ajax:
            return JsonResponse({"success": False, "error": "Metode tidak diizinkan."}, status=405)
        return redirect("users:user_list")

    if target_user == request.user and target_user.is_active:
        if is_ajax:
            return JsonResponse({"success": False, "error": "Tidak dapat menonaktifkan akun sendiri."}, status=400)
        messages.error(request, "Anda tidak dapat menonaktifkan akun Anda sendiri.")
        return redirect("users:user_list")

    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=["is_active"])

    if is_ajax:
        return JsonResponse({
            "success": True,
            "is_active": target_user.is_active,
            "status_text": "Aktif" if target_user.is_active else "Nonaktif",
        })

    if target_user.is_active:
        messages.success(request, f"User {target_user.username} berhasil diaktifkan.")
    else:
        messages.success(
            request, f"User {target_user.username} berhasil dinonaktifkan."
        )

    return redirect("users:user_list")


@login_required
def user_delete(request, pk):
    if not _can_manage_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk menghapus user.",
        )

    target_user = get_object_or_404(User, pk=pk)
    if request.method != "POST":
        return redirect("users:user_list")

    if target_user == request.user:
        messages.error(request, "Anda tidak dapat menghapus akun Anda sendiri.")
        return redirect("users:user_list")

    if target_user.is_active:
        messages.error(
            request, "User aktif tidak dapat dihapus. Nonaktifkan terlebih dahulu."
        )
        return redirect("users:user_list")

    username = target_user.username
    try:
        target_user.delete()
    except ProtectedError:
        messages.error(
            request,
            f"User {username} tidak dapat dihapus karena masih memiliki "
            f"data terkait di sistem (distribusi, penerimaan, dll). "
            f"Nonaktifkan user ini sebagai gantinya.",
        )
        return redirect("users:user_list")
    messages.success(request, f"User {username} berhasil dihapus.")
    return redirect("users:user_list")


@login_required
def user_detail(request, pk):
    if not _can_view_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk membuka detail user.",
        )

    target_user = get_object_or_404(
        User.objects.select_related("facility").prefetch_related("module_accesses"),
        pk=pk,
    )

    return render(
        request,
        "users/user_detail.html",
        {
            "target_user": target_user,
            "effective_scopes": _effective_scope_rows(target_user),
            "can_manage_users": _can_manage_users(request.user),
        },
    )


@login_required
def user_bulk_action(request):
    if not _can_manage_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk aksi massal.",
        )

    if request.method != "POST":
        return redirect("users:user_list")

    action = request.POST.get("action", "")
    pks = request.POST.getlist("selected_users", [])

    if not pks:
        messages.error(request, "Tidak ada pengguna yang dipilih.")
        return redirect("users:user_list")

    queryset = User.objects.filter(pk__in=pks)
    count = queryset.count()

    if action == "activate":
        queryset.update(is_active=True)
        messages.success(request, f"{count} pengguna berhasil diaktifkan.")
    elif action == "deactivate":
        updated = queryset.exclude(pk=request.user.pk).update(is_active=False)
        if updated < count:
            messages.warning(
                request,
                f"{updated} dari {count} pengguna dinonaktifkan. "
                f"Akun Anda sendiri tidak dapat dinonaktifkan.",
            )
        else:
            messages.success(request, f"{updated} pengguna berhasil dinonaktifkan.")
    elif action == "delete":
        inactive = queryset.filter(is_active=False)
        active_count = queryset.filter(is_active=True).count()
        deleted_count = 0
        protected_count = 0
        for user_obj in inactive:
            try:
                user_obj.delete()
                deleted_count += 1
            except ProtectedError:
                protected_count += 1
        if active_count or protected_count:
            message_parts = [f"{deleted_count} pengguna dihapus."]
            if active_count:
                message_parts.append(
                    f"{active_count} pengguna aktif tidak dapat dihapus."
                )
            if protected_count:
                message_parts.append(
                    f"{protected_count} pengguna memiliki data terkait dan tidak dapat dihapus."
                )
            messages.warning(
                request,
                " ".join(message_parts),
            )
        elif deleted_count:
            messages.success(request, f"{deleted_count} pengguna berhasil dihapus.")
        else:
            messages.error(request, "Tidak ada pengguna yang dapat dihapus.")
    else:
        messages.error(request, "Aksi tidak dikenali.")

    return redirect("users:user_list")


@login_required
def user_reset_password(request, pk):
    if not _can_manage_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk mereset password user.",
        )

    target_user = get_object_or_404(User, pk=pk)
    if request.method != "POST":
        return redirect("users:user_list")

    password1 = request.POST.get("password1", "")
    password2 = request.POST.get("password2", "")

    if not password1:
        messages.error(request, "Password baru harus diisi.")
        return redirect("users:user_update", pk=pk)

    if password1 != password2:
        messages.error(request, "Konfirmasi password tidak sama.")
        return redirect("users:user_update", pk=pk)

    try:
        validate_password(password1, target_user)
    except ValidationError as e:
        for err in e.messages:
            messages.error(request, err)
        return redirect("users:user_update", pk=pk)

    target_user.set_password(password1)
    target_user.save(update_fields=["password"])
    if target_user == request.user:
        update_session_auth_hash(request, target_user)
    messages.success(
        request, f"Password untuk {target_user.username} berhasil direset."
    )
    return redirect("users:user_update", pk=pk)


class _Echo:
    """Object that implements just the write method of the file-like interface."""

    def write(self, value):
        return value


def _build_user_export_queryset(request):
    queryset = User.objects.select_related("facility").only(
        "username", "full_name", "nip", "email", "role",
        "is_active", "last_login", "facility",
    )

    search = request.GET.get("q", "").strip()
    if search:
        queryset = (
            queryset.filter(username__icontains=search)
            | queryset.filter(full_name__icontains=search)
            | queryset.filter(email__icontains=search)
        )

    jabatan = request.GET.get("jabatan", "").strip()
    if not jabatan:
        jabatan = request.GET.get("role", "").strip()
    if jabatan:
        queryset = queryset.filter(role=jabatan)

    active = request.GET.get("active", "1")
    if active == "1":
        queryset = queryset.filter(is_active=True)
    elif active == "0":
        queryset = queryset.filter(is_active=False)

    return queryset.order_by("-date_joined")


@login_required
def user_export_csv(request):
    if not _can_view_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk mengekspor data pengguna.",
        )

    queryset = _build_user_export_queryset(request)
    role_map = dict(User.Role.choices)

    def generate_rows():
        writer = csv.writer(_Echo())
        yield "\ufeff"
        yield writer.writerow([
            "Username", "Nama Lengkap", "NIP", "Email",
            "Jabatan", "Fasilitas", "Status", "Login Terakhir",
        ])
        for user in queryset.iterator(chunk_size=200):
            yield writer.writerow([
                user.username,
                user.full_name,
                user.nip,
                user.email,
                role_map.get(user.role, user.role),
                user.facility.name if user.facility else (
                    "Instalasi Farmasi" if user.role != "PUSKESMAS" else ""
                ),
                "Aktif" if user.is_active else "Nonaktif",
                user.last_login.strftime("%Y-%m-%d %H:%M") if user.last_login else "",
            ])

    response = StreamingHttpResponse(
        generate_rows(),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = 'attachment; filename="users_export.csv"'
    return response
