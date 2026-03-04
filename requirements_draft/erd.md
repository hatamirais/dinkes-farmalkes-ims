# Entity Relationship Diagram - Healthcare IMS

## ERD Diagram

```mermaid
erDiagram
    %% Lookup Tables
    Unit {
        int id PK
        string code UK "TAB, BTL, AMP"
        string name "Tablet, Botol, Ampul"
        text description NULL
        timestamp created_at
        timestamp updated_at
    }
    
    Category {
        int id PK
        string code UK "TABLET, INJEKSI, VAKSIN"
        string name "Display name"
        int sort_order
        timestamp created_at
        timestamp updated_at
    }
    
    FundingSource {
        int id PK
        string code UK "DAK, DAU, APBD"
        string name "Display name"
        text description NULL
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }
    
    Program {
        int id PK
        string code UK "TB, HIV, MALARIA"
        string name "Tuberkulosis"
        text description NULL
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }
    
    Location {
        int id PK
        string code UK "LOC-001"
        string name "Warehouse A"
        text description NULL
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }
    
    Supplier {
        int id PK
        string code UK
        string name
        text address NULL
        string phone NULL
        string email NULL
        text notes NULL
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }
    
    Facility {
        int id PK
        string code UK "PKM-001"
        string name "Puskesmas X"
        text address NULL
        string phone NULL
        string type "Puskesmas, RS, Clinic"
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }
    
    User {
        int id PK
        string username UK
        string email UK
        string password_hash
        string full_name
        string role "Admin, Kepala, Admin Umum, Petugas Gudang, Auditor"
        boolean is_active
        timestamp last_login NULL
        timestamp created_at
        timestamp updated_at
    }
    
    %% Core Tables
    Item {
        int id PK
        string kode_barang UK
        string nama_barang
        int satuan_id FK
        int kategori_id FK
        boolean is_program_item "P marker"
        int program_id FK NULL "TB, HIV, Kusta"
        decimal minimum_stock
        text description NULL
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }
    
    Stock {
        int id PK
        int item_id FK
        int location_id FK
        string batch_lot
        date expiry_date
        decimal quantity
        decimal reserved "For pending distributions"
        decimal unit_price
        int sumber_dana_id FK
        int receiving_ref_id FK NULL
        timestamp created_at
        timestamp updated_at
    }
    
    Transaction {
        int id PK
        string transaction_type "IN, OUT, ADJUST, RETURN"
        int item_id FK
        int location_id FK
        string batch_lot
        decimal quantity
        decimal unit_price NULL
        int sumber_dana_id FK NULL
        string reference_type "Receiving, Distribution, Adjustment, Recall, Expired"
        int reference_id "Polymorphic reference"
        int user_id FK
        text notes NULL
        timestamp created_at
    }
    
    %% Receiving Module
    Receiving {
        int id PK
        string receiving_type "PROCUREMENT, GRANT"
        string document_number UK
        date receiving_date
        int supplier_id FK NULL "For PROCUREMENT"
        string grant_origin NULL "Province, Ministry, Donation"
        string program NULL "For program items"
        int sumber_dana_id FK
        string status "Draft, Submitted, Verified"
        int created_by_id FK
        int verified_by_id FK NULL
        timestamp verified_at NULL
        text notes NULL
        timestamp created_at
        timestamp updated_at
    }
    
    ReceivingItem {
        int id PK
        int receiving_id FK
        int item_id FK
        decimal quantity
        string batch_lot
        date expiry_date
        decimal unit_price
        decimal total_price "quantity * unit_price"
        timestamp created_at
    }
    
    ReceivingDocument {
        int id PK
        int receiving_id FK
        string file_name
        string file_path
        string file_type
        int file_size
        timestamp uploaded_at
    }
    
    %% Distribution Module
    Distribution {
        int id PK
        string distribution_type "LPLPO, ALLOCATION, SPECIAL_REQUEST"
        string document_number UK
        date request_date
        int facility_id FK
        string program NULL "For program-specific"
        string status "Submitted, Verified, Prepared, Distributed, Rejected"
        int created_by_id FK
        int verified_by_id FK NULL
        int approved_by_id FK NULL
        timestamp verified_at NULL
        timestamp approved_at NULL
        date distributed_date NULL
        text notes NULL
        text ocr_text NULL "For Special Request"
        timestamp created_at
        timestamp updated_at
    }
    
    DistributionItem {
        int id PK
        int distribution_id FK
        int item_id FK
        decimal quantity_requested
        decimal quantity_approved NULL
        int stock_id FK NULL "Specific batch allocated"
        text notes NULL
        timestamp created_at
    }

      %% Recall Module
      Recall {
        int id PK
        string document_number UK
        date recall_date
        int supplier_id FK
        string status "Draft, Submitted, Verified, Completed"
        int created_by_id FK
        int verified_by_id FK NULL
        timestamp verified_at NULL
        text notes NULL
        timestamp created_at
        timestamp updated_at
      }

      RecallItem {
        int id PK
        int recall_id FK
        int item_id FK
        int stock_id FK
        decimal quantity
        text notes NULL "Alasan recall"
        timestamp created_at
      }

      %% Expired Module
      Expired {
        int id PK
        string document_number UK
        date report_date
        string status "Draft, Submitted, Verified, Disposed"
        int created_by_id FK
        int verified_by_id FK NULL
        timestamp verified_at NULL
        text notes NULL
        timestamp created_at
        timestamp updated_at
      }

      ExpiredItem {
        int id PK
        int expired_id FK
        int item_id FK
        int stock_id FK
        decimal quantity
        text notes NULL "Detail pemusnahan"
        timestamp created_at
      }
    
    %% Relationships - Lookup to Core
    Item ||--|| Unit : "has"
    Item ||--|| Category : "has"
    Item ||--o| Program : "belongs_to"
    Stock ||--|| Item : "tracks"
    Stock ||--|| Location : "stored_in"
    Stock ||--|| FundingSource : "funded_by"
    Stock ||--o| Receiving : "received_from"
    
    %% Transaction relationships
    Transaction ||--|| Item : "affects"
    Transaction ||--|| Location : "at"
    Transaction ||--o| FundingSource : "funded_by"
    Transaction ||--|| User : "created_by"
    
    %% Receiving relationships
    Receiving ||--|| FundingSource : "funded_by"
    Receiving ||--o| Supplier : "from"
    Receiving ||--|| User : "created_by"
    Receiving ||--o| User : "verified_by"
    Receiving ||--o{ ReceivingItem : "contains"
    Receiving ||--o{ ReceivingDocument : "has_documents"
    ReceivingItem ||--|| Item : "receives"
    
    %% Distribution relationships
    Distribution ||--|| Facility : "to"
    Distribution ||--|| User : "created_by"
    Distribution ||--o| User : "verified_by"
    Distribution ||--o| User : "approved_by"
    Distribution ||--o{ DistributionItem : "contains"
    DistributionItem ||--|| Item : "distributes"
    DistributionItem ||--o| Stock : "from_batch"

    %% Recall relationships
    Recall ||--|| Supplier : "to_supplier"
    Recall ||--|| User : "created_by"
    Recall ||--o| User : "verified_by"
    Recall ||--o{ RecallItem : "contains"
    RecallItem ||--|| Item : "recalls"
    RecallItem ||--|| Stock : "from_batch"

    %% Expired relationships
    Expired ||--|| User : "created_by"
    Expired ||--o| User : "verified_by"
    Expired ||--o{ ExpiredItem : "contains"
    ExpiredItem ||--|| Item : "disposes"
    ExpiredItem ||--|| Stock : "from_batch"
```

