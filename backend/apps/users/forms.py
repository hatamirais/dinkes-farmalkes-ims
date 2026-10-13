import unicodedata

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q

from .access import (
    DELEGATE_ROLES,
    can_delegate_module,
    default_scope_for_role,
    has_module_scope,
)
from .models import (
    APPROVAL_MODULE_CHOICES,
    AuthorityDelegation,
    ModuleAccess,
    User,
)

# ADMIN role can only be created via CLI (createsuperuser / management command)
UI_ROLE_CHOICES = [
    (value, label) for value, label in User.Role.choices if value != User.Role.ADMIN
]

FACILITY_HELP_TEXT = "Wajib dipilih untuk Operator Puskesmas."


def _clean_normalized_text(value, *, field_label):
    value = unicodedata.normalize("NFC", (value or "").strip())
    if "\x00" in value:
        raise forms.ValidationError(f"{field_label} tidak boleh mengandung null byte.")
    return value


def _configure_user_form_fields(form):
    form.fields["facility"].help_text = FACILITY_HELP_TEXT
    form.fields["facility"].queryset = form.fields["facility"].queryset.filter(
        is_active=True
    )


def _clean_role_and_facility(form):
    cleaned_data = form.cleaned_data
    role = cleaned_data.get("role")
    facility = cleaned_data.get("facility")

    if role == User.Role.PUSKESMAS and not facility:
        form.add_error("facility", "Fasilitas wajib dipilih untuk Operator Puskesmas.")

    if role != User.Role.PUSKESMAS:
        cleaned_data["facility"] = None

    return cleaned_data


