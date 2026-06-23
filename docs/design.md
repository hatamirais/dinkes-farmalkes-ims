# Inventory Table UI

## Expiry Status

Three states only. Never color-only — always badge + icon.

- Past: `badge bg-danger` + warning-triangle icon
- ≤30 days: `badge bg-warning text-dark` + clock icon  
- Safe: `badge bg-success`

## Source Fund Badges

Consistent mapping, no exceptions:

- HIBAH → `bg-warning text-dark`
- DAU → `bg-info text-dark`
- PAD Yang Sah → `bg-success`
- Unknown → `bg-secondary`

## Bulk Actions

- Checkbox col: 40px fixed width
- Bulk bar: hidden by default, slides in above thead on any selection
- Actions: Move Location, Delete Stock, Mark Expired
- Destructive action (Mark Expired) always rightmost, red variant

## Row Actions

- Hidden by default, reveal on `tr:hover` via CSS opacity
- Max 2 icons: Edit + Detail only
- 28px icon buttons, outline style

## Stat Bar

- 4 cards: Total SKU, Expired count, Near-expiry count, Reserved
- Expired count: `text-danger` if > 0
- Near-expiry: `text-warning` if > 0
- Computed server-side in Jinja, not JS

## Filter Bar

Order: search input → lokasi select → sumber dana select → date range → quick-filter pills
Quick-filter pills are toggle buttons, active state uses semantic color matching the status.

## Table Column Order

checkbox | kode | nama barang | lokasi | batch/lot | kedaluwarsa | kuantitas | reserved | sumber dana | actions

## Typography in Table

- Kode: 12px, semibold, brand color link
- Nama: 13px regular
- Sub-label (variant name): 11px muted, below nama
- Badges: 11px
- Numbers (qty/reserved): 13px medium weight, unit suffix 11px muted
