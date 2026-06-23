import unicodedata
from decimal import Decimal, InvalidOperation

from django import forms
from django.db.models import Q

from .models import Category, Item, Program, TherapeuticClass, Unit


def _normalize_text_value(value, field_label, *, max_length=None, allow_blank=True):
    if value is None:
        return "" if allow_blank else value

    raw_value = str(value)
    if "\x00" in raw_value:
        raise forms.ValidationError(f"{field_label} mengandung karakter yang tidak valid.")

    normalized = unicodedata.normalize("NFC", raw_value)
    normalized = " ".join(normalized.strip().split())
    if not normalized and not allow_blank:
        raise forms.ValidationError(f"{field_label} wajib diisi.")
    if max_length is not None and len(normalized) > max_length:
        raise forms.ValidationError(
            f"{field_label} tidak boleh lebih dari {max_length} karakter."
        )
    return normalized


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            "nama_barang",
            "satuan",
            "kategori",
            "is_program_item",
            "is_essential",
            "program",
            "therapeutic_classes",
            "minimum_stock",
            "description",
        ]
        widgets = {
            "nama_barang": forms.TextInput(attrs={"class": "form-control", "maxlength": 255}),
            "satuan": forms.Select(attrs={"class": "form-select"}),
            "kategori": forms.Select(attrs={"class": "form-select"}),
            "is_program_item": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_essential": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "program": forms.Select(attrs={"class": "form-select"}),
            "therapeutic_classes": forms.SelectMultiple(attrs={"class": "form-select"}),
            "minimum_stock": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        self.fields["is_program_item"].label = "Barang program [P]"
        self.fields["is_essential"].label = "Barang esensial [E]"
        self.fields["program"].required = False
        self.fields["therapeutic_classes"].required = False
        self.fields["therapeutic_classes"].label = "Terapi Obat"
        self.fields["therapeutic_classes"].help_text = (
            "Pilih satu atau lebih kelompok terapi obat untuk kebutuhan pelaporan."
        )
        self.fields["satuan"].empty_label = None
        self.fields["kategori"].empty_label = None
        self.fields["program"].empty_label = ""

        instance_class_ids = []
        if self.instance and self.instance.pk:
            instance_class_ids = list(
                self.instance.therapeutic_classes.values_list("pk", flat=True)
            )

        self.fields["program"].queryset = Program.objects.filter(
            Q(is_active=True) | Q(pk=getattr(self.instance, "program_id", None))
        ).order_by("name")
        self.fields["therapeutic_classes"].queryset = TherapeuticClass.objects.filter(
            Q(is_active=True) | Q(pk__in=instance_class_ids)
        ).order_by("name")

        self.fields["satuan"].label_from_instance = lambda obj: obj.name
        self.fields["kategori"].label_from_instance = lambda obj: obj.name
        self.fields["program"].label_from_instance = lambda obj: obj.name
        self.fields["therapeutic_classes"].label_from_instance = lambda obj: obj.name

    def clean_nama_barang(self):
        return _normalize_text_value(
            self.cleaned_data.get("nama_barang"),
            "Nama barang",
            max_length=255,
            allow_blank=False,
        )

    def clean_description(self):
        return _normalize_text_value(
            self.cleaned_data.get("description"),
            "Keterangan",
            allow_blank=True,
        )

    def clean_minimum_stock(self):
        value = self.cleaned_data.get("minimum_stock")
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            decimal_value = value
        else:
            try:
                decimal_value = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise forms.ValidationError("Minimum stok harus berupa angka yang valid.") from exc

        if not decimal_value.is_finite():
            raise forms.ValidationError("Minimum stok harus berupa angka yang valid.")
        if decimal_value < 0:
            raise forms.ValidationError("Minimum stok tidak boleh kurang dari 0.")
        return decimal_value

    def clean(self):
        cleaned_data = super().clean()
        is_program_item = cleaned_data.get("is_program_item")
        program = cleaned_data.get("program")

        if is_program_item and not program:
            self.add_error("program", "Program wajib dipilih untuk barang program.")

        if not is_program_item:
            cleaned_data["program"] = None

        return cleaned_data


class LookupValidationMixin:
    code_field_name = "code"
    name_field_name = "name"
    description_field_name = "description"

    def _normalize_code(self):
        code = self.cleaned_data.get(self.code_field_name)
        code = _normalize_text_value(
            code,
            "Kode",
            max_length=20,
            allow_blank=False,
        )
        return code.upper()

    def _normalize_name(self):
        return _normalize_text_value(
            self.cleaned_data.get(self.name_field_name),
            "Nama",
            max_length=100,
            allow_blank=False,
        )

    def _normalize_description(self):
        return _normalize_text_value(
            self.cleaned_data.get(self.description_field_name),
            "Keterangan",
            allow_blank=True,
        )

    def _validate_unique_name(self, model_class, field_name="name"):
        value = self.cleaned_data.get(field_name)
        if not value:
            return value

        qs = model_class.objects.filter(**{f"{field_name}__iexact": value})
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError("Nama sudah digunakan. Gunakan nama lain.")
        return value


class UnitForm(LookupValidationMixin, forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["code", "name", "description"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control", "maxlength": 20}),
            "name": forms.TextInput(attrs={"class": "form-control", "maxlength": 100}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def clean_code(self):
        return self._normalize_code()

    def clean_name(self):
        name = self._normalize_name()
        self.cleaned_data["name"] = name
        return self._validate_unique_name(Unit)

    def clean_description(self):
        return self._normalize_description()


class CategoryForm(LookupValidationMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["code", "name", "sort_order"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control", "maxlength": 20}),
            "name": forms.TextInput(attrs={"class": "form-control", "maxlength": 100}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def clean_code(self):
        return self._normalize_code()

    def clean_name(self):
        name = self._normalize_name()
        self.cleaned_data["name"] = name
        return self._validate_unique_name(Category)


class ProgramForm(LookupValidationMixin, forms.ModelForm):
    class Meta:
        model = Program
        fields = ["code", "name", "description", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control", "maxlength": 20}),
            "name": forms.TextInput(attrs={"class": "form-control", "maxlength": 100}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_code(self):
        return self._normalize_code()

    def clean_name(self):
        name = self._normalize_name()
        self.cleaned_data["name"] = name
        return self._validate_unique_name(Program)

    def clean_description(self):
        return self._normalize_description()


class TherapeuticClassForm(LookupValidationMixin, forms.ModelForm):
    class Meta:
        model = TherapeuticClass
        fields = ["code", "name", "description", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-control", "maxlength": 20}),
            "name": forms.TextInput(attrs={"class": "form-control", "maxlength": 100}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_code(self):
        return self._normalize_code()

    def clean_name(self):
        name = self._normalize_name()
        self.cleaned_data["name"] = name
        return self._validate_unique_name(TherapeuticClass)

    def clean_description(self):
        return self._normalize_description()
