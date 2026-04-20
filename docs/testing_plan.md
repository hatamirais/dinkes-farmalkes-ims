# Rencana Pengujian

Dokumen ini menetapkan rencana pengujian bertahap untuk Healthcare IMS berdasarkan kondisi test suite saat ini, area risiko operasional, dan pola arsitektur aplikasi Django di repositori ini.

## Tujuan

- Menjaga integritas stok dan `Transaction` sebagai audit trail imutabel.
- Memastikan workflow dokumen hanya berubah melalui transisi status yang sah.
- Menutup gap pada permission, signal, report, dan proses administrasi yang berisiko tinggi.
- Menstandarkan pola penulisan test agar lebih mudah dirawat saat model dan workflow berkembang.

## Baseline Saat Ini

Kondisi test suite saat dokumen ini dibuat:

- Sudah ada test per app di hampir semua modul utama.
- Cakupan relatif kuat di `distribution`, `receiving`, `lplpo`, `puskesmas`, `users`, `expired`, dan `recall`.
- Cakupan masih lemah di `items`, `stock`, dan `stock_opname`.
- Modul `reports` belum memiliki test yang berarti.
- Banyak setup data masih duplikatif antar file test.

## Prinsip Prioritas

Urutan prioritas pengujian mengikuti risiko bisnis dan risiko data:

1. Mutasi stok dan konsistensi `Transaction`.
2. Workflow dokumen dan guard status transition.
3. Permission, facility isolation, dan decorator access control.
4. Signal dan automation lintas modul.
5. Report, export, print, dan filter list view.
6. Validasi form, UX AJAX, dan soft-delete behavior.

## Strategi Suite

### 1. Unit Tests

Fokus pada:

- method model
- property turunan
- validator
- helper/service function
- signal behavior yang dapat diisolasi

Target utama:

- `apps.items`
- `apps.stock`
- `apps.users`
- `apps.core`

### 2. Integration Tests

Fokus pada:

- transisi workflow end-to-end
- perubahan stok lintas model
- penulisan `Transaction`
- guard permission dan redirect/403
- sinkronisasi antar app seperti `distribution -> lplpo`

Target utama:

- `apps.receiving`
- `apps.distribution`
- `apps.recall`
- `apps.expired`
- `apps.stock_opname`
- `apps.lplpo`
- `apps.puskesmas`

### 3. Regression Tests

Setiap bug yang menyentuh:

- quantity stock
- batch/expiry
- settlement RS
- scope fasilitas
- status workflow

harus disertai test reproduksi sebelum atau bersama fix.

## Fase Implementasi

## Fase 1: Fondasi dan Risiko Kritis

Target durasi: 1 sampai 2 minggu

Fokus:

- Konsolidasi pola fixture test.
- Menutup gap pada signal dan stock transfer.
- Menetapkan baseline command untuk CI lokal.

Pekerjaan:

1. Tambah shared test helpers atau factory untuk `User`, `Item`, `Stock`, `Facility`, `FundingSource`, dan `Location`.
2. Tambah test signal `users` untuk sinkronisasi role/group dan `is_staff`.
3. Tambah test signal atau automation `lplpo` saat `Distribution` mencapai `DISTRIBUTED`.
4. Tambah test workflow `stock transfer` termasuk pasangan `Transaction(OUT)` dan `Transaction(IN)`.
5. Refactor test yang masih memakai setup duplikatif berat ke `setUpTestData()` bila fixture tidak dimutasi.

Definition of done:

- Tidak ada workflow stok utama tanpa minimal satu test sukses dan satu test gagal.
- Signal lintas modul yang mengubah status atau hak akses memiliki coverage dasar.

## Fase 2: Workflow Bernilai Tinggi

Target durasi: 1 sampai 2 minggu

Fokus:

- Memperdalam workflow receiving dan distribution bernilai tinggi.
- Menutup gap pada decorator permission.

Pekerjaan:

1. Tambah test workflow receiving reguler dan planned receiving sampai efek stok serta transaksi tervalidasi.
2. Tambah test workflow distribution sampai aksi verify, prepare, distribute, reset, reject, dan close tervalidasi.
3. Tambah test `@login_required` + `@perm_required` untuk kombinasi superuser, Django permission, module scope, dan deny path.
4. Tambah test `Stock.available_quantity` dan perilaku FEFO untuk pilihan batch distribusi.
5. Tambah negative-path test untuk guard status dan permission pada receiving, distribution, recall, dan expired.

Definition of done:

- Setiap alur dokumen dengan dampak stok memiliki test success path dan guard path.
- Access control penting tidak hanya diuji dari view tertentu, tetapi juga dari decorator/permission behavior secara langsung.

