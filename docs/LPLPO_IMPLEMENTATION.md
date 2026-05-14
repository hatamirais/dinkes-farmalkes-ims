# LPLPO Feature Implementation Guide

## Overview

This document describes the full implementation plan for the **Laporan Pemakaian dan Lembar Permintaan Obat (LPLPO)** module. It is intended as a complete specification for a coding agent to implement without ambiguity.

---

## 1. Context and Business Rules

### 1.1 What is LPLPO

LPLPO is a monthly document submitted by each Puskesmas to Instalasi Farmasi. It serves two purposes:
1. **Laporan Pemakaian** — reporting consumption of medicines/supplies in the previous month
2. **Lembar Permintaan** — requesting stock for the upcoming month

### 1.2 Timing

- LPLPO for **Bulan X** is submitted in **Bulan X+1**
- Example: LPLPO for January is filled and submitted in February
- This means when a Puskesmas opens their January LPLPO, the January Distribution records from Instalasi Farmasi already exist and can be used to pre-fill Penerimaan

### 1.3 Workflow (Sequential)

```
[Puskesmas Operator]
1. Opens new LPLPO for a given bulan/tahun
2. System auto-generates one line per active Item (controlled by Instalasi Farmasi)
3. System auto-fills Penerimaan from all LPLPO-type and SPECIAL_REQUEST Distributions
   sent to that Puskesmas in that bulan/tahun
4. Puskesmas fills: Stock Awal (month 1 only), Pemakaian, Stock Gudang Puskesmas,
   Waktu Kosong, Permintaan Jumlah, Permintaan Alasan
5. All computed fields are calculated automatically (see formulas)
6. Puskesmas submits LPLPO → status: SUBMITTED
7. Kepala Instalasi / approver can reject submitted LPLPO with a required rejection reason → status: REJECTED
8. Puskesmas revises rejected LPLPO and re-submits it when ready

[Instalasi Farmasi Operator]
9. Reviews submitted LPLPO
10. System suggests Pemberian Jumlah = Jumlah Kebutuhan per item
11. Operator adjusts Pemberian Jumlah based on actual warehouse stock
12. Operator fills Pemberian Alasan where adjusted
13. Operator finalizes → status: REVIEWED
14. System auto-generates a draft Distribution document (type: LPLPO)
    while the LPLPO remains in REVIEWED until the Distribution workflow is completed
15. LPLPO status → CLOSED after the linked Distribution reaches DISTRIBUTED

[Next Month Auto-fill]
14. When Puskesmas opens next month's LPLPO:
    - Stock Awal = previous month's Stock Keseluruhan (auto-filled)
    - Penerimaan = sum of all Distributions sent that month (auto-filled, confirmable)
```

### 1.4 Item List

- Fixed — controlled entirely by Instalasi Farmasi via the existing `Item` master data
- All active `Item` records are included as line items when a new LPLPO is created
- Puskesmas cannot add or remove items from the LPLPO

### 1.5 Penerimaan Sources

Penerimaan on the LPLPO = sum of ALL distributions sent to that Puskesmas in that month, including:
- Regular LPLPO-based distributions (`distribution_type=LPLPO`)
- Special/program item requests (`distribution_type=SPECIAL_REQUEST`)
- Any other distribution type sent to that Puskesmas in that period

Query logic:
```python
Distribution.objects.filter(
    facility=puskesmas_facility,
    status=Distribution.Status.DISTRIBUTED,
    distributed_date__year=tahun,
    distributed_date__month=bulan,
)
```

Then aggregate `quantity_approved` per `item` across all matching `DistributionItem` records.

### 1.6 Stock Awal Logic

- **Month 1 (first ever LPLPO for a Puskesmas)**: filled manually by Puskesmas operator
- **Subsequent months**: `Stock_Awal = previous month's Stock_Keseluruhan`
  - Lookup: previous LPLPO for same facility where `(bulan, tahun)` is one month earlier
  - If previous LPLPO exists and is CLOSED, auto-fill from `stock_keseluruhan`
  - If no previous LPLPO exists, field is editable

---

## 2. Formulas (Exact)

All computed fields must be calculated server-side and stored. They are also recalculated on save.