def _save_role_default_module_scopes(user, role):
    for module_code, _ in ModuleAccess.Module.choices:
        ModuleAccess.objects.update_or_create(
            user=user,
            module=module_code,
            defaults={"scope": default_scope_for_role(role, module_code)},
        )


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
        fields = ["username", "full_name", "nip", "email", "role", "facility", "is_active"]
        labels = {
            "role": "Jabatan",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "nip": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.can_manage_module_scopes = kwargs.pop("can_manage_module_scopes", True)
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = UI_ROLE_CHOICES
        _configure_user_form_fields(self)
        if self.can_manage_module_scopes:
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
        return _clean_role_and_facility(self)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            if self.can_manage_module_scopes:
                self._save_module_scopes(user)
            else:
                _save_role_default_module_scopes(user, user.role)
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
        fields = ["username", "full_name", "nip", "email", "role", "facility", "is_active"]
        labels = {
            "role": "Jabatan",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "full_name": forms.TextInput(attrs={"class": "form-control"}),
            "nip": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "facility": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        self.can_manage_module_scopes = kwargs.pop("can_manage_module_scopes", True)
        super().__init__(*args, **kwargs)
        # Only restrict role choices if the user is NOT already an ADMIN.
        # Existing ADMIN users can still be edited, but role cannot be
        # changed TO or FROM ADMIN via the Dashboard.
        if not (
            self.instance and self.instance.pk and self.instance.role == User.Role.ADMIN
        ):
            self.fields["role"].choices = UI_ROLE_CHOICES
        _configure_user_form_fields(self)
        if self.can_manage_module_scopes:
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

    def clean(self):
        super().clean()
        return _clean_role_and_facility(self)

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit and self.can_manage_module_scopes:
            for module_code, _ in ModuleAccess.Module.choices:
                field_name = f"module_scope__{module_code}"
                scope = int(self.cleaned_data.get(field_name, ModuleAccess.Scope.NONE))
                ModuleAccess.objects.update_or_create(
                    user=user,
                    module=module_code,
                    defaults={"scope": scope},
                )
        return user


class AuthorityDelegationCreateForm(forms.Form):
    class DurationMode:
        FIXED = "FIXED"
        UNTIL_REVOKED = "UNTIL_REVOKED"

    delegate = forms.ModelChoiceField(
        label="Pelaksana Harian",
        queryset=User.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    modules = forms.MultipleChoiceField(
        label="Modul yang Didelegasikan",
        choices=APPROVAL_MODULE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    duration_mode = forms.ChoiceField(
        label="Durasi",
        choices=(
            (DurationMode.FIXED, "Sampai waktu tertentu"),
            (DurationMode.UNTIL_REVOKED, "Berlaku sampai dicabut"),
        ),
        initial=DurationMode.FIXED,
        widget=forms.RadioSelect,
    )
    starts_at = forms.DateTimeField(
        label="Mulai Berlaku",
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "class": "form-control",
                "type": "datetime-local",
                "data-datetime-picker": "24h",
                "placeholder": "DD/MM/YYYY HH:mm",
            },
        ),
    )
    ends_at = forms.DateTimeField(
        label="Berakhir",
        required=False,
        help_text=(
            "Wajib untuk durasi tertentu; dikosongkan untuk berlaku sampai dicabut."
        ),
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "class": "form-control",
                "type": "datetime-local",
                "data-datetime-picker": "24h",
                "placeholder": "DD/MM/YYYY HH:mm",
            },
        ),
    )
    reason = forms.CharField(
        label="Alasan / Dasar Penugasan",
        max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        if self.is_bound and self.data.get(self.add_prefix("duration_mode")) == (
            self.DurationMode.UNTIL_REVOKED
        ):
            data = self.data.copy()
            data[self.add_prefix("ends_at")] = ""
            self.data = data
        self.fields["delegate"].queryset = User.objects.filter(
            is_active=True,
            role__in=DELEGATE_ROLES,
        ).order_by("full_name", "username")
        self.fields["modules"].choices = [
            (module, label)
            for module, label in APPROVAL_MODULE_CHOICES
            if can_delegate_module(actor, module)
        ]

    def clean_reason(self):
        return _clean_normalized_text(
            self.cleaned_data.get("reason"),
            field_label="Alasan",
        )

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get("starts_at")
        ends_at = cleaned_data.get("ends_at")
        duration_mode = cleaned_data.get("duration_mode")
        delegate = cleaned_data.get("delegate")
        modules = cleaned_data.get("modules") or []

        if starts_at and not 1000 <= starts_at.year <= 9999:
            self.add_error("starts_at", "Tahun harus berada pada rentang 1000–9999.")

        if duration_mode == self.DurationMode.FIXED:
            if ends_at is None:
                self.add_error(
                    "ends_at",
                    "Waktu berakhir wajib diisi untuk durasi tertentu.",
                )
            elif not 1000 <= ends_at.year <= 9999:
                self.add_error("ends_at", "Tahun harus berada pada rentang 1000–9999.")
            elif starts_at and starts_at >= ends_at:
                self.add_error("ends_at", "Waktu berakhir harus setelah waktu mulai.")
        elif duration_mode == self.DurationMode.UNTIL_REVOKED:
            ends_at = None
            cleaned_data["ends_at"] = None

        for module in modules:
            if not can_delegate_module(self.actor, module):
                self.add_error(
                    "modules",
                    "Anda tidak dapat mendelegasikan salah satu modul yang dipilih.",
                )
                break
            if (
                delegate
                and module
                in {ModuleAccess.Module.PUSKESMAS, ModuleAccess.Module.LPLPO}
                and not delegate.facility_id
            ):
                self.add_error(
                    "delegate",
                    "Pelaksana Harian harus terhubung ke fasilitas untuk delegasi Puskesmas/LPLPO.",
                )
                break
            if delegate and not has_module_scope(
                delegate,
                module,
                ModuleAccess.Scope.VIEW,
            ):
                self.add_error(
                    "modules",
                    f"{delegate} tidak memiliki akses Lihat pada salah satu modul yang dipilih.",
                )
                break

        if starts_at and duration_mode:
            overlapping = AuthorityDelegation.objects.filter(
                authority=AuthorityDelegation.Authority.KEPALA_APPROVAL,
                module__in=modules,
                revoked_at__isnull=True,
            )
            if ends_at is not None:
                overlapping = overlapping.filter(starts_at__lt=ends_at)
            overlapping = overlapping.filter(
                Q(ends_at__isnull=True) | Q(ends_at__gt=starts_at)
            )
            if overlapping.exists():
                labels = ", ".join(
                    sorted({obj.get_module_display() for obj in overlapping})
                )
                self.add_error(
                    "modules",
                    f"Periode bertumpang tindih dengan delegasi pada modul: {labels}.",
                )
        return cleaned_data

    def save(self):
        return [
            AuthorityDelegation.objects.create(
                authority=AuthorityDelegation.Authority.KEPALA_APPROVAL,
                module=module,
                delegate=self.cleaned_data["delegate"],
                starts_at=self.cleaned_data["starts_at"],
                ends_at=self.cleaned_data["ends_at"],
                reason=self.cleaned_data["reason"],
                granted_by=self.actor,
            )
            for module in self.cleaned_data["modules"]
        ]


class AuthorityDelegationRevokeForm(forms.Form):
    revocation_reason = forms.CharField(
        label="Alasan Pencabutan",
        max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def clean_revocation_reason(self):
        return _clean_normalized_text(
            self.cleaned_data.get("revocation_reason"),
            field_label="Alasan pencabutan",
        )
