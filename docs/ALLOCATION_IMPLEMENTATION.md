# Allocation Feature Implementation Draft

## Overview

This document defines the proposed redesign of the current Alokasi method into a dedicated module. The goal is to separate allocation work from the generic Distribusi module because allocation now has a different business shape:

- one document can target multiple facilities
- one document can assign multiple preparation staff (`Petugas`)
- Kepala Instalasi must have an explicit approval checkpoint before stock is prepared and released
- allocation rows must clearly state which facility receives each item

This is a draft specification intended to guide implementation.

---

## 1. Decision Summary

### 1.1 Main decision

Create a new Django app: `backend/apps/allocation/`

Do not continue modeling allocation as `distribution_type=ALLOCATION` inside the generic `distribution` app.

### 1.2 Why a separate app is needed

Current `Distribution` is structurally single-destination:

- header has a single `facility`
- detail, print, workflow, and stock transaction notes assume one destination facility per document
- current list, filters, and notification labels only distinguish distribution types, not different document structures

If multi-facility allocation is forced into `distribution`, the codebase will accumulate special cases in forms, templates, workflow services, filters, print pages, and audit output.

### 1.3 New workflow summary

Recommended workflow:

`DRAFT -> SUBMITTED -> APPROVED -> PREPARED -> DISTRIBUTED`

Optional rejection branch:

`SUBMITTED -> REJECTED`

This makes Kepala Instalasi approval explicit instead of overloading a generic verification step.

---

## 2. Business Rules

### 2.1 Document purpose

Alokasi is an internal Instalasi Farmasi planning-and-release document used to allocate stock across multiple destination facilities in one controlled approval flow.

### 2.2 Core rules

1. One Alokasi document may include many facilities.
2. Item rows must store the destination facility explicitly.
3. The header-level facility picker limits which facilities may be used in item rows.
4. Stock is not reduced on create, submit, or approve.
5. Stock is reduced only on `DISTRIBUTED`.
6. Kepala Instalasi approval is required before preparation can start.
7. The selected `Petugas` on the form are operational staff assignments, not the approving authority.
8. One item row always maps to one destination facility.

### 2.3 Quantity model

Initial version should use a single operational quantity field on each row:

- `quantity`

Reason:

- allocation is an internal pharmacy allocation document, not an external request document
- the user-requested UI only mentions one quantity column
- document-level approval by Kepala Instalasi is sufficient for the first iteration

If later needed, a second field such as `approved_quantity` can be added without changing the document structure.

---

## 3. Proposed Data Model

### 3.1 New app

Create a new app:

- `backend/apps/allocation/`

### 3.2 Allocation (header)

```python
class Allocation(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SUBMITTED = 'SUBMITTED', 'Diajukan'
        APPROVED = 'APPROVED', 'Disetujui'
        PREPARED = 'PREPARED', 'Disiapkan'
        DISTRIBUTED = 'DISTRIBUTED', 'Terdistribusi'
        REJECTED = 'REJECTED', 'Ditolak'

    document_number = models.CharField(...)
    allocation_date = models.DateField()
    status = models.CharField(..., default=Status.DRAFT)
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(..., related_name='created_allocations')
    submitted_by = models.ForeignKey(..., null=True, blank=True, related_name='submitted_allocations')
    approved_by = models.ForeignKey(..., null=True, blank=True, related_name='approved_allocations')
    prepared_by = models.ForeignKey(..., null=True, blank=True, related_name='prepared_allocations')
    distributed_by = models.ForeignKey(..., null=True, blank=True, related_name='distributed_allocations')

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    prepared_at = models.DateTimeField(null=True, blank=True)
    distributed_at = models.DateTimeField(null=True, blank=True)
    distributed_date = models.DateField(null=True, blank=True)
```

Notes:

- `document_number` is auto-generated only when the user leaves the field empty.
- `prepared_by` is the authenticated user who executes the prepare action.
- Keep document numbering separate from Distribusi, for example `ALC-YYYYMM-XXXXX`.

### 3.3 AllocationStaffAssignment (assigned staff)

```python
class AllocationStaffAssignment(TimeStampedModel):
    allocation = models.ForeignKey(
        'allocation.Allocation',
        on_delete=models.CASCADE,
        related_name='staff_assignments',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='allocation_staff_assignments',
    )

    class Meta:
        unique_together = ('allocation', 'user')
```

Use this table for the `Petugas` multi-select assignment.

### 3.4 AllocationFacility (selected facilities)

