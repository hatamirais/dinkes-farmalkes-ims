# Seed Data & CSV Import Guide

This project uses **`django-import-export`** via the **Django Admin panel** for importing master data. Seed CSV files are located in `backend/seed/`.

## Seed Files

### Lookup Tables (Import First)

1. **units.csv** — Measurement units (TAB, KAP, SYR, BTL, AMP, etc.)
2. **categories.csv** — Item categories (TABLET, KAPSUL, INJEKSI, VAKSIN, etc.)
3. **funding_sources.csv** — Funding sources (DAK, DAU, APBD, etc.)
4. **locations.csv** — Storage locations (customize with actual warehouse layout)
5. **suppliers.csv** — Vendor/supplier list
6. **facilities.csv** — Puskesmas and hospitals (customize with actual facility list)

### Core Data (Import After Lookups)

1. **items.csv** — Item master data (requires units + categories)
2. **stock.csv** — Initial inventory (requires items + locations + funding sources)

## Import Order

> [!IMPORTANT]
> Import in this exact order to satisfy foreign key dependencies.

```
1. units.csv
2. categories.csv
3. funding_sources.csv
4. locations.csv
5. suppliers.csv
6. facilities.csv
7. items.csv        ← requires units + categories
8. stock.csv        ← requires items + locations + funding sources
```

## How to Import (Django Admin)

1. Go to **Django Admin** (`/admin/`)
2. Select a model (e.g., **Units**)
3. Click **Import** (top-right button)
4. Choose the CSV file and set format to **csv**
5. Click **Submit** → review the dry-run preview
6. Click **Confirm Import** to commit the data

> [!TIP]
> See `backend/seed/README.md` for detailed column specifications for each CSV file.

## Column Reference (Quick Summary)

### items.csv

| Column | Required | Notes |
|--------|----------|-------|
| kode_barang | ✅ Yes | Unique item code, max 50 chars |
| nama_barang | ✅ Yes | Item name |
| satuan | ✅ Yes | Unit **code** (e.g. `TAB`) |
| kategori | ✅ Yes | Category **code** (e.g. `TABLET`) |
| is_program_item | ❌ No | `1` for program items, default `0` |
| program_name | ❌ No | e.g. TB, HIV, Kusta |
| minimum_stock | ❌ No | Low stock alert threshold, default `0` |
| description | ❌ No | |
| is_active | ❌ No | Default `1` |

### stock.csv

| Column | Required | Notes |
|--------|----------|-------|
| item | ✅ Yes | Item **kode_barang** |
| location | ✅ Yes | Location **code** |
| batch_lot | ✅ Yes | Batch/lot number |
| expiry_date | ✅ Yes | Format: `YYYY-MM-DD` |
| quantity | ❌ No | Default `0` |
| reserved | ❌ No | Default `0` |
| unit_price | ❌ No | Default `0` |
| sumber_dana | ✅ Yes | Funding source **code** |

## Customization Guide

### For Client: Update These Files

1. **locations.csv** — Replace placeholder locations with actual warehouse layout
2. **facilities.csv** — Add all Puskesmas and healthcare facilities
3. **items.csv** — Replace sample data with actual item master
4. **stock.csv** — Add actual inventory with batch/expiry data

### Mapping from Legacy Data

If migrating from the old `data.csv`:

| Old Column | New Column | Notes |
|-----------|-----------|-------|
| namaBarang | nama_barang | |
| satuan | satuan (in items.csv) | Use Unit code (e.g. `TAB`) |
| kategori | kategori (in items.csv) | Use Category code (e.g. `TABLET`) |
| batch | batch_lot (in stock.csv) | |
| ed | expiry_date (in stock.csv) | Format: `YYYY-MM-DD` |
| qty | quantity (in stock.csv) | |
| hargaSatuan | unit_price (in stock.csv) | |
| sumberDana | sumber_dana (in stock.csv) | Use FundingSource code |

## Error Handling

If import fails:

1. Check error message for specific row/field
2. Verify foreign key references exist (Unit, Category, Location, etc.)
3. Validate date formats (`YYYY-MM-DD`)
4. Ensure numeric fields don't have commas or currency symbols
5. CSV files must be **UTF-8** encoded

## Notes

- Test imports on development environment first
- Keep backup of original CSV files
- Excel can create CSVs but watch for encoding issues
- `django-import-export` supports dry-run preview before committing
- The `skip_unchanged` option is enabled — re-importing the same CSV is safe
