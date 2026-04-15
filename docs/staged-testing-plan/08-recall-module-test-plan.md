# Rencana Pengujian Modul `recall`

## Tujuan

Memastikan modul `recall` menjalankan alur pengembalian barang ke pemasok secara aman, hanya memotong stok pada checkpoint verifikasi yang benar, menghasilkan `Transaction(OUT)` yang lengkap untuk audit, dan menolak rollback status yang dapat merusak konsistensi inventaris setelah stok terlanjur berkurang.

## Cakupan Yang Diuji

Komponen dalam cakupan plan ini:

- model `Recall`
- model `RecallItem`
- `save()` pada `Recall` untuk pembangkitan `document_number`
- form `RecallForm`
- form `RecallItemForm`
- `RecallItemFormSet`
- view `recall_list`
- view `recall_create`
- view `recall_edit`
- view `recall_detail`
- view action `recall_submit`
- view action `recall_verify`
- view action `recall_complete`
- view action `recall_reset_to_draft`
- view action `recall_step_back`
- view action `recall_delete`
- kontrak integrasi langsung dengan `Stock`
- kontrak integrasi langsung dengan `Transaction` untuk `reference_type=RECALL`
- guard permission dan module scope pada action yang memerlukan approval

## Di Luar Cakupan

Di luar plan ini:

- workflow disposal pada modul `expired`
- laporan dan dashboard agregat berbasis data recall
- administrasi master data `Supplier`, `Item`, `FundingSource`, atau `Location` secara penuh
- pengujian visual template dan perilaku JavaScript formset pada browser end-to-end
- rekonsiliasi lintas dokumen tingkat lanjut di luar kontrak langsung `Stock` dan `Transaction`

Catatan:

Rencana ini fokus pada kontrak bisnis modul `recall` sebagai alur stok keluar ke pemasok. Interaksi dengan modul lain diuji hanya sampai titik yang benar-benar dipanggil oleh modul ini.

## Modul Terkait dan Dependency

Modul terkait yang perlu diperhatikan saat menyusun pengujian:

- `stock`: sumber batch recall, `available_quantity`, pengurangan `Stock.quantity`, dan audit `Transaction(OUT)`
- `items`: `Item`, `Supplier`, `Location`, `FundingSource`, dan referensi master data lain yang dipakai recall
- `users`: autentikasi, role, dan `ModuleAccess` untuk guard permission serta approval scope
- `core`: decorator `perm_required` dan `module_scope_required`

Dependency teknis utama:

- transaksi database atomik di action `recall_verify`
- locking melalui `select_for_update()` pada stok yang akan dipotong
- formset inline untuk line item recall
- properti `Stock.available_quantity` sebagai dasar validasi stok tersedia
- `Transaction.ReferenceType.RECALL` sebagai kontrak audit trail keluar

## Risiko Bisnis

### Risiko Kritis

1. Stok terpotong saat status belum masuk tahap verifikasi.
2. `Stock.quantity` berkurang dengan angka yang salah atau terpotong parsial ketika salah satu line item gagal.
3. `Transaction(OUT)` tidak dibuat, dibuat ganda, atau memakai item, batch, atau referensi dokumen yang salah.
4. Recall bisa diverifikasi walaupun batch stok tidak sesuai dengan item pada line.
5. Recall yang sudah memotong stok masih bisa dikembalikan ke `DRAFT`, sehingga ledger dan saldo stok tidak konsisten.

### Risiko Tinggi

1. User tanpa scope approval dapat memverifikasi atau menyelesaikan recall.
2. Recall dapat diajukan tanpa item.
3. Recall menerima quantity melebihi `available_quantity`.
4. `step_back` atau `reset_to_draft` mengizinkan status mundur yang seharusnya diblokir setelah stok berubah.
5. Delete menghapus dokumen yang bukan `DRAFT`.

### Risiko Menengah

1. `document_number` `REC-YYYYMM-XXXXX` tidak unik atau tidak berurutan.
2. List view, search, dan filter status tidak menampilkan dokumen secara konsisten.
3. `RecallItemForm` menampilkan batch yang seharusnya tidak tersedia atau tidak mengikuti FEFO.
4. Metadata `verified_by`, `verified_at`, `completed_by`, dan `completed_at` tidak sinkron dengan status dokumen.

## Sasaran Mutu

Target kualitas untuk modul ini:

- Setiap jalur yang memotong stok harus memiliki assertion langsung terhadap `Stock` dan `Transaction`, bukan hanya status HTTP atau redirect.
- Seluruh transisi status harus memiliki jalur sukses dan jalur gagal.
- Guard rollback setelah stok terpotong wajib diuji eksplisit.
- Permission dan approval scope wajib diuji pada titik verify dan complete.
- Tidak ada perilaku kritis yang hanya diuji lewat response template tanpa pemeriksaan state data.

