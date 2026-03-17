from django import forms
from django.contrib.auth.password_validation import validate_password

from .access import default_scope_for_role
from .models import ModuleAccess
from .models import User

# ADMIN role can only be created via CLI (createsuperuser / management command)
UI_ROLE_CHOICES = [
    (value, label) for value, label in User.Role.choices if value != User.Role.ADMIN
]


class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        strip=False,
    )
    password2 = forms.CharField(
        label="Konfirmasi Password",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        strip=False,
    )

    class Meta:
        model = User
        fields = ["username", "full_name", "email", "role", "is_active"]
        labels = {
            "role": "Jabatan",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = UI_ROLE_CHOICES
        self._add_module_scope_fields()

    def _add_module_scope_fields(self):
        role = self.data.get("role") or self.initial.get("role") or User.Role.ADMIN_UMUM
        for module_code, module_label in ModuleAccess.Module.choices:
            field_name = f"module_scope__{module_code}"
            default_scope = default_scope_for_role(role, module_code)
            self.fields[field_name] = forms.ChoiceField(
                label=f"Akses {module_label}",
                choices=ModuleAccess.Scope.choices,
                initial=default_scope,
                required=True,
                widget=forms.Select(attrs={"class": "form-select"}),
            )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Username sudah digunakan.")
        return username

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Email sudah digunakan.")
        return email

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if role == User.Role.ADMIN:
            raise forms.ValidationError(
                "Role Admin hanya dapat dibuat melalui CLI server."
            )
        return role

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1:
            validate_password(password1)
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Konfirmasi password tidak sama.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self._save_module_scopes(user)
        return user

    def _save_module_scopes(self, user):
        for module_code, _ in ModuleAccess.Module.choices:
            field_name = f"module_scope__{module_code}"
            scope = int(self.cleaned_data.get(field_name, ModuleAccess.Scope.NONE))
            ModuleAccess.objects.update_or_create(
                user=user,
                module=module_code,
                defaults={"scope": scope},
            )


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "full_name", "email", "role", "is_active"]
        labels = {
            "role": "Jabatan",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only restrict role choices if the user is NOT already an ADMIN.
        # Existing ADMIN users can still be edited, but role cannot be
        # changed TO or FROM ADMIN via the Dashboard.
        if not (self.instance and self.instance.pk and self.instance.role == User.Role.ADMIN):
            self.fields["role"].choices = UI_ROLE_CHOICES
        self._add_module_scope_fields()

    def _add_module_scope_fields(self):
        role = self.data.get("role") or self.initial.get("role") or self.instance.role
        existing_map = {
            ma.module: ma.scope for ma in self.instance.module_accesses.all()
        }
        for module_code, module_label in ModuleAccess.Module.choices:
            field_name = f"module_scope__{module_code}"
            initial_scope = existing_map.get(
                module_code,
                default_scope_for_role(role, module_code),
            )
            self.fields[field_name] = forms.ChoiceField(
                label=f"Akses {module_label}",
                choices=ModuleAccess.Scope.choices,
                initial=initial_scope,
                required=True,
                widget=forms.Select(attrs={"class": "form-select"}),
            )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        qs = User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Username sudah digunakan.")
        return username

    def clean_role(self):
        role = self.cleaned_data.get("role")
        # Block changing a non-ADMIN user TO ADMIN via Dashboard
        if role == User.Role.ADMIN and (
            not self.instance.pk or self.instance.role != User.Role.ADMIN
        ):
            raise forms.ValidationError(
                "Role Admin hanya dapat dibuat melalui CLI server."
            )
        return role

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        qs = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if email and qs.exists():
            raise forms.ValidationError("Email sudah digunakan.")
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            for module_code, _ in ModuleAccess.Module.choices:
                field_name = f"module_scope__{module_code}"
                scope = int(self.cleaned_data.get(field_name, ModuleAccess.Scope.NONE))
                ModuleAccess.objects.update_or_create(
                    user=user,
                    module=module_code,
                    defaults={"scope": scope},
                )
        return user