## Table Details

### Lookup Tables (Master Data)

#### 1. Unit

- **Purpose:** Standardized measurement units
- **Indexes:** `code` (unique)
- **Initial Data:** TAB, BTL, AMP, VIAL, STRIP, BOX, KG, LITER, etc.

#### 2. Category

- **Purpose:** Item classification for reporting and access control
- **Indexes:** `code` (unique), `sort_order`
- **Initial Data:** TABLET, KAPSUL, SIRUP, INJEKSI, INFUS, VAKSIN, SALEP, TETES, SUPPO, INHALER, ALKES, BMHP, NARKOTIKA, REAGENT

#### 3. FundingSource

- **Purpose:** Track budget allocation and accounting
- **Indexes:** `code` (unique)
- **Initial Data:** DAK, DAU, APBD, HIBAH, DONASI, etc.
- **Note:** Different batches of same item can have different funding sources

#### 4. Program

- **Purpose:** Track health program assignments (TB, HIV, Kusta)
- **Indexes:** `code` (unique)
- **Initial Data:** TB, HIV, KUSTA, MALARIA, etc.

#### 5. Location

- **Purpose:** Physical storage locations within warehouse
- **Indexes:** `code` (unique)
- **Note:** To be provided by client

#### 6. Supplier

- **Purpose:** Vendor management for procurement tracking
- **Indexes:** `code` (unique)

