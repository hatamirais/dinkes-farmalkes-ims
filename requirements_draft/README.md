# CSV Import Templates

This directory contains CSV templates for importing initial data into the Healthcare IMS.

## Template Files

### Lookup Tables (Import First)
1. **lookup_units.csv** - Measurement units (TAB, BTL, AMP, etc.)
2. **lookup_categories.csv** - Item categories (TABLET, INJEKSI, VAKSIN, etc.)
3. **lookup_funding_sources.csv** - Funding sources (DAK, DAU, APBD, etc.)
4. **lookup_locations.csv** - Storage locations (customize with actual warehouse layout)
5. **lookup_facilities.csv** - Puskesmas and hospitals (customize with actual facility list)

### Core Data (Import After Lookups)
6. **initial_stock_import.csv** - Initial inventory with items and stock
7. **distribution_request_import.csv** - Bulk import distribution requests (optional)

## Import Order

**CRITICAL: Import in this exact order to satisfy foreign key dependencies**

```bash
# Step 1: Lookup tables
python manage.py import_lookup_data unit templates/lookup_units.csv
python manage.py import_lookup_data category templates/lookup_categories.csv
python manage.py import_lookup_data funding_source templates/lookup_funding_sources.csv
python manage.py import_lookup_data location templates/lookup_locations.csv
python manage.py import_lookup_data facility templates/lookup_facilities.csv

# Step 2: Core data (creates Item + Stock + Transaction)
python manage.py import_initial_stock templates/initial_stock_import.csv

# Step 3: Distribution requests (optional)
python manage.py import_distribution_requests templates/distribution_request_import.csv
```

## Field Specifications

### initial_stock_import.csv

| Field | Required | Format | Notes |
|-------|----------|--------|-------|
| kode_barang | No | String | Auto-generated if empty |
| nama_barang | Yes | String | Item name |
| satuan_code | Yes | String | Must exist in Unit table |
| kategori_code | Yes | String | Must exist in Category table |
| is_program_item | Yes | TRUE/FALSE | Case insensitive |
| program_name | No | String | Required if is_program_item=TRUE |
| minimum_stock | Yes | Number | Threshold for alerts |
| location_code | Yes | String | Must exist in Location table |
| batch_lot | Yes | String | Batch/lot number |
| expiry_date | Yes | YYYY-MM-DD | Expiry date |
| quantity | Yes | Number | Must be > 0 |
| unit_price | Yes | Number | Unit price in IDR |
| sumber_dana_code | Yes | String | Must exist in FundingSource table |

**Validation Rules:**
- Same `kode_barang` + different batch = separate rows (multiple stock entries)
- If `kode_barang` is empty, system generates: `{kategori_code}-{sequential_number}`
- All foreign key codes must exist in their respective lookup tables

### distribution_request_import.csv

| Field | Required | Format | Notes |
|-------|----------|--------|-------|
| document_number | Yes | String | Groups items into one distribution |
| distribution_type | Yes | LPLPO / ALLOCATION / SPECIAL_REQUEST | |
| request_date | Yes | YYYY-MM-DD | Request date |
| facility_code | Yes | String | Must exist in Facility table |
| program | No | String | Program name (typically for ALLOCATION) |
| kode_barang | Yes | String | Must exist in Item table |
| quantity_requested | Yes | Number | Must be > 0 |
| notes | No | String | Item-specific notes |

**Validation Rules:**
- Multiple rows with same `document_number` = single Distribution with multiple items
- Initial status = "Submitted" (requires verification workflow)
- Does NOT allocate stock automatically (requires manual batch selection)

## Customization Guide

### For Client: Update These Files

1. **lookup_locations.csv**
   - Replace placeholder locations with actual warehouse layout
   - Use codes like: LOC-001, LOC-002, etc.

2. **lookup_facilities.csv**
   - Add all 20+ Puskesmas and healthcare facilities
   - Ensure codes match existing facility codes if migrating from old system

3. **initial_stock_import.csv**
   - Replace sample data with actual inventory from existing data.csv
   - Map old column names to new template format:
     - `namaBarang` → `nama_barang`
     - `satuan` → `satuan_code` (lookup from Unit table)
     - `kategori` → `kategori_code` (lookup from Category table)
     - `batch` → `batch_lot`
     - `ed` → `expiry_date` (format: YYYY-MM-DD)
     - `qty` → `quantity`
     - `hargaSatuan` → `unit_price`
     - `sumberDana` → `sumber_dana_code` (lookup from FundingSource table)

## Error Handling

If import fails:
1. Check error message for specific row/field
2. Verify foreign key references exist (Unit, Category, Location, etc.)
3. Validate date formats (YYYY-MM-DD)
4. Ensure numeric fields don't have commas or currency symbols
5. Check boolean fields use TRUE/FALSE (not Yes/No or 1/0)

## Rollback

If you need to undo an import:
```bash
# Delete all data (DESTRUCTIVE - use only in development)
python manage.py flush

# Then re-run migrations and imports
python manage.py migrate
# ... run import commands again
```

## Notes

- CSV files must be UTF-8 encoded
- Excel can create CSVs but watch for encoding issues
- Test imports on development environment first
- Keep backup of original CSV files
- Import creates audit trail in Transaction table