```python
class AllocationFacility(models.Model):
    allocation = models.ForeignKey(
        'allocation.Allocation',
        on_delete=models.CASCADE,
        related_name='selected_facilities',
    )
    facility = models.ForeignKey(
        'items.Facility',
        on_delete=models.PROTECT,
        related_name='allocation_selections',
    )

    class Meta:
        unique_together = ('allocation', 'facility')
```
```

Use this table to support the header-level multiple facility picker.

### 3.5 AllocationItem (line rows)

```python
class AllocationItem(models.Model):
    allocation = models.ForeignKey(
        'allocation.Allocation',
        on_delete=models.CASCADE,
        related_name='items',
    )
    facility = models.ForeignKey(
        'items.Facility',
        on_delete=models.PROTECT,
        related_name='allocation_items',
    )
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.PROTECT,
        related_name='allocation_items',
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    stock = models.ForeignKey(
        'stock.Stock',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='allocation_items',
    )
    issued_batch_lot = models.CharField(max_length=100, blank=True)
    issued_expiry_date = models.DateField(null=True, blank=True)
    issued_unit_price = models.DecimalField(max_digits=28, decimal_places=15, null=True, blank=True)
    issued_sumber_dana = models.ForeignKey(
        'items.FundingSource',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='issued_allocation_items',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```
```

### 3.6 Important validation rules

1. `quantity > 0`
2. `stock.item == item`
3. `quantity <= stock.available_quantity`
4. `facility` on every row must be one of the header-selected facilities
5. `selected_facilities` may not be empty
6. `items` may not be empty on submit
7. `staff_assignments` may not be empty on submit

---

## 4. Workflow and Approval Model

### 4.1 Roles

Recommended responsibility split:

- `ADMIN_UMUM` or `GUDANG`: create, edit, submit, prepare, distribute according to scope
- `KEPALA`: approve or reject submitted allocation documents
- `ADMIN`: manage all states

### 4.2 Status behavior

#### DRAFT

- editable
- selected facilities may be added or removed
- line items may be added, edited, or removed

#### SUBMITTED

- awaiting Kepala Instalasi review
- no stock impact
- only approver may approve or reject

#### APPROVED

- document is approved by Kepala Instalasi
- preparer can start physical preparation
- no stock impact yet

#### PREPARED

- physical preparation complete
- final stock deduction still has not happened

#### DISTRIBUTED

- stock is deducted
- `Transaction(type=OUT, reference_type=ALLOCATION)` rows are written
- row-level issued snapshot fields are frozen

#### REJECTED

- returned by Kepala Instalasi
- may be reset to `DRAFT`

### 4.3 Approval semantics

Kepala Instalasi control should be explicit in both data and authorization:

- use `approved_by` and `approved_at` fields on the header
- gate the approval action with module scope `APPROVE`
- show `Setujui` and `Tolak` actions only to users with approval scope

This is preferable to reusing a generic `verified_by` field because the business meaning here is approval, not warehouse verification.

---

## 5. Permissions and Module Access

### 5.1 New module scope

Add a new `ModuleAccess.Module.ALLOCATION = 'allocation'`.

Reason:

- user requested Alokasi as its own module
- future access may diverge from generic Distribusi
- separate notifications and sidebar visibility are easier to manage

### 5.2 Recommended default scopes

```python
ADMIN       -> MANAGE
KEPALA      -> APPROVE
ADMIN_UMUM  -> OPERATE
GUDANG      -> OPERATE
AUDITOR     -> VIEW
PUSKESMAS   -> NONE
```

### 5.3 Permissions

Register standard Django permissions for the new models and rely on existing hybrid logic:

- `allocation.view_allocation`
- `allocation.add_allocation`
- `allocation.change_allocation`
- `allocation.delete_allocation`

Approval and rejection actions should also require:

- module scope `APPROVE`

---

## 6. Routes and Navigation

### 6.1 New route group

Add root include:

- `/allocation/`

Recommended route set:

- `/allocation/` -> list
- `/allocation/create/` -> create
- `/allocation/<pk>/` -> detail
- `/allocation/<pk>/edit/` -> edit
- `/allocation/<pk>/submit/` -> submit
- `/allocation/<pk>/approve/` -> approve
- `/allocation/<pk>/reject/` -> reject
- `/allocation/<pk>/prepare/` -> prepare
- `/allocation/<pk>/distribute/` -> distribute
- `/allocation/<pk>/reset-to-draft/` -> reset
- `/allocation/<pk>/delete/` -> delete

### 6.2 Sidebar placement

Place Alokasi under the existing `Pengeluaran` submenu as its own menu entry.

Recommended order:

1. Distribusi
2. Alokasi
3. Daftar LPLPO
4. Recall / Retur
5. Kedaluwarsa

### 6.3 Back button behavior

Match current module patterns:

- non-list allocation pages show a contextual back button to the allocation list

---

## 7. Form and UI Draft

### 7.1 Header form

Create page fields:

- `Document number`
- `Date`
- `Facility` multi-picker
- `Petugas` multi-picker
- `Keterangan`

Recommended field mapping:

- `Document number` -> `document_number`
- `Date` -> `allocation_date`
- `Facility multi-picker` -> `AllocationFacility` through form handling
- `Petugas multi-picker` -> `AllocationStaffAssignment` through form handling
- `Keterangan` -> `notes`

### 7.2 Item table

Recommended columns:

1. `Fasilitas`
2. `Barang`
3. `Jumlah`
4. `Stok (Batch)`
5. `Keterangan`

This is slightly more explicit than the original idea of showing all selected facilities in one display-only column. Each row must carry one facility value so the data remains auditable and printable.

This is a fixed design rule: one item row always represents one facility.

### 7.3 Row behavior

1. Facility dropdown options are limited to the header-selected facilities.
2. Item selector uses the same inline typeahead approach already used in Distribusi.
3. Stock selector stays dependent on the selected item in the same row.
4. Batch choices must remain FEFO-sorted and available-stock-only.
5. If a selected facility is removed from the header, existing rows using that facility must be blocked until corrected.

### 7.4 List page

Recommended list filters:

- search: document number, facility name, item name, petugas name
- status
- date range or month-year

Recommended list columns:

- Document number
- Date
- Ringkasan fasilitas
- Petugas
- Total item rows
- Status
- Created by

For facility summary, show for example:

- first facility name + `(+N)` additional facilities

---

## 8. Detail and Print Behavior

### 8.1 Detail page

Show:

- document header
- selected facilities summary
- assigned staff
- approval information (`approved_by`, `approved_at`)
- row-level facility, item, quantity, batch, notes

### 8.2 Print view

Print output should include:

- Kepala Instalasi approval block
- assigned staff list
- grouped rows by facility for easier reading

Recommended print grouping:

```text
Facility A
  - item 1
  - item 2

Facility B
  - item 3
```

This reads better than a flat multi-facility table on paper.

---

## 9. Stock Mutation Rules

### 9.1 When stock changes

Stock only changes when the document moves to `DISTRIBUTED`.

### 9.2 What happens on distribute

For each `AllocationItem`:

1. re-check stock under transaction lock
2. decrement `Stock.quantity`
3. store batch snapshot fields on the line
4. create `Transaction(type=OUT)`

### 9.3 Proposed transaction reference

Add a new `Transaction.ReferenceType.ALLOCATION`.

Reason:

- separates allocation history from generic distribution history
- improves reporting and stock-card traceability

Transaction notes should include both document number and destination facility, for example:

```text
Alokasi ALC-202604-00001 ke Puskesmas Johan Pahlawan: catatan baris
```

---

## 10. Migration Strategy from Current Distribution Type

### 10.1 Short-term recommendation

After the new module is implemented:

1. remove `ALLOCATION` from manual distribution choices
2. keep historical `distribution_type=ALLOCATION` rows readable in the existing distribution module
3. stop creating new allocation documents in `distribution`

### 10.2 Historical data recommendation

Do not migrate already distributed historical allocation records into the new app.

Reason:

- those rows already have immutable stock transactions linked through `reference_type=DISTRIBUTION`
- backfilling them into a new `allocation` reference chain adds migration risk without operational benefit

### 10.3 Optional migration of open documents

If there are open `distribution_type=ALLOCATION` documents in `DRAFT`, `SUBMITTED`, or `VERIFIED`, these may be migrated into the new app with a custom data migration.

Recommended rule:

- migrate only non-distributed allocation documents
- leave distributed history untouched

---

## 11. Notifications

Add allocation notification counts separate from Distribusi.

Recommended behavior:

- `OPERATE` users see `APPROVED` and `PREPARED` work queues when relevant
- `APPROVE` users see `SUBMITTED` allocations awaiting decision

Recommended notification label:

- `Alokasi`

Notification URL should point to the new allocation list instead of the generic distribution list.

---

## 12. Test Plan

Minimum implementation coverage:

1. create allocation with multiple selected facilities
2. reject create or submit when no facilities are selected
3. reject item row facility not present in selected facility set
4. reject item row stock batch that does not match item
5. reject quantity above available stock
6. submit requires at least one item row
7. approve requires `APPROVE` scope
8. prepare only allowed from `APPROVED`
9. distribute only allowed from `PREPARED`
10. distribute writes `Transaction.ReferenceType.ALLOCATION`
11. stock deduction occurs only on distribute
12. historical `distribution_type=ALLOCATION` is no longer creatable through Distribusi form

---

## 13. Recommended Implementation Order

1. Create `allocation` app and models
2. Add admin registration and migrations
3. Add module access enum and default scopes
4. Add routes and list/detail/create/edit views
5. Add header + line form handling with multi-facility validation and multi-staff assignment
6. Add workflow services and stock posting logic
7. Add templates and sidebar entry
8. Add notifications
9. Remove manual `ALLOCATION` creation from Distribusi
10. Add regression tests and update documentation

---

## 14. Open Decisions

Remaining design choice before implementation:

1. Should rejected documents be editable directly, or only after reset to draft? Recommendation: use reset to draft for consistency with other modules.

---

## 15. Final Recommendation

Implement Alokasi as a new module with its own app, routes, sidebar entry, permissions, and approval workflow.

Use a document-level multi-facility picker, but store facility explicitly on each allocation line item so one row always maps to one facility.

Make Kepala Instalasi the approver through a dedicated `APPROVED` step before preparation and stock release.

Use multi-staff `Petugas` assignment, with document numbering auto-generated only when the user leaves `Document number` empty.