```
persediaan        = stock_awal + penerimaan
stock_keseluruhan = persediaan - pemakaian
stock_optimum     = pemakaian + (pemakaian * 20 / 100)
                  = pemakaian * 1.2
jumlah_kebutuhan  = (stock_optimum - stock_keseluruhan) + waktu_kosong
                  = max(stock_optimum - stock_keseluruhan, 0) + waktu_kosong

suggested_pemberian = jumlah_kebutuhan
```

`stock_optimum` follows the consumption method, so it must always be based on period usage (`pemakaian`) rather than ending stock.

**Important**: All computed fields must handle `None`/null inputs gracefully. If any input is None, treat as 0 for calculation purposes.

---

## 3. Data Models

### 3.1 New App: `apps.lplpo`

Create a new Django app: `backend/apps/lplpo/`

### 3.2 LPLPO (Header Model)

```python
class LPLPO(TimeStampedModel):
    """Header document for monthly Puskesmas stock report and request."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SUBMITTED = 'SUBMITTED', 'Diajukan'      # Puskesmas submitted
        REVIEWED = 'REVIEWED', 'Ditinjau'         # Instalasi Farmasi reviewed
        DISTRIBUTED = 'DISTRIBUTED', 'Didistribusikan'  # Distribution created
        CLOSED = 'CLOSED', 'Ditutup'              # Distribution completed

    facility = models.ForeignKey(
        'items.Facility',
        on_delete=models.PROTECT,
        related_name='lplpos',
    )
    bulan = models.PositiveSmallIntegerField()   # 1-12
    tahun = models.PositiveIntegerField()         # e.g. 2026
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    document_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text='Auto-generated: LPLPO-YYYYMM-XXXXX'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_lplpos',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='reviewed_lplpos',
    )
    rejection_reason = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    distribution = models.OneToOneField(
        'distribution.Distribution',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='lplpo_source',
        help_text='Distribution document generated from this LPLPO'
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'lplpos'
        ordering = ['-tahun', '-bulan', 'facility__name']
        constraints = [
            models.UniqueConstraint(
                fields=['facility', 'bulan', 'tahun'],
                name='uq_lplpo_facility_period'
            )
        ]
        indexes = [
            models.Index(fields=['facility', 'tahun', 'bulan'], name='idx_lplpo_facility_period'),
            models.Index(fields=['status'], name='idx_lplpo_status'),
        ]
```

### 3.3 LPLPOItem (Line Model)

```python
class LPLPOItem(models.Model):
    """Line item for each drug/supply in an LPLPO document."""

    lplpo = models.ForeignKey(
        LPLPO,
        on_delete=models.CASCADE,
        related_name='items',
    )
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.PROTECT,
        related_name='lplpo_items',
    )

    # === Filled by Puskesmas ===
    stock_awal = models.PositiveIntegerField(
        default=0,
        help_text='Manual on first LPLPO, auto-filled from previous month Stock Keseluruhan'
    )
    penerimaan = models.PositiveIntegerField(
        default=0,
        help_text='Auto-filled from Distribution records, confirmable by Puskesmas'
    )
    pembelian_puskesmas = models.PositiveIntegerField(
        default=0,
        help_text='Jumlah pembelian mandiri Puskesmas pada periode ini'
    )
    pemakaian = models.PositiveIntegerField(
        default=0,
        help_text='Filled by Puskesmas operator'
    )
    stock_gudang_puskesmas = models.PositiveIntegerField(
        default=0,
        help_text='Physical count of Puskesmas warehouse stock, filled manually'
    )
    waktu_kosong = models.PositiveSmallIntegerField(
        default=0,
        help_text='Stockout days in the reporting period'
    )
    permintaan_jumlah = models.PositiveIntegerField(
        default=0,
        help_text='Requested quantity by Puskesmas'
    )
    permintaan_alasan = models.TextField(
        blank=True,
        help_text='Reason for request, filled by Puskesmas'
    )

    # === Computed Fields (auto-calculated, stored) ===
    persediaan = models.PositiveIntegerField(
        default=0,
        help_text='stock_awal + penerimaan + pembelian_puskesmas'
    )
    stock_keseluruhan = models.IntegerField(
        default=0,
        help_text='persediaan - pemakaian'
    )
    stock_optimum = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='replenishment_basis * 1.2; use pemakaian when stock_keseluruhan <= 0'
    )
    jumlah_kebutuhan = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='max(stock_optimum - stock_keseluruhan, 0) + waktu_kosong'
    )

    # === Filled by Instalasi Farmasi ===
    pemberian_jumlah = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Actual quantity given, system-suggested = jumlah_kebutuhan'
    )
    pemberian_alasan = models.TextField(
        blank=True,
        help_text='Reason if pemberian differs from permintaan'
    )

    # === Audit ===
    penerimaan_auto_filled = models.BooleanField(
        default=False,
        help_text='True if penerimaan was auto-filled from Distribution records'
    )

    class Meta:
        db_table = 'lplpo_items'
        unique_together = [('lplpo', 'item')]
        ordering = ['item__kategori__sort_order', 'item__nama_barang']

    def compute_fields(self):
        """Recalculate all derived fields. Call before save."""
        from decimal import Decimal

        def safe(val):
            return val if val is not None else Decimal('0')

        self.persediaan = safe(self.stock_awal) + safe(self.penerimaan)
        self.stock_keseluruhan = self.persediaan - safe(self.pemakaian)
        self.stock_optimum = self.stock_keseluruhan * Decimal('1.2')
        self.jumlah_kebutuhan = (
            self.stock_keseluruhan * Decimal('0.2')
        ) + safe(self.waktu_kosong)

    def save(self, *args, **kwargs):
        self.compute_fields()
        super().save(*args, **kwargs)
```