#### 6. Facility

- **Purpose:** Distribution destinations (Puskesmas, hospitals, clinics)
- **Indexes:** `code` (unique)
- **Note:** 20+ facilities in the system

#### 7. User

- **Purpose:** System authentication and authorization
- **Indexes:** `username` (unique), `email` (unique)
- **Roles:** Admin, Kepala Instalasi, Admin Umum, Petugas Gudang, Auditor

---

### Core Tables

#### 8. Item (Master Barang)

- **Purpose:** Central item registry
- **Indexes:**
  - `kode_barang` (unique)
  - `(kategori_id, is_program_item)` for filtering
  - Full-text search on `nama_barang`
- **Special Fields:**
  - `kode_barang`: Auto-generated as `ITM-YYYY-NNNNN` (or manually assigned)
  - `is_program_item` + `program` (FK to Program): For designated program items [P]
  - `minimum_stock`: Threshold for low stock alerts

#### 9. Stock (Persediaan)

- **Purpose:** Real-time inventory tracking by batch/location
- **Indexes:**
  - `(item_id, location_id, expiry_date)` for FEFO queries
  - `(item_id, location_id)` WHERE `quantity > 0` for available stock
  - `expiry_date` for expiry alerts
- **Key Fields:**
  - `quantity`: Current available stock
  - `reserved`: Stock allocated but not yet distributed (for workflow)
  - `batch_lot` + `expiry_date`: Critical for FEFO and compliance
  - `sumber_dana_id`: Per-batch funding tracking (same item, different funding)
- **Constraints:**
  - `CHECK (quantity >= 0)`
  - `CHECK (reserved >= 0)`
  - `CHECK (reserved <= quantity)`
- **Unique Constraint:** `(item_id, location_id, batch_lot, sumber_dana_id)` prevents duplicate stock entries

#### 10. Transaction

- **Purpose:** Immutable audit trail of all stock movements
- **Indexes:**
  - `(item_id, created_at DESC)` for stock cards
  - `(reference_type, reference_id)` for linking
  - `created_at` for date-range queries
- **Transaction Types:**
  - `IN`: Receiving
  - `OUT`: Distribution
  - `ADJUST`: Manual adjustments (stock opname)
  - `RETURN`: Returns from facilities
- **Polymorphic Reference:** `reference_type` + `reference_id` links to source document

---

### Receiving Module

#### 11. Receiving

- **Purpose:** Document incoming stock (procurement or grants)
- **Indexes:**
  - `document_number` (unique)
  - `(status, receiving_date)` for workflow queries
  - `supplier_id` for supplier reports
- **Types:**
  - `PROCUREMENT`: Via eKatalog with supplier
  - `GRANT`: From province/ministry/donations
- **Status Workflow:** Draft → Submitted → Verified
- **Verification:** Requires `verified_by_id` + `verified_at` timestamp

#### 12. ReceivingItem

- **Purpose:** Line items for each receiving document
- **Key Fields:**
  - `batch_lot` + `expiry_date`: Recorded at receiving time
  - `unit_price` + `total_price`: Financial tracking
- **Note:** When verified, creates `Stock` entries and `Transaction` records

#### 13. ReceivingDocument

- **Purpose:** Store supporting documents (eKatalog files, grant letters)
- **Storage:** Local filesystem under `/media/receiving/{receiving_id}/`
- **File Types:** PDF, images, Excel

---

### Distribution Module

#### 14. Distribution

- **Purpose:** Outbound stock requests and allocations
- **Indexes:**
  - `document_number` (unique)
  - `(facility_id, status, request_date)` for facility tracking
  - `status` for workflow queries
- **Types:**
  - `LPLPO`: Standard request from Puskesmas
  - `ALLOCATION`: Planned distribution (routine/special)
  - `SPECIAL_REQUEST`: Ad-hoc requests requiring approval
- **Status Workflow:**
  - LPLPO/Special: Submitted → Verified → Prepared → Distributed
  - Allocation: Draft → Approved → Distributed
