# Rencana Pengujian Modul `receiving`

## Tujuan

Memastikan modul `receiving` menangani seluruh alur masuk inventaris secara valid, menciptakan atau menginkrementasi `Stock` dengan benar, menghasilkan jejak audit `Transaction(IN)` yang akurat, dan menjaga dokumen workflow tetap aman dari transisi status yang tidak valid.

## Cakupan Yang Diuji

Komponen dalam cakupan plan ini:

- model `Receiving`
- model `ReceivingItem`
- model `ReceivingOrderItem`
- model `ReceivingDocument`
- model `ReceivingTypeOption`
- properti turunan seperti `receiving_type_label`, `remaining_quantity`, dan `total_price`
- `generate_document_number()` pada `Receiving`
- view `receiving_list`
- view `receiving_create`
- view `receiving_detail`
- view `receiving_plan_list`
- view `receiving_plan_create`
- view `receiving_plan_detail`
- view `receiving_plan_submit`
- view `receiving_plan_approve`
- view `receiving_plan_receive`
- view `receiving_plan_close`
- view `receiving_plan_close_items`
- endpoint `quick_create_supplier`
- endpoint `quick_create_funding_source`
- endpoint `quick_create_receiving_type`
- logika pembuatan `Stock` dan `Transaction(IN)` saat receiving terverifikasi
- admin CSV import untuk `Receiving` dan `ReceivingItem`

## Di Luar Cakupan

Di luar plan ini:

- workflow distribution secara penuh
- CRUD admin penuh untuk master data items, location, atau funding source
- laporan dan agregasi dashboard dari data receiving
- template styling dan visual presentation

## Modul Terkait dan Dependency

Modul terkait yang perlu diperhatikan saat menyusun pengujian:

- `items`: `Item`, `Supplier`, `FundingSource`, dan `Location` sebagai referensi utama
- `stock`: `Stock` dan `Transaction` sebagai target efek samping saat receiving diverifikasi
- `users`: autentikasi, role, dan module scope sebagai penjaga akses
- `core`: decorator `perm_required` dan `module_scope_required`

Dependency teknis utama:

- transaksi database atomik untuk operasi verifikasi receiving
- `select_for_update()` untuk guard duplikat verifikasi
- formset inline untuk `ReceivingItem` dan `ReceivingOrderItem`
- `setUpTestData()` untuk fixture master reference yang mahal dibuat ulang
- unique constraint pada `document_number` di `Receiving`

## Risiko Bisnis

### Risiko Kritis

1. Stock tidak bertambah atau bertambah dengan nilai yang salah saat receiving diverifikasi.
2. `Transaction(IN)` tidak dibuat atau dibuat dengan quantity, batch, atau referensi dokumen yang salah.
3. CSV import menciptakan record tidak konsisten atau melewati validasi yang harusnya gagal.
4. Rollback tidak terjadi saat proses verifikasi gagal di tengah jalan, meninggalkan state parsial.

### Risiko Tinggi

1. Planned receiving status transition salah, seperti `APPROVED` langsung ke `RECEIVED` tanpa submit.
2. Regular receiving dibuat sebagai `VERIFIED` tetapi stock increment tidak terjadi.
3. `ReceivingTypeOption` nonaktif masih bisa dipilih di form.
4. `quick_create_supplier` atau `quick_create_funding_source` dapat dibuat oleh user tanpa scope yang cukup.
5. Nomor dokumen `RCV-YYYY-NNNNN` tidak unik atau formatnya salah.

### Risiko Menengah

1. `remaining_quantity` pada `ReceivingOrderItem` menghitung nilai negatif atau melebihi `planned_quantity`.
2. `receiving_type_label` fallback ke tipe kustom tidak berjalan ketika built-in choices tidak cocok.
3. Filter dan pagination list view menyembunyikan data secara tidak konsisten.
4. Admin import tidak menulis `Transaction(IN)` saat dipakai untuk initial stock seeding.

## Tingkat Pengujian

### Tingkat 1: Pengujian Model dan Aturan

Fokus:

- pembangkitan nomor dokumen
- properti turunan pada `Receiving` dan `ReceivingOrderItem`
- tipe kustom label resolution
- constraint dan validasi model dasar

### Tingkat 2: Pengujian Workflow

Fokus:

- regular receiving: create, detail, verify
- planned receiving: create, submit, approve, receive, close
- guard terhadap transisi status invalid

### Tingkat 3: Pengujian Side Effect Stok dan Transaksi

Fokus:

- stock creation bila batch belum ada
- stock increment bila batch sudah ada
- `Transaction(IN)` creation per line item
- atomisitas dan rollback saat verifikasi gagal