## Tingkat Pengujian

### Tingkat 1: Pengujian Model dan Properti Dasar

Fokus:

- pembangkitan `document_number`
- `__str__()` pada `Recall` dan `RecallItem`
- default `recall_date`
- keterisian field audit sesuai transisi status

### Tingkat 2: Pengujian Form dan Validasi Input

Fokus:

- validasi kecocokan `stock.item` dengan `item`
- validasi `quantity > 0`
- FEFO dan filtering batch dengan `available_quantity > 0`
- create dan edit dengan formset item recall

### Tingkat 3: Pengujian Workflow Dokumen

Fokus:

- alur `DRAFT -> SUBMITTED -> VERIFIED -> COMPLETED`
- restriction edit
- `reset_to_draft`
- `step_back`
- delete restriction

### Tingkat 4: Pengujian Side Effect Stok dan Audit Trail

Fokus:

- pemotongan stok saat verifikasi
- satu `Transaction(OUT)` per line item recall
- rollback penuh bila satu item gagal
- penolakan batch yang tidak sesuai dengan item

### Tingkat 5: Pengujian View dan Akses

Fokus:

- list, search, filter, dan pagination
- autentikasi dan permission
- module scope `APPROVE` untuk verify dan complete

## Matriks Skenario

### A. Document Number dan Field Header

Prioritas: Tinggi

Skenario:

1. Save tanpa `document_number` menghasilkan format `REC-YYYYMM-XXXXX`.
2. Nomor recall berikutnya meningkat sekuensial dalam bulan yang sama.
3. `document_number` kustom tetap dipertahankan bila diisi.
4. `Recall.__str__()` menampilkan nomor dokumen dan pemasok.
5. `RecallItem.__str__()` menampilkan item dan quantity.

### B. Form Validation dan Integritas Line Item

Prioritas: Tinggi

Skenario:

1. `RecallItemForm` menolak batch stok yang item-nya tidak sesuai dengan item pada line.
2. `RecallItemForm` menolak `quantity <= 0`.
3. Field batch hanya menampilkan stok dengan `quantity > reserved`.
4. Urutan batch mengikuti FEFO berdasarkan expiry terdekat lalu batch lot.
5. Line item yang valid tersimpan benar melalui formset create.
6. Line item dapat diperbarui melalui formset edit selama status recall masih boleh diubah.

### C. Workflow Recall Dasar

Prioritas: Kritis

Skenario:

1. Recall `DRAFT` dengan minimal satu item dapat diajukan menjadi `SUBMITTED`.
2. Submit ditolak bila recall tidak memiliki item.
3. Submit ditolak bila status bukan `DRAFT`.
4. Verify hanya boleh dari status `SUBMITTED`.
5. Complete hanya boleh dari status `VERIFIED`.
6. Edit hanya diizinkan untuk `DRAFT` dan `SUBMITTED`.
7. Edit ditolak untuk `VERIFIED` dan `COMPLETED`.

### D. Side Effect Verifikasi ke Stok dan Ledger

Prioritas: Kritis

Skenario:

1. Verifikasi recall mengurangi `Stock.quantity` sesuai quantity per line item.
2. Verifikasi recall membuat tepat satu `Transaction(OUT)` per line item.
3. `Transaction` menyimpan `item`, `location`, `batch_lot`, `quantity`, `unit_price`, `sumber_dana`, dan `reference_id` recall yang benar.
4. `verified_by` dan `verified_at` terisi saat verifikasi berhasil.
5. Verifikasi ditolak bila `quantity` melebihi `available_quantity`.
6. Verifikasi ditolak bila `stock.item_id` tidak sama dengan `recall_item.item_id`.
7. Bila salah satu item gagal diproses, seluruh transaksi dibatalkan dan tidak ada stok yang berubah parsial.

### E. Complete, Step-Back, dan Reset Guard

Prioritas: Tinggi

Skenario:

1. Recall `VERIFIED` dapat ditandai `COMPLETED`.
2. `completed_by` dan `completed_at` terisi saat complete berhasil.
3. `step_back` dari `COMPLETED` kembali ke `VERIFIED` serta membersihkan metadata complete.
4. `step_back` dari `SUBMITTED` kembali ke `DRAFT`.
5. `step_back` ditolak untuk `VERIFIED` karena stok sudah terpotong.
6. `reset_to_draft` hanya diizinkan dari `SUBMITTED`.
7. `reset_to_draft` ditolak untuk `VERIFIED` dan `COMPLETED`.
8. Pesan error pada guard rollback mencerminkan alasan bisnis bahwa stok sudah diperbarui.