- **OCR Field:** For Special Request proof document text extraction

#### 15. DistributionItem

- **Purpose:** Line items for distribution requests
- **Key Fields:**
  - `quantity_requested`: What facility asked for
  - `quantity_approved`: What was approved (can differ)
  - `stock_id`: Links to specific batch (FEFO selection)
- **Workflow:**
  1. Request created with `quantity_requested`
  2. Verification: Set `quantity_approved`, select `stock_id` (FEFO)
  3. Preparation: Update `Stock.reserved += quantity_approved`
  4. Distribution: Update `Stock.quantity -= quantity_approved`, `reserved -= quantity_approved`, create `Transaction`

#### 16. Recall

- **Purpose:** Return recalled items to supplier with auditable stock deduction
- **Indexes:**
  - `document_number` (unique)
  - `(status, recall_date)` for workflow queries
- **Status Workflow:** Draft → Submitted → Verified → Completed
- **Verification:** Deducts stock and creates `Transaction(type=OUT, reference_type=RECALL)`

#### 17. RecallItem

- **Purpose:** Line items for each recall document
- **Key Fields:**
  - `stock_id`: Exact batch to be recalled
  - `quantity`: Quantity deducted on verification

#### 18. Expired

- **Purpose:** Record expired stock disposal documents
- **Indexes:**
  - `document_number` (unique)
  - `(status, report_date)` for workflow queries
- **Status Workflow:** Draft → Submitted → Verified → Disposed
- **Verification:** Deducts stock and creates `Transaction(type=OUT, reference_type=EXPIRED)`

#### 19. ExpiredItem

- **Purpose:** Line items for each expired/disposal document
- **Key Fields:**
  - `stock_id`: Exact expired batch
  - `quantity`: Quantity deducted on verification

---

## Key Design Decisions

### 1. Why Sumber Dana in Stock, not Item?

Same item can come from different funding sources:

- Paracetamol Batch A (DAK): 1000 tablets
- Paracetamol Batch B (APBD): 500 tablets

Financial reports must track: "How much DAK money in current inventory?"

### 2. Stock Reservation Pattern

`reserved` field prevents double allocation:

```text
Available for new distributions = quantity - reserved
```

When distribution status = "Prepared", stock is reserved but not yet deducted.

### 3. Transaction as Audit Trail

Immutable log of all movements. Never delete, only add. Stock card = query transactions by item.

### 4. Polymorphic Reference

`reference_type` + `reference_id` allows transactions to link to Receiving, Distribution, Recall, Expired, or manual Adjustments without complex foreign keys.

### 7. Recall & Expired Verification Pattern

Verification is the stock-impacting checkpoint:

- Validates selected batch belongs to selected item
- Validates requested quantity does not exceed available stock
- Deducts `Stock.quantity`
- Creates immutable `Transaction(type=OUT)` rows with `reference_type=RECALL|EXPIRED`

### 5. FEFO Implementation

Query for distribution:

```sql
SELECT * FROM stock 
WHERE item_id = ? 
  AND location_id = ? 
  AND (quantity - reserved) > 0
ORDER BY expiry_date ASC, created_at ASC
LIMIT ?
```

### 6. Expiry Alert Logic

First day of expiry month = expired. Celery task runs daily:

```python
# Alert if expiring within 3 months
alert_date = today + timedelta(days=90)
expiring = Stock.objects.filter(
    expiry_date__lte=alert_date,
    quantity__gt=0
)
```

---

## Database Constraints & Indexes

### Critical Indexes

```sql
-- Stock table (most queried)
CREATE INDEX idx_stock_fefo ON stock(item_id, location_id, expiry_date) 
  WHERE quantity > 0;
CREATE INDEX idx_stock_expiry ON stock(expiry_date) 
  WHERE quantity > 0;
CREATE INDEX idx_stock_item_loc ON stock(item_id, location_id);

-- Transaction audit trail
CREATE INDEX idx_trans_item_date ON transaction(item_id, created_at DESC);
CREATE INDEX idx_trans_reference ON transaction(reference_type, reference_id);

-- Item search
CREATE INDEX idx_item_search ON item 
  USING gin(to_tsvector('indonesian', nama_barang));
CREATE INDEX idx_item_category ON item(kategori_id, is_program_item);

-- Distribution workflow
CREATE INDEX idx_dist_status ON distribution(status, request_date);
CREATE INDEX idx_dist_facility ON distribution(facility_id, request_date);
```