### Tingkat 4: Pengujian Impor

Fokus:

- CSV import jalur berhasil menulis receiving, items, stock, dan transaction
- baris dengan field kosong atau tidak valid ditolak dengan pesan yang jelas
- duplicate document number ditangani dengan benar
- import admin hanya dapat diakses oleh user dengan scope cukup

### Tingkat 5: Pengujian View dan Akses

Fokus:

- list, search, dan filter view
- pagination
- permission dan scope access control
- quick-create supplier, funding source, dan receiving type

## Matriks Skenario

### A. Document Number Generation

Prioritas: Tinggi

1. `generate_document_number()` menghasilkan format `RCV-YYYY-NNNNN`.
2. Save tanpa `document_number` mengisi otomatis dengan nomor yang benar.
3. `document_number` kedua dalam tahun yang sama menginkrementasi sekuensial.
4. Nomor tidak duplikat meskipun dua receiving dibuat dalam satu request bersamaan.

### B. Receiving Model Properties

Prioritas: Tinggi

1. `receiving_type_label` mengembalikan label built-in untuk type standar.
2. `receiving_type_label` mengembalikan nama custom dari `ReceivingTypeOption` aktif bila type bukan built-in.
3. `receiving_type_label` kembali ke nilai mentah `receiving_type` bila tipe kustom tidak ditemukan.
4. `ReceivingItem.total_price` mengembalikan `quantity * unit_price` dengan benar.
5. `ReceivingOrderItem.remaining_quantity` mengembalikan `planned_quantity - received_quantity` bila positif.
6. `ReceivingOrderItem.remaining_quantity` mengembalikan `0` bila `received_quantity >= planned_quantity`.
7. `ReceivingOrderItem.remaining_quantity` mengembalikan `0` bila `is_cancelled`.

### C. Regular Receiving Create

Prioritas: Kritis

1. User dengan scope `OPERATE` dapat membuat regular receiving dengan minimal satu item valid.
2. Receiving dibuat langsung dengan status `VERIFIED`.
3. Stock dinaikkan sesuai quantity untuk setiap item pada receiving yang terverifikasi.
4. `Transaction(IN)` dibuat per item dengan `reference_type`, `reference_id`, dan `reference_number` yang benar.
5. Line item dengan quantity kosong atau nol tidak membuat row receiving item.
6. Receiving gagal dibuat bila semua item tidak valid.
7. User tanpa scope yang cukup ditolak dengan status 403.
8. Receiving dengan item nonaktif ditolak.

### D. Stock Creation and Increment Side Effects

Prioritas: Kritis

1. Verifikasi receiving membuat `Stock` baru bila tuple `(item, location, batch_lot, sumber_dana)` belum ada.
2. Verifikasi receiving menginkrementasi `Stock.quantity` bila tuple sudah ada.
3. Setiap item receiving menghasilkan tepat satu `Transaction` dengan `type=IN`.
4. `Transaction.quantity`, `Transaction.batch_lot`, `Transaction.expiry_date`, dan `Transaction.unit_price` sesuai item receiving.
5. `Transaction.reference_number` sesuai `document_number` receiving.
6. Kegagalan pada satu item membatalkan seluruh operasi atomik dan tidak mengubah stok apapun.

### E. Planned Receiving Workflow

Prioritas: Tinggi

1. User dengan scope `OPERATE` dapat membuat planned receiving dengan status awal `DRAFT`.
2. Planned receiving dapat di-submit ke status `SUBMITTED`.
3. User dengan scope `APPROVE` dapat meng-approve planned receiving ke status `APPROVED`.
4. `APPROVED` receiving dapat di-receive menghasilkan `RECEIVED` atau `PARTIAL`.
5. `PARTIAL` receiving dapat menerima batch berikutnya hingga menjadi `RECEIVED`.
6. Planned receiving dapat di-close dengan alasan dan mengubah status ke `CLOSED`.
7. Transisi langsung dari `DRAFT` ke `APPROVED` tanpa submit ditolak.
8. Transisi dari `RECEIVED` ke status manapun ditolak.
9. Stock dan `Transaction(IN)` dibuat saat planned receiving menerima item aktual.
10. `remaining_quantity` pada `ReceivingOrderItem` berkurang setelah item diterima.

### F. Status Transition Guards

Prioritas: Tinggi

1. Submit planned receiving dari non-`DRAFT` ditolak.
2. Approve planned receiving dari non-`SUBMITTED` ditolak.
3. Receive planned receiving dari non-`APPROVED` ditolak.
4. Close planned receiving dari `RECEIVED` ditolak.
5. Action oleh user yang tidak memiliki scope yang diperlukan ditolak.