---

## 4. New User Role / Access

### 4.1 New Role: PUSKESMAS

Add `PUSKESMAS = 'PUSKESMAS', 'Operator Puskesmas'` to `User.Role` in `backend/apps/users/models.py`.

Update `ROLE_DEFAULT_SCOPES` in `backend/apps/users/access.py`:

```python
User.Role.PUSKESMAS: {
    ModuleAccess.Module.USERS: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.ITEMS: ModuleAccess.Scope.VIEW,
    ModuleAccess.Module.STOCK: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.RECEIVING: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.DISTRIBUTION: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.RECALL: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.EXPIRED: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.STOCK_OPNAME: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.REPORTS: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.ADMIN_PANEL: ModuleAccess.Scope.NONE,
    ModuleAccess.Module.LPLPO: ModuleAccess.Scope.OPERATE,
},
```

### 4.2 Facility Binding

Add a nullable FK to User model to bind a Puskesmas operator to their facility:

```python
# In User model
facility = models.ForeignKey(
    'items.Facility',
    on_delete=models.SET_NULL,
    null=True, blank=True,
    related_name='operators',
    help_text='For PUSKESMAS role: the facility this user belongs to'
)
```

Add a migration for this field.

### 4.3 New Module in ModuleAccess

Add `LPLPO = 'lplpo', 'LPLPO'` to `ModuleAccess.Module` choices.

### 4.4 Access Rules

- **PUSKESMAS role**: can only see and edit their own facility's LPLPO. Enforce this in every view with `lplpo.facility == request.user.facility`.
- **PUSKESMAS role**: can only edit LPLPO in `DRAFT` or `REJECTED` status.
- **PUSKESMAS role**: cannot see Distribution, Stock, Receiving, or any other module.
- **GUDANG / ADMIN / KEPALA**: can see all LPLPO from all facilities, can fill Pemberian fields (REVIEWED step).
- **KEPALA / approve-scope users**: can reject `SUBMITTED` LPLPO and can finalize `REVIEWED` LPLPO.

---

## 5. URL Structure

```
/lplpo/                                    → lplpo_list (Instalasi Farmasi sees all)
/lplpo/my/                                 → lplpo_my_list (Puskesmas sees own)
/lplpo/create/                             → lplpo_create
/lplpo/print-report/                       → lplpo_print_report (printable filtered submitted queue)
/lplpo/<int:pk>/                           → lplpo_detail
/lplpo/<int:pk>/edit/                      → lplpo_edit (Puskesmas, DRAFT/REJECTED)
/lplpo/<int:pk>/submit/                    → lplpo_submit (Puskesmas)
/lplpo/<int:pk>/reject/                    → lplpo_reject (approve-scope Instalasi Farmasi)
/lplpo/<int:pk>/review/                    → lplpo_review (Instalasi Farmasi, fills Pemberian)
/lplpo/<int:pk>/finalize/                  → lplpo_finalize (creates Distribution)
/lplpo/<int:pk>/print/                     → lplpo_print (print-friendly HTML)
/lplpo/api/prefill-penerimaan/             → api_prefill_penerimaan (AJAX)
```

