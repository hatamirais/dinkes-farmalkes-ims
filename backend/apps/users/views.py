from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .access import ROLE_DEFAULT_SCOPES, get_user_module_scope, has_module_scope
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
    rows = []
    for module_code, module_label in ModuleAccess.Module.choices:
        if not module_code:
            continue
        scope_value = get_user_module_scope(user_obj, module_code)
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
            "role", "is_active", "last_login", "facility",
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
