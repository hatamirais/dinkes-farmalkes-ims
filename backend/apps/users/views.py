import csv

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.db.models import Q
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .access import ROLE_DEFAULT_SCOPES, has_module_permission
from .forms import UserCreateForm, UserUpdateForm
from .models import ModuleAccess, User


def _role_defaults_json():
    """Return role default scopes in a shape safe for json_script."""
    return {
        role: {module: scope for module, scope in modules.items()}
        for role, modules in ROLE_DEFAULT_SCOPES.items()
    }


def _has_user_access(user, perm):
    return user.is_superuser or user.has_perm(perm) or has_module_permission(user, perm)


def _can_view_users(user):
    return _has_user_access(user, "users.view_user")


def _can_add_users(user):
    return _has_user_access(user, "users.add_user")


def _can_change_users(user):
    return _has_user_access(user, "users.change_user")


def _can_delete_users(user):
    return _has_user_access(user, "users.delete_user")


def _can_manage_user_scopes(user):
    return user.is_superuser or has_module_permission(user, "users.change_user")


def _protected_user_account_q():
    return Q(is_superuser=True) | Q(role=User.Role.ADMIN)


def _is_protected_user_account(user_obj):
    return User.objects.filter(pk=user_obj.pk).filter(_protected_user_account_q()).exists()


def _require_user_access(user, perm, message):
    if not _has_user_access(user, perm):
        raise PermissionDenied(message)


def _forbidden_protected_user_mutation(request, is_ajax=False):
    message = "Akun admin hanya dapat dikelola oleh superuser."
    if is_ajax:
        return JsonResponse({"success": False, "error": message}, status=403)
    raise PermissionDenied(message)


def _ensure_can_mutate_target_user(request, target_user, is_ajax=False):
    if request.user.is_superuser:
        return None
    if _is_protected_user_account(target_user):
        return _forbidden_protected_user_mutation(request, is_ajax=is_ajax)
    return None


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
    _require_user_access(
        request.user,
        "users.view_user",
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
            "can_add_user": _can_add_users(request.user),
            "can_change_user": _can_change_users(request.user),
            "can_delete_user": _can_delete_users(request.user),
        },
    )


@login_required
def user_create(request):
    _require_user_access(
        request.user,
        "users.add_user",
        "Anda tidak memiliki izin untuk menambah user.",
    )
    can_manage_user_scopes = _can_manage_user_scopes(request.user)

    if request.method == "POST":
        form = UserCreateForm(
            request.POST,
            can_manage_module_scopes=can_manage_user_scopes,
        )
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User {user.username} berhasil ditambahkan.")
            return redirect("users:user_list")
    else:
        form = UserCreateForm(can_manage_module_scopes=can_manage_user_scopes)

    return render(
        request,
        "users/user_form.html",
        {
            "form": form,
            "title": "Tambah User",
            "role_defaults_json": _role_defaults_json(),
            "can_manage_user_scopes": can_manage_user_scopes,
        },
    )


@login_required
def user_update(request, pk):
    _require_user_access(
        request.user,
        "users.change_user",
        "Anda tidak memiliki izin untuk mengubah user.",
    )
    can_manage_user_scopes = _can_manage_user_scopes(request.user)

    target_user = get_object_or_404(User, pk=pk)
    protected_response = _ensure_can_mutate_target_user(request, target_user)
    if protected_response:
        return protected_response

    if request.method == "POST":
        form = UserUpdateForm(
            request.POST,
            instance=target_user,
            can_manage_module_scopes=can_manage_user_scopes,
        )
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User {user.username} berhasil diperbarui.")
            return redirect("users:user_list")
    else:
        form = UserUpdateForm(
            instance=target_user,
            can_manage_module_scopes=can_manage_user_scopes,
        )

    return render(
        request,
        "users/user_form.html",
        {
            "form": form,
            "title": f"Edit User {target_user.username}",
            "target_user": target_user,
            "effective_scopes": _effective_scope_rows(target_user),
            "role_defaults_json": _role_defaults_json(),
            "can_manage_user_scopes": can_manage_user_scopes,
        },
    )