App namespace: `lplpo`

---

## 6. View Logic

### 6.1 lplpo_create

- Only accessible to PUSKESMAS role (and ADMIN for manual creation on behalf)
- On GET: show form with bulan/tahun selector
- On POST:
  1. Validate no existing LPLPO for same (facility, bulan, tahun)
  2. Create LPLPO header
  3. Auto-generate one `LPLPOItem` per active `Item` in the system
  4. Auto-fill `stock_awal` from previous month's `stock_keseluruhan` if available
  5. Auto-fill `penerimaan` from Distribution records (set `penerimaan_auto_filled=True`)
    6. Keep `pemberian_jumlah` empty until Instalasi Farmasi review
    7. Redirect to detail view

### 6.2 lplpo_edit

- Only DRAFT status allowed
- Puskesmas can edit: `stock_awal` (only if no previous LPLPO), `pemakaian`, `stock_gudang_puskesmas`, `waktu_kosong`, `permintaan_jumlah`, `permintaan_alasan`
- Puskesmas can confirm/override `penerimaan` (even if auto-filled)
- Computed fields recalculate on save
- `pemberian_jumlah` suggestion is shown only in review form initial data and is not persisted before review

### 6.3 lplpo_submit

- Transitions DRAFT → SUBMITTED
- Validates: all items have `pemakaian` filled (warn if zero but allow)
- Sets `submitted_at = now()`

### 6.4 lplpo_review

- Only accessible to GUDANG/ADMIN/KEPALA scope
- Shows full LPLPO with Pemberian columns editable
- Operator can adjust `pemberian_jumlah` and fill `pemberian_alasan` per line
- Shows current Instalasi Farmasi stock for each item alongside (from Stock model)
  to help operator make informed decisions
- On save: transitions to REVIEWED, sets `reviewed_by`, `reviewed_at`

### 6.5 lplpo_finalize

- Only accessible to KEPALA or ADMIN with APPROVE scope
- Creates a `Distribution` document:
  ```python
  Distribution.objects.create(
      distribution_type=Distribution.DistributionType.LPLPO,
      facility=lplpo.facility,
      request_date=date(lplpo.tahun, lplpo.bulan, 1),
      status=Distribution.Status.DRAFT,
      created_by=request.user,
      notes=f'Generated from LPLPO {lplpo.document_number}',
  )
  ```
- Creates `DistributionItem` for each `LPLPOItem` where `pemberian_jumlah > 0`:
  ```python
  DistributionItem.objects.create(
      distribution=distribution,
      item=lplpo_item.item,
      quantity_requested=lplpo_item.permintaan_jumlah,
      quantity_approved=lplpo_item.pemberian_jumlah,
  )
  ```
- Links `lplpo.distribution = distribution`
- Keeps LPLPO in REVIEWED so the Distribution document can continue through
    submit, verify, prepare, and distribute stages normally
- Redirects to the created Distribution detail view
- LPLPO transitions to CLOSED automatically via a signal or explicit check
  when the linked Distribution reaches DISTRIBUTED status
- `DistributionType.LPLPO` should not be available in the manual Distribution create/edit form; it is reserved for documents generated from finalized LPLPO submissions.

### 6.5.1 Submitted Queue for Instalasi Farmasi

- The main Instalasi Farmasi LPLPO submenu should show only documents that have already been submitted by Puskesmas (`submitted_at is not null`).
- Operators can filter this queue by submission month and submission year.
- The queue provides a printable report view based on the current filters.

### 6.6 Auto-fill Penerimaan Logic (helper function)

```python
def get_penerimaan_for_facility_period(facility, bulan, tahun):
    """
    Returns dict: {item_id: total_quantity} for all distributions
    sent to this facility in the given month/year.
    """
    from apps.distribution.models import Distribution, DistributionItem
    from django.db.models import Sum

    distributions = Distribution.objects.filter(
        facility=facility,
        status=Distribution.Status.DISTRIBUTED,
        distributed_date__year=tahun,
        distributed_date__month=bulan,
    )
    result = {}
    items = DistributionItem.objects.filter(
        distribution__in=distributions
    ).values('item_id').annotate(
        total=Sum('quantity_approved')
    )
    for row in items:
        result[row['item_id']] = row['total']
    return result
```

