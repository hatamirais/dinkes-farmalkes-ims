from django import forms
from .models import Item


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = [
            'kode_barang', 'nama_barang', 'satuan', 'kategori',
            'is_program_item', 'program_name', 'minimum_stock', 'description',
        ]
        widgets = {
            'kode_barang': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Auto-generated jika kosong'}),
            'nama_barang': forms.TextInput(attrs={'class': 'form-control'}),
            'satuan': forms.Select(attrs={'class': 'form-select'}),
            'kategori': forms.Select(attrs={'class': 'form-select'}),
            'is_program_item': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'program_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'TB, HIV, Kusta, etc.'}),
            'minimum_stock': forms.NumberInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kode_barang'].required = False
        self.fields['description'].required = False
        self.fields['program_name'].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Auto-generate kode_barang if empty
        if not instance.kode_barang:
            kategori_code = instance.kategori.code
            last_item = (
                Item.objects.filter(kode_barang__startswith=kategori_code)
                .order_by('-kode_barang')
                .first()
            )
            if last_item:
                try:
                    last_num = int(last_item.kode_barang.split('-')[-1])
                    instance.kode_barang = f"{kategori_code}-{last_num + 1:04d}"
                except (ValueError, IndexError):
                    count = Item.objects.filter(kategori=instance.kategori).count()
                    instance.kode_barang = f"{kategori_code}-{count + 1:04d}"
            else:
                instance.kode_barang = f"{kategori_code}-0001"
        if commit:
            instance.save()
        return instance
