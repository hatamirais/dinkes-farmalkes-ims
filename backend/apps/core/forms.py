from django import forms
from django.contrib.auth.forms import AuthenticationForm

from crispy_forms.helper import FormHelper
from crispy_forms.bootstrap import FieldWithButtons, StrictButton
from crispy_forms.layout import Field, Layout

from .models import SystemSettings
from .upload_validation import validate_image_upload


REQUIRED_NUMBERING_TOKENS = ("{seq}", "{year}")
LOGO_MAX_SIZE_BYTES = 2 * 1024 * 1024


class CrispyAuthenticationForm(AuthenticationForm):
    """AuthenticationForm rendered through crispy-forms on the login page."""

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.fields["username"].label = "Nama Pengguna"
        self.fields["username"].widget.attrs.update(
            {
                "autocomplete": "off",
                "autofocus": True,
                "class": "form-control form-control-lg",
                "placeholder": "Masukkan username",
            }
        )
        self.fields["password"].label = "Kata Sandi"
        self.fields["password"].help_text = (
            "Minimal 10 karakter sesuai kebijakan sistem"
        )
        self.fields["password"].widget.attrs.update(
            {
                "autocomplete": "current-password",
                "class": "form-control form-control-lg",
                "placeholder": "Masukkan kata sandi",
            }
        )

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.layout = Layout(
            Field("username", wrapper_class="auth-field-group"),
            FieldWithButtons(
                Field("password"),
                StrictButton(
                    '<i class="bi bi-eye" aria-hidden="true"></i><span class="visually-hidden">Tampilkan kata sandi</span>',
                    css_id="passwordToggle",
                    css_class="btn-outline-secondary auth-password-toggle",
                    type="button",
                    aria_label="Tampilkan kata sandi",
                    aria_pressed="false",
                    data_password_toggle="id_password",
                ),
                input_size="input-group-lg",
                css_class="auth-password-group flex-nowrap",
            ),
        )


class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'platform_label',
            'facility_name',
            'facility_address',
            'facility_phone',
            'header_title',
            'lplpo_distribution_number_template',
            'special_request_distribution_number_template',
            'logo'
        ]
        labels = {
            'lplpo_distribution_number_template': 'Template nomor distribusi LPLPO',
            'special_request_distribution_number_template': 'Template nomor Permintaan Khusus',
        }
        widgets = {
            'facility_address': forms.Textarea(attrs={'rows': 3}),
            'lplpo_distribution_number_template': forms.TextInput(attrs={'class': 'form-control font-monospace'}),
            'special_request_distribution_number_template': forms.TextInput(attrs={'class': 'form-control font-monospace'}),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo is not None and logo is not False and not hasattr(logo, "read"):
            raise forms.ValidationError("Logo harus berupa file gambar, bukan URL.")
        if logo and hasattr(logo, "read") and not hasattr(logo, "url"):
            self.cleaned_logo_mime_type = validate_image_upload(
                logo,
                max_size_bytes=LOGO_MAX_SIZE_BYTES,
                field_label="Logo",
                allowed_extensions={"png", "jpg", "jpeg", "webp"},
                allowed_formats={"PNG", "JPEG", "WEBP"},
            )
        return logo

    def clean_lplpo_distribution_number_template(self):
        return self._clean_numbering_template(
            'lplpo_distribution_number_template',
            'Template nomor LPLPO',
        )

    def clean_special_request_distribution_number_template(self):
        return self._clean_numbering_template(
            'special_request_distribution_number_template',
            'Template nomor Permintaan Khusus',
        )

    def _clean_numbering_template(self, field_name, label):
        value = (self.cleaned_data.get(field_name) or '').strip()
        if not value:
            raise forms.ValidationError(f'{label} wajib diisi.')

        missing_tokens = [token for token in REQUIRED_NUMBERING_TOKENS if token not in value]
        if missing_tokens:
            raise forms.ValidationError(
                f"{label} harus memuat placeholder {' dan '.join(missing_tokens)}."
            )

        for token in REQUIRED_NUMBERING_TOKENS:
            if value.count(token) != 1:
                raise forms.ValidationError(
                    f'{label} hanya boleh memakai placeholder {token} satu kali.'
                )

        normalized = value
        for token in REQUIRED_NUMBERING_TOKENS:
            normalized = normalized.replace(token, '')
        if '{' in normalized or '}' in normalized:
            raise forms.ValidationError(
                f'{label} hanya mendukung placeholder {{seq}} dan {{year}}.'
            )

        return value