@login_required
def user_toggle_active(request, pk):
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not _can_change_users(request.user):
        if is_ajax:
            return JsonResponse(
                {"success": False, "error": "Tidak memiliki izin."}, status=403
            )
        raise PermissionDenied("Anda tidak memiliki izin untuk mengubah status user.")

    target_user = get_object_or_404(User, pk=pk)
    protected_response = _ensure_can_mutate_target_user(
        request, target_user, is_ajax=is_ajax
    )
    if protected_response:
        return protected_response
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
    _require_user_access(
        request.user,
        "users.delete_user",
        "Anda tidak memiliki izin untuk menghapus user.",
    )

    target_user = get_object_or_404(User, pk=pk)
    protected_response = _ensure_can_mutate_target_user(request, target_user)
    if protected_response:
        return protected_response
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
    _require_user_access(
        request.user,
        "users.view_user",
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
            "can_manage_users": _can_change_users(request.user),
        },
    )


@login_required
def user_bulk_action(request):
    if request.method != "POST":
        return redirect("users:user_list")

    action = request.POST.get("action", "")
    required_perm = "users.delete_user" if action == "delete" else "users.change_user"
    _require_user_access(
        request.user,
        required_perm,
        "Anda tidak memiliki izin untuk aksi massal.",
    )
    pks = request.POST.getlist("selected_users", [])

    if not pks:
        messages.error(request, "Tidak ada pengguna yang dipilih.")
        return redirect("users:user_list")

    queryset = User.objects.filter(pk__in=pks)
    protected_accounts = queryset.filter(_protected_user_account_q())
    protected_count = 0
    if not request.user.is_superuser:
        protected_count = protected_accounts.count()
        queryset = queryset.exclude(pk__in=protected_accounts.values("pk"))
    count = queryset.count()

    if action == "activate":
        queryset.update(is_active=True)
        message = f"{count} pengguna berhasil diaktifkan."
        if protected_count:
            message = (
                f"{message} {protected_count} akun admin dilewati karena hanya "
                "dapat dikelola oleh superuser."
            )
            messages.warning(request, message)
        else:
            messages.success(request, message)
    elif action == "deactivate":
        updated = queryset.exclude(pk=request.user.pk).update(is_active=False)
        if updated < count:
            message = (
                f"{updated} dari {count} pengguna dinonaktifkan. "
                f"Akun Anda sendiri tidak dapat dinonaktifkan."
            )
            if protected_count:
                message = (
                    f"{message} {protected_count} akun admin dilewati karena "
                    "hanya dapat dikelola oleh superuser."
                )
            messages.warning(request, message)
        else:
            message = f"{updated} pengguna berhasil dinonaktifkan."
            if protected_count:
                message = (
                    f"{message} {protected_count} akun admin dilewati karena "
                    "hanya dapat dikelola oleh superuser."
                )
                messages.warning(request, message)
            else:
                messages.success(request, message)
    elif action == "delete":
        inactive = queryset.filter(is_active=False)
        active_count = queryset.filter(is_active=True).count()
        deleted_count = 0
        related_protected_count = 0
        for user_obj in inactive:
            try:
                user_obj.delete()
                deleted_count += 1
            except ProtectedError:
                related_protected_count += 1
        if active_count or related_protected_count or protected_count:
            message_parts = [f"{deleted_count} pengguna dihapus."]
            if active_count:
                message_parts.append(
                    f"{active_count} pengguna aktif tidak dapat dihapus."
                )
            if related_protected_count:
                message_parts.append(
                    f"{related_protected_count} pengguna memiliki data terkait dan tidak dapat dihapus."
                )
            if protected_count:
                message_parts.append(
                    f"{protected_count} akun admin dilewati karena hanya dapat dikelola oleh superuser."
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
    _require_user_access(
        request.user,
        "users.change_user",
        "Anda tidak memiliki izin untuk mereset password user.",
    )

    target_user = get_object_or_404(User, pk=pk)
    protected_response = _ensure_can_mutate_target_user(request, target_user)
    if protected_response:
        return protected_response
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
    _require_user_access(
        request.user,
        "users.view_user",
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