## Fase 3: Reporting dan Rekonsiliasi

Target durasi: 1 sampai 2 minggu

Fokus:

- Menutup blind spot pada report, stock opname, dan list filtering.

Pekerjaan:

1. Tambah smoke test dan data-accuracy test untuk modul `reports`.
2. Tambah test `stock_opname` untuk create, progress, completion, dan discrepancy output.
3. Tambah test list view untuk pagination, filter status, filter tipe dokumen, dan pencarian.
4. Tambah test export/print yang menghasilkan response valid dan context data yang benar.

Definition of done:

- `reports` tidak lagi kosong dari test.
- `stock_opname` tidak lagi hanya diuji dari sisi akses.

## Fase 4: Ketahanan dan Konsistensi Lintas Modul

Target durasi: 1 sampai 2 minggu

Fokus:

- Soft-delete, concurrency, dan edge-case validation.

Pekerjaan:

1. Tambah cross-app test untuk memastikan entitas `is_active=False` tidak muncul di selector, typeahead, workflow, dan report.
2. Tambah test untuk skenario stok mepet atau modifikasi bersamaan pada distribusi.
3. Tambah test form validation untuk nested formset dan mismatch FK.
4. Tambah regression test untuk seluruh bug workflow yang ditemukan selama fase sebelumnya.

Definition of done:

- Perilaku soft-delete konsisten di modul utama.
- Skenario race dan over-allocation minimal memiliki guard test pada service atau workflow yang relevan.

## Prioritas Per App

### Prioritas Tinggi

- `apps.stock`: stock transfer, reservation, available quantity, transaction pairing.
- `apps.reports`: smoke test, data accuracy, export/print behavior.
- `apps.stock_opname`: workflow lengkap dan discrepancy logic.
- `apps.distribution`: RS settlement dan edge-case stock posting.
- `apps.receiving`: receiving return RS, partial receiving, rollback guard.

### Prioritas Menengah

- `apps.items`: soft delete visibility, item business rules, lookup normalization tambahan.
- `apps.core`: decorator chain, context processor, shared utilities.
- `apps.users`: module scope fallback, sync role/group regression.

### Prioritas Pemeliharaan

- `apps.expired`, `apps.recall`, `apps.lplpo`, `apps.puskesmas`: tambah regression test saat ada perubahan workflow atau bug baru.

## Standar Penulisan Test

- Gunakan `TestCase.setUpTestData()` untuk fixture bersama yang tidak dimutasi.
- Gunakan `setUp()` hanya untuk state yang harus segar di setiap test.
- Hindari hardcoded setup duplikatif jika helper/factory dapat dipakai ulang.
- Nama test harus menjelaskan perilaku bisnis, bukan sekadar method yang dipanggil.
- Setiap transisi status minimal punya test:
  - transisi valid
  - transisi tidak valid
  - dampak stok atau audit trail bila ada
- Untuk bugfix, tulis regression test yang gagal tanpa fix dan lulus setelah fix.

## Command Eksekusi

Metode utama di Windows dari root repo:

```powershell
.\scripts\run-django-test.ps1 -Target apps.items
.\scripts\run-django-test.ps1 -Target apps.distribution
.\scripts\run-django-test.ps1 -Target apps.receiving
```

Menjalankan beberapa target secara berurutan:

```powershell
.\scripts\run-django-test.ps1 -Target apps.stock,apps.distribution,apps.receiving
```

Dari direktori `backend/`:

```bash
python manage.py test
python manage.py test apps.stock
python manage.py test apps.distribution
python manage.py test apps.reports
```

## Cadence Kerja Yang Disarankan

- Saat menyentuh workflow dokumen, jalankan minimal test app terkait sebelum dan sesudah perubahan.
- Saat menyentuh model stok atau transaksi, jalankan `apps.stock`, `apps.distribution`, `apps.receiving`, `apps.recall`, dan `apps.expired`.
- Saat menyentuh permission atau role, jalankan `apps.users`, `apps.core`, `apps.puskesmas`, dan `apps.lplpo`.
- Tambahkan target CI bertahap dimulai dari smoke suite modul kritis, lalu meluas per fase.

## Ukuran Keberhasilan

Rencana ini dianggap berhasil bila:

- modul berisiko tinggi tidak lagi memiliki blind spot utama
- bug workflow baru hampir selalu datang bersama regression test
- perubahan lintas app lebih cepat diverifikasi karena fixture test sudah terkonsolidasi
- confidence terhadap mutasi stok, permission, dan report meningkat tanpa perlu uji manual penuh untuk setiap perubahan
