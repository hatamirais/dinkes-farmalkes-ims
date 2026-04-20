# Rencana Pengujian Modul `distribution`

## Tujuan

Memastikan modul `distribution` mengelola seluruh alur stok keluar secara aman dan konsisten, menegakkan guard transisi status dokumen, mengurangi `Stock` hanya pada checkpoint yang benar, dan menghasilkan `Transaction(OUT)` yang akurat.

## Cakupan Yang Diuji

Komponen dalam cakupan plan ini:

- model `Distribution`
- model `DistributionItem`
- model `DistributionStaffAssignment`
- `save()` pada `Distribution` untuk pembangkitan `document_number`
- form `DistributionForm`
- form `DistributionItemForm`
- `DistributionItemFormSet`
- helper `sync_distribution_staff_assignments`
- seluruh service workflow di `apps.distribution.services`
- view `distribution_list`
- view `distribution_create`
- view `distribution_edit`
- view `distribution_detail`
- view action `distribution_submit`
- view action `distribution_verify`
- view action `distribution_prepare`
- view action `distribution_distribute`
- view action `distribution_reject`
- view action `distribution_reset_to_draft`
- view action `distribution_step_back`
- view action `distribution_delete`
- interaksi langsung dengan `Stock` dan `Transaction` saat distribusi dilakukan
- kontrak integrasi dengan `lplpo` untuk distribusi tipe `LPLPO`

## Di Luar Cakupan

Di luar plan ini:

- implementasi detail workflow `receiving`
- pengujian penuh perhitungan dan finalisasi `lplpo`, selain relasi serta dampak distribusi yang dihasilkan
- pengujian laporan dan dashboard agregat dari data distribusi
- styling template dan perilaku JavaScript typeahead di level visual browser end-to-end
- pengujian lengkap admin Django untuk seluruh master data pendukung

## Modul Terkait dan Dependency

Modul terkait yang perlu diperhatikan saat menyusun pengujian:

- `stock`: sumber batch, `available_quantity`, pengurangan `Stock.quantity`, dan pencatatan `Transaction(OUT)`
- `items`: `Item`, `Facility`, `Location`, `FundingSource`, `Unit`, dan validitas referensi master data
- `users`: autentikasi, role, dan `ModuleAccess` untuk guard permission dan approval scope
- `core`: decorator `perm_required` dan `module_scope_required`
- `lplpo`: relasi distribusi hasil finalisasi LPLPO terhadap dokumen distribusi tipe `LPLPO`

Dependency teknis utama:

- transaksi database atomik pada `execute_stock_distribution`
- locking melalui `select_for_update()` saat distribusi stok
- formset inline untuk line item distribusi
- properti `Stock.available_quantity` sebagai dasar validasi stok
- field snapshot `issued_batch_lot`, `issued_expiry_date`, `issued_unit_price`, dan `issued_sumber_dana` pada `DistributionItem`

## Risiko Bisnis

### Risiko Kritis

1. Stok berkurang pada status yang salah, misalnya saat verifikasi atau persiapan, bukan saat distribusi final.
2. `Stock.quantity` berkurang lebih besar atau lebih kecil dari `quantity_approved`, sehingga saldo inventaris tidak akurat.
3. `Transaction(OUT)` tidak tercatat, tercatat ganda, atau memakai item, batch, nilai, atau referensi dokumen yang salah.
4. Snapshot batch dan harga pada `DistributionItem` tidak tersalin dari stok aktual, sehingga audit trail menjadi salah.

### Risiko Tinggi

1. User tanpa scope approval dapat memverifikasi atau menolak distribusi.
2. Distribusi bisa diajukan tanpa item atau tanpa petugas yang ditugaskan.
3. Distribusi bisa diverifikasi atau didistribusikan dengan batch stok yang tidak sesuai item.
4. Guard `step_back`, `reset_to_draft`, atau `delete` mengizinkan perubahan pada dokumen yang seharusnya tidak boleh diubah lagi.

### Risiko Menengah

1. `document_number` `DIST-YYYYMM-XXXXX` tidak unik atau tidak berurutan.
2. Filter, search, dan pagination pada list view menampilkan dokumen yang tidak sesuai.
3. Sinkronisasi `staff_assignments` tidak menghapus penugasan lama atau membuat duplikasi.

## Tingkat Pengujian

### Tingkat 1: Pengujian Model dan Relasi

