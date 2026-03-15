from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from .access import get_user_module_scope, has_module_scope
from .forms import UserCreateForm, UserUpdateForm
from .models import ModuleAccess, User


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

    queryset = User.objects.order_by("-date_joined")

    search = request.GET.get("q", "").strip()
    if search:
        queryset = (
            queryset.filter(username__icontains=search)
            | queryset.filter(full_name__icontains=search)
            | queryset.filter(email__icontains=search)
        )

    role = request.GET.get("role", "")
    if role:
        queryset = queryset.filter(role=role)

    active = request.GET.get("active", "")
    if active == "1":
        queryset = queryset.filter(is_active=True)
    elif active == "0":
        queryset = queryset.filter(is_active=False)

    paginator = Paginator(queryset, 25)
    users = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "users/user_list.html",
        {
            "users": users,
            "search": search,
            "selected_role": role,
            "selected_active": active,
            "role_choices": User.Role.choices,
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
        },
    )


@login_required
def user_toggle_active(request, pk):
    if not _can_manage_users(request.user):
        return _forbidden_manage_user(
            request,
            "Anda tidak memiliki izin untuk mengubah status user.",
        )

    target_user = get_object_or_404(User, pk=pk)
    if request.method != "POST":
        return redirect("users:user_list")

    if target_user == request.user and target_user.is_active:
        messages.error(request, "Anda tidak dapat menonaktifkan akun Anda sendiri.")
        return redirect("users:user_list")

    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=["is_active"])

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
    target_user.delete()
    messages.success(request, f"User {username} berhasil dihapus.")
    return redirect("users:user_list")
