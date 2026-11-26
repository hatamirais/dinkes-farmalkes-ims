from decimal import Decimal

from django import forms

from apps.items.models import Item
from .inventory_models import PuskesmasInventoryLayer
from .models import PuskesmasSubunit
from .opname import CONDITIONS, MAX_QUANTITY, revision_roster
from .opname_models import OpnameAction


class StartCountForm(forms.Form):
    year = forms.IntegerField(label="Tahun", min_value=1000, max_value=9999)
    month = forms.IntegerField(label="Bulan", min_value=1, max_value=12)
    inactive = forms.ModelMultipleChoiceField(
        label="Lokasi nonaktif yang masih menyimpan stok", queryset=PuskesmasSubunit.objects.none(), required=False,
    )

    def __init__(self, *args, facility_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inactive"].queryset = PuskesmasSubunit.objects.filter(facility_id=facility_id, is_active=False)


class RevisionForm(forms.Form):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class CloseCountForm(RevisionForm):
    journal = forms.CharField(max_length=64, widget=forms.HiddenInput)


class LocationForm(RevisionForm):
    counted_at = forms.DateTimeField(label="Waktu hitung aktual", widget=forms.DateTimeInput(
        format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    evidence = forms.CharField(label="Bukti cakupan mutasi atau konfirmasi tidak ada mutasi",
        max_length=1000, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    confirmed = forms.BooleanField(label="Lokasi selesai dihitung (tanpa baris berarti stok nihil)", required=False)


class LayerChoice(forms.ModelChoiceField):
    def label_from_instance(self, layer):
        return f"{layer.item} · {layer.batch_lot or 'Batch tidak diketahui'} · {layer.source_document_number or 'Sumber tidak diketahui'} · Rp {layer.unit_price} · #{layer.pk}"


def layers_for(count):
    return PuskesmasInventoryLayer.objects.filter(
        posting__facility_id=count.facility_id, posting__effective_date__lte=count.cutoff,
    ).select_related("item").order_by("item__nama_barang", "pk")


class ObservationForm(RevisionForm):
    item = forms.ModelChoiceField(label="Barang", queryset=Item.objects.order_by("nama_barang"))
    batch = forms.CharField(label="Batch / lot", max_length=100, required=False)
    expiry = forms.DateField(label="Kedaluwarsa", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    layer = LayerChoice(label="Lapisan asal (bila dapat dibuktikan)", queryset=PuskesmasInventoryLayer.objects.none(), required=False)
    observed = forms.IntegerField(label="Jumlah terhitung", min_value=0, max_value=MAX_QUANTITY)
    observed_unit = forms.CharField(label="Satuan pengamatan jika berbeda", max_length=100, required=False)
    factor = forms.DecimalField(label="Faktor ke satuan inventaris", min_value=Decimal("0.000001"), max_digits=14,
                                decimal_places=6, required=False)
    conversion = forms.CharField(label="Bukti konversi satuan", max_length=255, required=False)
    delta = forms.IntegerField(label="Penyesuaian jumlah menuju tanggal batas", min_value=-MAX_QUANTITY,
                               max_value=MAX_QUANTITY, required=False)
    movement_evidence = forms.CharField(label="Bukti mutasi untuk penyesuaian", max_length=255, required=False)
    condition = forms.ChoiceField(label="Kondisi dan penyimpanan", choices=CONDITIONS.items(), required=False)
    excluded_posting = forms.IntegerField(label="ID jurnal penarikan jika masih disimpan", min_value=1, required=False)

    def __init__(self, *args, count, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["layer"].queryset = layers_for(count)


class CaseEvidenceForm(RevisionForm):
    case_key = forms.CharField(max_length=64, widget=forms.HiddenInput)
    evidence = forms.CharField(label="Bukti atau hasil penyelidikan", max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))


class ActionForm(RevisionForm):
    key = forms.UUIDField(widget=forms.HiddenInput)
    kind = forms.ChoiceField(label="Tindakan", choices=OpnameAction.Kind.choices)
    case_key = forms.ChoiceField(label="Kasus selisih", required=False)
    layer = LayerChoice(label="Lapisan terkait", queryset=PuskesmasInventoryLayer.objects.none(), required=False)
    quantity = forms.IntegerField(label="Jumlah pengurangan", min_value=1, max_value=MAX_QUANTITY, required=False)
    incident_date = forms.DateField(label="Tanggal kejadian", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    reverse_id = forms.IntegerField(label="ID penyesuaian yang dibalik", min_value=1, required=False)
    reason = forms.CharField(label="Alasan", max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))
    reference = forms.CharField(label="Referensi bukti", max_length=255)
    expected_change = forms.CharField(label="Perubahan yang diminta saat membuka ulang", max_length=1000, required=False)
    add_location = forms.ModelChoiceField(label="Poli/Pustu yang terlewat (khusus pembukaan ulang)",
                                          queryset=PuskesmasSubunit.objects.none(), required=False)

    def __init__(self, *args, count, comparison, revision, receipt=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["layer"].queryset = layers_for(count)
        if receipt:
            self.fields["kind"].choices = [(OpnameAction.Kind.RECEIPT, OpnameAction.Kind.RECEIPT.label)]
            self.fields["kind"].initial = OpnameAction.Kind.RECEIPT
            self.fields["layer"].queryset = self.fields["layer"].queryset.filter(posting__receipt=receipt)
            for field in ("incident_date", "reverse_id", "expected_change", "add_location"):
                self.fields[field].widget = forms.HiddenInput()
        covered = [row["key"] for row in revision_roster(count, revision) if row["key"].isdigit()]
        self.fields["add_location"].queryset = PuskesmasSubunit.objects.filter(facility_id=count.facility_id).exclude(pk__in=covered)
        self.fields["case_key"].choices = [("", "—")] + [
            (row["key"], f'{row["name"]} / {row["batch"] or "—"} / {row["expiry"] or "—"}')
            for row in comparison["rows"] if row["open"]
        ]


class DecisionForm(forms.Form):
    approve = forms.TypedChoiceField(label="Keputusan", coerce=lambda value: value == "yes",
        choices=(("yes", "Setujui"), ("no", "Tolak")))
    reason = forms.CharField(label="Alasan penolakan", max_length=1000, required=False)