Fokus:

- pembangkitan `document_number`
- integritas relasi `DistributionItem`
- uniqueness pada `DistributionStaffAssignment`

### Tingkat 2: Pengujian Form dan Validasi Input

Fokus:

- validasi kecocokan `stock.item` dengan `item`
- validasi quantity positif
- filtering batch FEFO dan hanya batch dengan `available_quantity > 0`
- sinkronisasi assigned staff pada create dan edit

### Tingkat 3: Pengujian Workflow Dokumen

Fokus:

- alur `DRAFT -> SUBMITTED -> VERIFIED -> PREPARED -> DISTRIBUTED`
- rejection path
- `step_back`
- `reset_to_draft`
- delete restriction

### Tingkat 4: Pengujian Side Effect Stok dan Audit Trail

Fokus:

- pengurangan stok saat `DISTRIBUTED`
- satu `Transaction(OUT)` per line item
- snapshot batch dan harga pada `DistributionItem`
- rollback penuh bila satu item gagal diproses

### Tingkat 5: Pengujian Integrasi Antar Modul

Fokus:

- relasi `lplpo_source`
- dampak distribusi terhadap dokumen hilir yang mengandalkan distribusi selesai

## Matriks Skenario

### A. Document Number dan Properti Header

Prioritas: Tinggi

1. Save tanpa `document_number` menghasilkan format `DIST-YYYYMM-XXXXX`.
2. Nomor dokumen berikutnya meningkat sekuensial dalam bulan yang sama.
3. `Distribution.__str__()` menampilkan kombinasi nomor dokumen dan fasilitas.

### B. Staff Assignment dan Integritas Relasi

Prioritas: Tinggi

1. `DistributionStaffAssignment` menolak duplikasi pasangan distribusi-user.
2. `sync_distribution_staff_assignments` menambah assignment baru yang belum ada.
3. `sync_distribution_staff_assignments` menghapus assignment lama yang tidak lagi dipilih.
4. Create distribution menyimpan daftar petugas sesuai input form.
5. Edit distribution memperbarui assignment tanpa menyisakan duplikasi.

### C. Form Validation dan Input Guard

Prioritas: Tinggi

1. `DistributionItemForm` menolak batch stok yang item-nya tidak sama dengan item pada line.
2. `DistributionItemForm` menolak `quantity_requested <= 0`.
3. Field batch hanya menampilkan stok dengan `available_quantity > 0` dan urutan FEFO.

### D. Workflow Distribusi Reguler

Prioritas: Kritis

1. Draft dengan item valid dan petugas terpilih dapat di-submit.
2. Submit ditolak bila tidak ada item.
3. Submit ditolak bila tidak ada petugas terlibat.
4. Verifikasi hanya boleh dari status `SUBMITTED`.
5. Verifikasi menolak line tanpa `quantity_approved`.
6. Verifikasi menolak line tanpa batch stok.
7. Verifikasi menolak quantity yang melebihi `available_quantity`.
8. Prepare hanya boleh dari status `VERIFIED`.
9. Distribute hanya boleh dari status `PREPARED`.
10. Rejection hanya boleh dari status `SUBMITTED`.

### E. Side Effect Distribusi Stok

Prioritas: Kritis

1. Distribusi final mengurangi `Stock.quantity` sesuai `quantity_approved`.
2. Distribusi final membuat tepat satu `Transaction(OUT)` per line item.
3. `Transaction` mencatat `item`, `location`, `batch_lot`, `quantity`, `unit_price`, `sumber_dana`, dan referensi distribusi yang benar.
4. `approved_by`, `approved_at`, dan `distributed_date` terisi saat distribusi final berhasil.
5. Snapshot `issued_batch_lot`, `issued_expiry_date`, `issued_unit_price`, dan `issued_sumber_dana` tersalin ke `DistributionItem`.
6. Bila satu line gagal karena stok tidak cukup, seluruh transaksi dibatalkan dan tidak ada stok yang berubah parsial.
7. Batch stok yang tidak sesuai item memicu error dan rollback.

### F. Step-Back, Reset, dan Delete Guard

Prioritas: Tinggi

