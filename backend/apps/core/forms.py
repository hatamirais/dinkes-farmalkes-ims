from django import forms
from django.contrib.auth.forms import AuthenticationForm

from crispy_forms.helper import FormHelper
from crispy_forms.bootstrap import FieldWithButtons, StrictButton
from crispy_forms.layout import Field, HTML, Layout

from .models import DocumentNumberRule, SystemSettings
from .upload_validation import validate_image_upload


LOGO_MAX_SIZE_BYTES = 2 * 1024 * 1024


class CrispyAuthenticationForm(AuthenticationForm):
    """AuthenticationForm rendered through crispy-forms on the login page."""

    error_messages = {
        "invalid_login": "Invalid username or password",
        "inactive": "Invalid username or password",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.fields["username"].label = "Nama Pengguna"
        self.fields["username"].widget.attrs.update(
            {
                "autocomplete": "username",
                "autofocus": True,
                "class": "form-control form-control-lg",
                "id": "id_username",
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
                "id": "id_password",
                "placeholder": "Masukkan kata sandi",
            }
        )

        if self.is_bound and self.non_field_errors():
            for field_name, feedback_id in (
                ("username", "id_username_invalid_feedback"),
                ("password", "id_password_invalid_feedback"),
            ):
                field = self.fields[field_name]
                css_classes = field.widget.attrs.get("class", "")
                if "is-invalid" not in css_classes:
                    field.widget.attrs["class"] = f"{css_classes} is-invalid".strip()
                field.widget.attrs["aria-invalid"] = "true"
                field.widget.attrs["aria-describedby"] = feedback_id

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.disable_csrf = True
        self.helper.form_show_errors = False
        self.helper.layout = Layout(
            Field("username", wrapper_class="auth-field-group"),
            HTML(
                "{% if form.non_field_errors %}"
                '<div id="id_username_invalid_feedback" class="invalid-feedback d-block">'
                "Invalid username or password"
                "</div>"
                "{% endif %}"
            ),
            FieldWithButtons(
                Field("password"),
                StrictButton(
                    '<i class="bi bi-eye" aria-hidden="true"></i><span class="visually-hidden">Tampilkan kata sandi</span>',
                    css_id="passwordToggle",
                    css_class="btn-outline-secondary auth-password-toggle",
                    type="button",
                    **{
                        "aria-label": "Tampilkan kata sandi",
                        "aria-pressed": "false",
                        "data-password-toggle": "id_password",
                    },
                ),
                input_size="input-group-lg",
                css_class="auth-password-group flex-nowrap",
            ),
            HTML(
                "{% if form.non_field_errors %}"
                '<div id="id_password_invalid_feedback" class="invalid-feedback d-block">'
                "Invalid username or password"
                "</div>"
                "{% endif %}"
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
            'logo'
        ]
        widgets = {
            'facility_address': forms.Textarea(attrs={'rows': 3}),
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



class DocumentNumberRuleForm(forms.ModelForm):
    class Meta:
        model = DocumentNumberRule
        fields = ["template", "reset_period", "padding"]
        labels = {
            "template": "Template",
            "reset_period": "Reset urutan",
            "padding": "Minimum digit urutan",
        }
        widgets = {
            "template": forms.TextInput(
                attrs={"class": "form-control font-monospace", "autocomplete": "off"}
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        # Model formsets add a hidden ``id`` ModelChoiceField. Copy only the
        # explicitly editable model fields so the instance primary key cannot
        # be replaced by a model object during validation.
        for field_name in self._meta.fields:
            if field_name in cleaned_data:
                setattr(self.instance, field_name, cleaned_data[field_name])
        try:
            self.instance.clean()
        except forms.ValidationError as exc:
            self.add_error(None, exc)
        return cleaned_data


DocumentNumberRuleFormSet = forms.modelformset_factory(
    DocumentNumberRule,
    form=DocumentNumberRuleForm,
    extra=0,
    can_delete=False,
)