---

## 7. Forms

### 7.1 LPLPOCreateForm

```python
class LPLPOCreateForm(forms.Form):
    bulan = forms.ChoiceField(
        choices=[(i, calendar.month_name[i]) for i in range(1, 13)],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    tahun = forms.IntegerField(
        min_value=2020,
        max_value=2099,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )
```

### 7.2 LPLPOItemPuskesmasForm (for Puskesmas edit)

Fields: `stock_awal`, `penerimaan`, `pemakaian`, `stock_gudang_puskesmas`, `waktu_kosong`, `permintaan_jumlah`, `permintaan_alasan`

Lock `stock_awal` if previous LPLPO exists (readonly widget).
Lock `penerimaan` display but allow override with confirmation flag.

### 7.3 LPLPOItemReviewForm (for Instalasi Farmasi review)

Fields: `pemberian_jumlah`, `pemberian_alasan` only.
All Puskesmas fields are readonly.

---

## 8. Templates

### 8.1 Template List

```
backend/templates/lplpo/
├── lplpo_list.html          # Instalasi Farmasi: all LPLPOs
├── lplpo_my_list.html       # Puskesmas: own LPLPOs only
├── lplpo_create.html        # Period selector form
├── lplpo_detail.html        # Read-only full view
├── lplpo_edit.html          # Puskesmas fills their columns
├── lplpo_review.html        # Instalasi Farmasi fills Pemberian
└── lplpo_print.html         # Print-friendly, mirrors Excel layout
```

### 8.2 Key UI Notes

- The main editing views (`lplpo_edit` and `lplpo_review`) should render as a **wide table** matching the LPLPO column layout, not as a vertical form. Use `table-responsive` wrapper.
- Computed fields should update **live via JavaScript** as the user types, before save.
- In `lplpo_review`, show a third column alongside `permintaan_jumlah` and `pemberian_jumlah` showing **current Instalasi Farmasi stock** for that item (queried from `Stock` model, sum of available quantity).
- Group rows by `item.kategori` with a category header row (same as the Excel template groups by TABLET, SIRUP, etc.).
- `lplpo_print.html` should closely mirror the Excel layout for physical printing.

### 8.3 JavaScript Requirements

In `lplpo_edit.html`, add inline JS to recalculate computed fields on input:

```javascript
// For each row, on input of stock_awal, penerimaan, pemakaian, waktu_kosong:
function recalcRow(row) {
    const stockAwal = parseFloat(row.querySelector('[name*="stock_awal"]').value) || 0;
    const penerimaan = parseFloat(row.querySelector('[name*="penerimaan"]').value) || 0;
    const pemakaian = parseFloat(row.querySelector('[name*="pemakaian"]').value) || 0;
    const waktuKosong = parseFloat(row.querySelector('[name*="waktu_kosong"]').value) || 0;

    const persediaan = stockAwal + penerimaan;
    const stockKeseluruhan = persediaan - pemakaian;
    const stockOptimum = stockKeseluruhan * 1.2;
    const jumlahKebutuhan = (stockKeseluruhan * 0.2) + waktuKosong;

    row.querySelector('.js-persediaan').textContent = persediaan.toFixed(2);
    row.querySelector('.js-stock-keseluruhan').textContent = stockKeseluruhan.toFixed(2);
    row.querySelector('.js-stock-optimum').textContent = stockOptimum.toFixed(2);
    row.querySelector('.js-jumlah-kebutuhan').textContent = jumlahKebutuhan.toFixed(2);
    row.querySelector('.js-suggested-pemberian').textContent = jumlahKebutuhan.toFixed(2);
}
```

---

## 9. Admin Registration

```python
# backend/apps/lplpo/admin.py

class LPLPOItemInline(admin.TabularInline):
    model = LPLPOItem
    extra = 0
    readonly_fields = ('persediaan', 'stock_keseluruhan', 'stock_optimum', 'jumlah_kebutuhan')

@admin.register(LPLPO)
class LPLPOAdmin(admin.ModelAdmin):
    list_display = ('document_number', 'facility', 'bulan', 'tahun', 'status', 'created_by')
    list_filter = ('status', 'tahun', 'bulan')
    search_fields = ('document_number', 'facility__name')
    inlines = [LPLPOItemInline]
```

