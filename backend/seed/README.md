# Seed Data Templates

CSV templates for importing master data via Django Admin.

> [!NOTE]
> Seed CSV templates are intended for **master data + initial stock only**. Transactional modules (`receiving`, `distribution`, `recall`, `expired`) are operational documents and should be created via app workflow or Admin forms.

## Import Order (important!)

Import lookup tables first, then items that reference them:

1. `units.csv`
2. `categories.csv`
3. `funding_sources.csv`
4. `programs.csv` ← health programs (TB, HIV, etc.)
5. `locations.csv`
6. `suppliers.csv`
7. `facilities.csv`
8. `items.csv` ← requires units + categories + programs to exist first
9. `receiving.csv` ← creates receiving + stock + transactions (via Admin → Receivings → Import CSV)

> **Note:** For initial stock seeding, use `receiving.csv` instead of `stock.csv`.
> This creates proper audit trail (transactions + kartu stok) from day one.

## How to Import

1. Go to Django Admin → select a model (e.g., Units)
2. Click **Import** → choose CSV file, format = "csv"
3. Click **Submit** → review the dry-run preview
4. Click **Confirm Import** to commit

## Column Reference

### `code` Field Rules (all tables except items)

- **Any text** — letters, numbers, hyphens, underscores
- **Max 20 characters**
- **Must be unique** within its table
- Examples: `TAB`, `001`, `GD-01`, `TABLET`

---

### units.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `code` | ✅ Yes | — | Unique, max 20 chars |
| `name` | ✅ Yes | — | Display name |
| `description` | ❌ No | blank | |

### categories.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `code` | ✅ Yes | — | Unique, max 20 chars |
| `name` | ✅ Yes | — | Display name |
| `sort_order` | ❌ No | `0` | Controls dropdown order |

### funding_sources.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `code` | ✅ Yes | — | Unique, max 20 chars |
| `name` | ✅ Yes | — | |
| `description` | ❌ No | blank | |
| `is_active` | ❌ No | `1` | |

### locations.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `code` | ✅ Yes | — | Unique, max 20 chars |
| `name` | ✅ Yes | — | |
| `description` | ❌ No | blank | |
| `is_active` | ❌ No | `1` | |

### suppliers.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `code` | ✅ Yes | — | Unique, max 20 chars |
| `name` | ✅ Yes | — | |
| `address` | ❌ No | blank | |
| `phone` | ❌ No | blank | |
| `email` | ❌ No | blank | |
| `notes` | ❌ No | blank | |
| `is_active` | ❌ No | `1` | |

### facilities.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `code` | ✅ Yes | — | Unique, max 20 chars |
| `name` | ✅ Yes | — | |
| `address` | ❌ No | blank | |
| `phone` | ❌ No | blank | |
| `facility_type` | ❌ No | `PUSKESMAS` | Options: `PUSKESMAS`, `RS`, `CLINIC` |
| `is_active` | ❌ No | `1` | |

### programs.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `code` | ✅ Yes | — | Unique, max 20 chars (e.g. `TB`, `HIV`) |
| `name` | ✅ Yes | — | Display name (e.g. `Tuberkulosis`) |
| `description` | ❌ No | blank | |
| `is_active` | ❌ No | `1` | |

### items.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `nama_barang` | ✅ Yes | — | Item name (used as unique identifier for import) |
| `satuan` | ✅ Yes | — | Unit **code** (e.g. `TAB`) |
| `kategori` | ✅ Yes | — | Category **code** (e.g. `TABLET`) |
| `is_program_item` | ❌ No | `0` | `1` for program items |
| `program` | ❌ No | blank | Program **code** (e.g. `TB`, `HIV`) from programs table |
| `minimum_stock` | ❌ No | `0` | Low stock alert threshold |
| `description` | ❌ No | blank | |
| `is_active` | ❌ No | `1` | |

> **Note:** `kode_barang` is auto-generated as `ITM-00001`, `ITM-00002`, etc. You don't need to provide it.

### stock.csv

| Column | Required | Default | Notes |
| -------- | ---------- | --------- | ------- |
| `item_code` | ✅ Yes | — | Item **kode_barang** from items table |
| `location_code` | ✅ Yes | — | Location **code** from locations table |
| `batch_lot` | ✅ Yes | — | Batch/lot number |
| `expiry_date` | ✅ Yes | — | Format: `YYYY-MM-DD` |
| `quantity` | ❌ No | `0` | |
| `reserved` | ❌ No | `0` | Allocated for pending distributions |
| `unit_price` | ❌ No | `0` | |
| `sumber_dana_code` | ✅ Yes | — | Funding source **code** from funding_sources table |