### G. CSV Import

Prioritas: Tinggi

1. Import CSV valid membuat `Receiving`, `ReceivingItem`, menginkrementasi `Stock`, dan menulis `Transaction(IN)`.
2. Import CSV dengan baris quantity kosong menghasilkan error pada baris tersebut.
3. Import CSV dengan kode item tidak dikenal ditolak dengan pesan error yang jelas.
4. Import CSV dengan `document_number` duplikat ditolak.
5. Dry-run mode menampilkan preview tanpa menyimpan data.
6. Import admin hanya dapat diakses oleh superuser atau user dengan scope `MANAGE`.

### H. List, Filter, and Search Views

Prioritas: Tinggi

1. `receiving_list` menampilkan dokumen receiving reguler terurut terbaru.
2. Filter status bekerja untuk setiap nilai status yang valid.
3. Search bekerja untuk `document_number`, nama supplier, dan tanggal.
4. Pagination `25 per page` bekerja untuk boundary 25 dan 26 baris.
5. `receiving_plan_list` hanya menampilkan planned receiving.

### I. Quick-Create Endpoints

Prioritas: Menengah

1. `quick_create_supplier` membuat supplier baru dan mengembalikan id serta nama.
2. `quick_create_funding_source` membuat sumber dana baru dan mengembalikan id serta nama.
3. `quick_create_receiving_type` membuat `ReceivingTypeOption` baru dan mengembalikan code serta name.
4. Supplier dengan nama duplikat ditolak dengan pesan error.
5. Endpoint ditolak bagi user tanpa scope yang cukup.
6. Non-POST request ke endpoint mengembalikan status error yang sesuai.

### J. Permission and Scope Access

Prioritas: Kritis

1. User tidak login diarahkan ke halaman login dari semua view.
2. User dengan scope `VIEW` dapat mengakses list dan detail, tetapi tidak dapat create atau approve.
3. User dengan scope `OPERATE` dapat create receiving tetapi tidak dapat approve planned receiving.
4. User dengan scope `APPROVE` dapat approve planned receiving.
5. Superuser dapat mengakses semua view tanpa memerlukan permission khusus.

## Strategi Data Uji

Gunakan data minimal tetapi representatif:

- 1 superuser
- 1 user dengan scope `OPERATE` untuk receiving
- 1 user dengan scope `APPROVE` untuk planned receiving
- 1 user dengan scope `VIEW` untuk validasi akses baca saja
- 1 user tanpa akses receiving untuk validasi deny-path
- 2 item aktif dengan batch yang berbeda
- 1 item nonaktif untuk jalur gagal
- 2 lokasi aktif
- 1 funding source utama
- 1 supplier aktif
- contoh `ReceivingTypeOption` aktif dan nonaktif untuk label resolution test

Prinsip data:

- Gunakan `setUpTestData()` untuk master reference yang tidak berubah lintas test.
- Gunakan `setUp()` hanya untuk state yang dimutasi oleh test tertentu.
- Pisahkan fixture workflow tests dari fixture model tests agar debugging lebih mudah.
- Gunakan data sekecil mungkin tetapi tetap cukup untuk memverifikasi perhitungan stok dan transaksi.

## Struktur File Test Yang Direkomendasikan

```text
backend/apps/receiving/tests/
|- test_models.py
|- test_regular_receiving_workflow.py
|- test_planned_receiving_workflow.py
|- test_stock_transaction_effects.py
|- test_import.py
|- test_list_views.py
`- test_access_control.py
```

## Kriteria Masuk

Rencana ini siap dieksekusi bila:

- app `receiving` sudah termigrasi penuh
- modul `stock`, `items`, dan `users` sudah memiliki cakupan dasar yang stabil
- fixture dasar item, lokasi, funding source, supplier, dan user sudah bisa dibuat konsisten
- tidak ada migration pending yang mempengaruhi model `receiving` atau `stock`

## Kriteria Selesai

Modul `receiving` dianggap memenuhi rencana dasar ini bila:

- semua critical scenario punya automated test
- minimal 80 persen high-priority scenario punya automated test
- setiap receiving path yang mengubah stok memiliki assertion `Stock.quantity` dan `Transaction`
- CSV import memiliki test jalur berhasil dan cakupan baris tidak valid
- transisi status invalid diblokir dan diuji

## Urutan Pelaksanaan Yang Direkomendasikan

1. `test_models.py`
2. `test_stock_transaction_effects.py`
3. `test_regular_receiving_workflow.py`
4. `test_planned_receiving_workflow.py`
5. `test_import.py`
6. `test_list_views.py`
7. `test_access_control.py`
