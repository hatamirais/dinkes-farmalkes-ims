from django import forms
from .models import Item, Unit, Category, Program


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            'nama_barang', 'satuan', 'kategori',
            'is_program_item', 'program', 'minimum_stock', 'description',
        ]
        widgets = {
            'nama_barang': forms.TextInput(attrs={'class': 'form-control'}),
            'satuan': forms.Select(attrs={'class': 'form-select'}),
            'kategori': forms.Select(attrs={'class': 'form-select'}),
            'is_program_item': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'program': forms.Select(attrs={'class': 'form-select'}),
            'minimum_stock': forms.NumberInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['program'].required = False
        self.fields['satuan'].empty_label = None
        self.fields['kategori'].empty_label = None
        self.fields['program'].empty_label = ''
        self.fields['satuan'].label_from_instance = lambda obj: obj.name
        self.fields['kategori'].label_from_instance = lambda obj: obj.name
        self.fields['program'].label_from_instance = lambda obj: obj.name

    def clean(self):
        cleaned_data = super().clean()
        is_program_item = cleaned_data.get('is_program_item')
        program = cleaned_data.get('program')

        if is_program_item and not program:
            self.add_error('program', 'Program wajib dipilih untuk barang program.')

        if not is_program_item:
            cleaned_data['program'] = None

        return cleaned_data


class LookupValidationMixin:
    code_field_name = 'code'
    name_field_name = 'name'

    def _normalize_code(self):
        code = (self.cleaned_data.get(self.code_field_name) or '').strip().upper()
        return code

    def _normalize_name(self):
        name = (self.cleaned_data.get(self.name_field_name) or '').strip()
        return ' '.join(name.split())

    def _validate_unique_name(self, model_class, field_name='name'):
        value = self.cleaned_data.get(field_name)
        if not value:
            return value

        qs = model_class.objects.filter(**{f'{field_name}__iexact': value})
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError('Nama sudah digunakan. Gunakan nama lain.')
        return value


class UnitForm(LookupValidationMixin, forms.ModelForm):
    class Meta:
        model = Unit
        fields = ['code', 'name', 'description']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_code(self):
        return self._normalize_code()

    def clean_name(self):
        name = self._normalize_name()
        self.cleaned_data['name'] = name
        return self._validate_unique_name(Unit)


class CategoryForm(LookupValidationMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['code', 'name', 'sort_order']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def clean_code(self):
        return self._normalize_code()

    def clean_name(self):
        name = self._normalize_name()
        self.cleaned_data['name'] = name
        return self._validate_unique_name(Category)


class ProgramForm(LookupValidationMixin, forms.ModelForm):
    class Meta:
        model = Program
        fields = ['code', 'name', 'description', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_code(self):
        return self._normalize_code()

    def clean_name(self):
        name = self._normalize_name()
        self.cleaned_data['name'] = name
        return self._validate_unique_name(Program)