### F. Delete Restriction

Prioritas: Tinggi

Skenario:

1. Delete diizinkan hanya untuk recall berstatus `DRAFT`.
2. Delete ditolak untuk `SUBMITTED`.
3. Delete ditolak untuk `VERIFIED`.
4. Delete ditolak untuk `COMPLETED`.
5. Delete non-POST tidak menghapus dokumen.

### G. Akses, Permission, dan Module Scope

Prioritas: Tinggi

Skenario:

1. User tanpa permission `recall.add_recall` tidak dapat membuat recall.
2. User tanpa permission `recall.change_recall` tidak dapat submit, verify, complete, reset, atau step-back.
3. User tanpa permission `recall.delete_recall` tidak dapat menghapus recall.
4. User tanpa scope `APPROVE` pada modul `recall` tidak dapat verify.
5. User tanpa scope `APPROVE` pada modul `recall` tidak dapat complete.
6. Superuser tetap dapat menjalankan semua action recall.
7. View list dan detail memerlukan autentikasi.

### H. List, Detail, Search, dan Filter

Prioritas: Menengah

Skenario:

1. `recall_list` memfilter berdasarkan nomor dokumen atau nama supplier.
2. `recall_list` memfilter berdasarkan status.
3. Pagination membatasi 25 data per halaman.
4. `recall_detail` menampilkan item, batch stok, lokasi, dan sumber dana yang terhubung ke recall.
5. List tetap mengembalikan urutan berdasarkan `-recall_date`.

## Strategi Data Uji

Data uji minimum yang direkomendasikan:

- satu user superuser untuk baseline success path
- satu user role `GUDANG` tanpa scope approval untuk jalur negatif verify dan complete
- satu user dengan scope `APPROVE` eksplisit pada modul `recall` untuk jalur approval non-superuser
- satu `Supplier`
- satu `Item` aktif dengan `Unit` dan `Category`
- satu `FundingSource`
- satu `Location`
- minimal dua batch `Stock` untuk item yang sama dengan expiry berbeda guna menguji FEFO
- satu batch stok dengan quantity rendah untuk menguji insufficient stock
- satu line item dengan batch salah item untuk menguji rollback

Prinsip data uji:

- gunakan `setUpTestData()` untuk referensi master yang dipakai berulang
- pisahkan fixture recall per status agar jalur workflow tidak saling memengaruhi
- verifikasi state database setelah action penting, bukan hanya redirect atau pesan sukses

## Kriteria Masuk

Sebelum implementasi test pada modul ini dimulai:

- plan `stock`, `items`, `users`, `core`, `receiving`, dan `distribution` sudah direview karena recall bergantung langsung pada layer-layer tersebut
- kontrak `Stock.available_quantity` dan `Transaction.ReferenceType.RECALL` sudah stabil
- source of truth workflow recall di `apps.recall.views` sudah dipahami dan tidak sedang direfaktor besar
- helper atau fixture pembuat stok dan item tersedia atau siap dirapikan di file test recall

## Kriteria Selesai

Plan ini dianggap selesai bila:

- semua transisi status recall memiliki jalur berhasil dan gagal yang teruji
- setiap jalur verify memiliki assertion langsung terhadap pengurangan stok dan pembuatan `Transaction(OUT)`
- rollback guard setelah stok terpotong terbukti tidak mengizinkan kembali ke `DRAFT`
- permission dan approval scope diuji minimal pada create, verify, complete, dan delete
- test gagal bila terjadi regresi pada ledger atau quantity stok, bukan hanya bila status dokumen berubah

## Hasil Akhir Yang Diharapkan

Jika plan ini diterapkan dengan baik, tim akan memperoleh:

- jaminan bahwa recall hanya mengurangi stok pada checkpoint verifikasi yang benar
- keyakinan bahwa jejak audit pengeluaran ke pemasok lengkap dan dapat ditelusuri
- perlindungan regresi terhadap rollback status yang berisiko merusak konsistensi inventaris
- baseline aman untuk melanjutkan plan modul `expired` yang juga melakukan pengurangan stok dengan pola audit serupa

## Urutan Pelaksanaan Yang Direkomendasikan

Urutan implementasi test yang disarankan:

1. Tambahkan pengujian model untuk `document_number`, string representation, dan field audit dasar.
2. Lengkapi pengujian form untuk validasi batch-item, quantity positif, dan filtering FEFO.
3. Lengkapi pengujian workflow submit, verify, complete, reset, step-back, edit, dan delete restriction.
4. Tambahkan pengujian side effect stok dan `Transaction(OUT)` termasuk rollback atomik.
5. Tambahkan pengujian permission, scope approval, serta list/filter/detail sebagai lapisan regresi terakhir.