1. `step_back` dari `SUBMITTED` kembali ke `DRAFT`.
2. `step_back` dari `VERIFIED` kembali ke `SUBMITTED` dan membersihkan metadata verifikasi.
3. `step_back` dari `PREPARED` kembali ke `VERIFIED`.
4. `step_back` dari `REJECTED` kembali ke `SUBMITTED`.
5. `step_back` ditolak untuk `DISTRIBUTED`.
6. `reset_to_draft` menghapus metadata verifikasi dan distribusi untuk status yang diperbolehkan.
7. `reset_to_draft` ditolak untuk `DISTRIBUTED`.
8. Delete hanya diizinkan untuk `DRAFT` dan `REJECTED`.
9. Delete ditolak untuk `SUBMITTED`, `VERIFIED`, `PREPARED`, dan `DISTRIBUTED`.

### G. Akses, Permission, dan Module Scope

Prioritas: Tinggi

1. User tanpa permission `distribution.add_distribution` tidak dapat membuat distribusi.
2. User tanpa permission `distribution.change_distribution` tidak dapat submit, verify, prepare, distribute, reset, atau step-back.
3. User tanpa scope `APPROVE` pada modul `distribution` tidak dapat verify atau reject.
4. Superuser tetap dapat menjalankan seluruh action approval.
5. Endpoint detail dan list meminta autentikasi.

### H. List, Detail, Search, dan Filter

Prioritas: Menengah

1. `distribution_list` memfilter berdasarkan kata kunci nomor dokumen, fasilitas, atau program.
2. `distribution_list` memfilter berdasarkan status dan distribution type.
3. Pagination membatasi 25 data per halaman.
4. `distribution_detail` menampilkan total quantity, grand total, dan daftar petugas sesuai state dokumen.

### I. Integrasi Dengan `LPLPO`

Prioritas: Menengah

1. Distribusi tipe `LPLPO` dapat direlasikan ke satu dokumen `LPLPO`.
2. Relasi `lplpo_source` tidak rusak setelah distribusi melewati workflow normal.
3. Ketika distribusi terkait dianggap selesai di modul `lplpo`, status distribusi yang sudah `DISTRIBUTED` tetap menjadi sumber kebenaran untuk penutupan alur hilir.

## Strategi Data Uji

Data uji minimum yang direkomendasikan:

- satu user superuser untuk baseline success path
- satu user role `GUDANG` tanpa scope approval untuk negative path approval
- satu user role `KEPALA` atau user dengan scope `APPROVE` untuk jalur verifikasi dan rejection
- satu `Facility` tipe `PUSKESMAS`
- minimal dua batch `Stock` untuk item yang sama dengan expiry berbeda guna menguji FEFO dan pemilihan batch
- satu `Distribution` reguler tipe `LPLPO` atau `ALLOCATION`
- satu relasi `LPLPO.distribution` untuk memastikan kontrak lintas modul tidak pecah

Prinsip data uji:

- gunakan `setUpTestData()` untuk master data dan stok dasar yang dipakai lintas method
- gunakan fixture terpisah untuk status dokumen agar jalur sukses dan jalur gagal tidak saling memengaruhi
- jangan mengandalkan implicit ordering selain yang memang dikontrak model atau query

## Kriteria Masuk

Sebelum implementasi test pada modul ini dimulai:

- plan `stock`, `items`, `users`, `core`, dan `receiving` sudah direview karena modul ini bergantung langsung pada semuanya
- helper test untuk membuat `Stock`, `Distribution`, `Facility`, dan `User` sudah stabil atau siap direfaktor lokal di file test
- aturan workflow terbaru pada `distribution.services` sudah dianggap source of truth

## Kriteria Selesai

Plan ini dianggap selesai bila:

- seluruh workflow status punya jalur sukses dan gagal yang teruji
- setiap path yang mengurangi stok punya assertion langsung terhadap `Stock` dan `Transaction`
- permission dan scope approval diuji minimal untuk create, verify, reject, dan delete
- test gagal bila terjadi regresi pada snapshot issued fields, bukan hanya bila status dokumen berubah

## Urutan Pelaksanaan Yang Direkomendasikan

1. Tambahkan pengujian model untuk `document_number` dan uniqueness staff assignment.
2. Lengkapi pengujian service workflow agar seluruh guard dan rollback kritis terkunci di level unit-integrasi ringan.
3. Lengkapi pengujian view action untuk submit, verify, prepare, distribute, reject, reset, step-back, dan delete.
4. Tambahkan pengujian list, filter, detail, dan kontrak relasi `LPLPO` sebagai lapisan regresi terakhir.