### Check Constraints

```sql
-- Stock non-negative
ALTER TABLE stock ADD CONSTRAINT chk_stock_quantity 
  CHECK (quantity >= 0);
ALTER TABLE stock ADD CONSTRAINT chk_stock_reserved 
  CHECK (reserved >= 0 AND reserved <= quantity);

-- Transaction quantity validation
ALTER TABLE transaction ADD CONSTRAINT chk_trans_quantity 
  CHECK (quantity != 0);
```

### Unique Constraints

```sql
-- Prevent duplicate stock entries
ALTER TABLE stock ADD CONSTRAINT uq_stock_batch 
  UNIQUE (item_id, location_id, batch_lot, sumber_dana_id);

-- Unique document numbers
ALTER TABLE receiving ADD CONSTRAINT uq_receiving_doc 
  UNIQUE (document_number);
ALTER TABLE distribution ADD CONSTRAINT uq_dist_doc 
  UNIQUE (document_number);
ALTER TABLE recalls ADD CONSTRAINT uq_recall_doc 
  UNIQUE (document_number);
ALTER TABLE expired_docs ADD CONSTRAINT uq_expired_doc 
  UNIQUE (document_number);
```

---

## Migration Strategy

### Phase 1: Lookup Tables

```python
# Create and populate lookup tables
1. Unit (seed data from constants)
2. Category (seed data from constants)
3. FundingSource (seed data from constants)
4. Program (seed data from constants)
5. Location (TBD by client)
6. Supplier (initially empty)
7. Facility (import from existing list)
8. User (create admin user)
```

### Phase 2: Core Tables

```python
8. Item (import from CSV - 414 items)
9. Stock (import from CSV with batch/expiry)
10. Transaction (generate initial IN transactions)
```

### Phase 3: Module Tables

```python
11-13. Receiving tables (empty, ready for use)
14-15. Distribution tables (empty, ready for use)
16-17. Recall tables (empty, ready for use)
18-19. Expired tables (empty, ready for use)
```

### CSV Import Logic

```python
# data.csv → Item + Stock
for row in csv:
    item, created = Item.objects.get_or_create(
        nama_barang=row['namaBarang'],
        defaults={
            'satuan': Unit.objects.get(code=row['satuan']),
            'kategori': Category.objects.get(code=row['kategori']),
        }
    )
    
    stock = Stock.objects.create(
        item=item,
        location=default_location,
        batch_lot=row['batch'],
        expiry_date=row['ed'],
        quantity=row['qty'],
        unit_price=row['hargaSatuan'],
        sumber_dana=FundingSource.objects.get(code=row['sumberDana']),
    )
    
    Transaction.objects.create(
        transaction_type='IN',
        item=item,
        location=default_location,
        batch_lot=row['batch'],
        quantity=row['qty'],
        unit_price=row['hargaSatuan'],
        sumber_dana_id=stock.sumber_dana_id,
        reference_type='INITIAL_IMPORT',
        reference_id=0,
        user=admin_user,
        notes='Initial data import'
    )
```

---

## Naming Conventions

- **Tables:** Singular, PascalCase (e.g., `Item`, `Stock`, `FundingSource`)
- **Fields:** snake_case (e.g., `kode_barang`, `expiry_date`)
- **Foreign Keys:** `{table}_id` (e.g., `item_id`, `sumber_dana_id`)
- **Timestamps:** Always `created_at`, `updated_at` where applicable
- **Boolean:** Prefix with `is_` (e.g., `is_active`, `is_program_item`)
- **Indexes:** `idx_{table}_{columns}` (e.g., `idx_stock_fefo`)

---

## Next Steps

1. ✅ ERD completed
2. ✅ ERD reviewed and approved
3. ✅ Django models created from ERD
4. ✅ Initial migrations written and applied
5. ✅ Seed lookup table data (via `django-import-export` in Django Admin)
6. ✅ CSV import via Django Admin (`django-import-export`)
7. ✅ Recall module implemented (models, views, forms, templates)
8. ✅ Expired module implemented (models, views, forms, templates)
9. ⬜ Define DRF serializers (if/when REST API is needed)
10. ⬜ Build API endpoints (if/when REST API is needed)