---

## 10. Signal: Auto-close LPLPO When Distribution Completes

Add a signal in `apps/lplpo/apps.py` (or `signals.py`) that listens for Distribution status changes:

```python
# apps/lplpo/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender='distribution.Distribution')
def close_lplpo_on_distribution_complete(sender, instance, **kwargs):
    """When a Distribution linked to an LPLPO is DISTRIBUTED, close the LPLPO."""
    from apps.lplpo.models import LPLPO
    if instance.status != 'DISTRIBUTED':
        return
    try:
        lplpo = instance.lplpo_source
        if lplpo.status in (LPLPO.Status.REVIEWED, LPLPO.Status.DISTRIBUTED):
            lplpo.status = LPLPO.Status.CLOSED
            lplpo.save(update_fields=['status', 'updated_at'])
    except LPLPO.DoesNotExist:
        pass
```

---

## 11. Document Number Generation

In `LPLPO.save()`:

```python
def save(self, *args, **kwargs):
    if not self.document_number:
        prefix = f"LPLPO-{self.tahun}{str(self.bulan).zfill(2)}-"
        last = LPLPO.objects.filter(
            document_number__startswith=prefix
        ).order_by('-document_number').first()
        if last:
            num = int(last.document_number.split('-')[-1]) + 1
        else:
            num = 1
        self.document_number = f"{prefix}{str(num).zfill(5)}"
    super().save(*args, **kwargs)
```

---

## 12. Settings and App Registration

Add to `INSTALLED_APPS` in `backend/config/settings.py`:
```python
'apps.lplpo',
```

Add to `backend/config/urls.py`:
```python
path('lplpo/', include('apps.lplpo.urls')),
```

Add to sidebar in `backend/templates/base.html` — visible to PUSKESMAS role and Instalasi Farmasi staff with LPLPO module access.

---

## 13. Migration Notes

Run in order:
1. Migration for `User.facility` FK
2. Migration for `ModuleAccess.Module.LPLPO` choice addition
3. Migration for `User.Role.PUSKESMAS` choice addition
4. Migration for new `lplpo` app (creates `lplpos` and `lplpo_items` tables)

---

## 14. Testing Requirements

Write tests in `backend/apps/lplpo/tests.py` covering:

1. `test_auto_generate_items_on_create` — verify all active Items become LPLPOItems
2. `test_penerimaan_auto_fill` — verify penerimaan aggregates from Distribution correctly
3. `test_stock_awal_from_previous_lplpo` — verify month-to-month stock_awal chain
4. `test_computed_fields_correct` — verify all formula calculations
5. `test_unique_constraint_facility_period` — verify duplicate LPLPO blocked
6. `test_puskesmas_cannot_see_other_facility_lplpo` — verify access control
7. `test_finalize_creates_distribution` — verify Distribution is created correctly
8. `test_distribution_distributed_closes_lplpo` — verify signal works

---

## 15. Conventions to Follow

Follow all existing project conventions from `AGENTS.md` and `.github/copilot-instructions.md`:

- All models inherit from `TimeStampedModel` (except line items which use auto `created_at`)
- Use `@login_required` + `@perm_required` decorators on all views
- Paginate list views at 25 items per page
- Use `messages.success` / `messages.error` for user feedback
- Indonesian field labels in templates, English field names in code
- Use `db_table` explicit naming: `lplpos`, `lplpo_items`
- Document number auto-generation follows existing pattern
- Never mutate Transaction records — the Distribution created from LPLPO will handle its own Transaction trail
- Use `select_related` and `prefetch_related` appropriately on list queries
- Add `is_staff` sync for PUSKESMAS role in `STAFF_ROLES` — PUSKESMAS should NOT have `is_staff=True`

---

## 16. What NOT to Build (Out of Scope)

- Puskesmas portal login page (use existing login, just filter by role)
- Excel/PDF export of LPLPO (can be added later)
- Celery task for LPLPO reminders (can be added later)
- API endpoints for LPLPO (React frontend planned separately)
- Editing LPLPO after SUBMITTED status from Puskesmas side
