# Document Numbering Refactor — Deep Validation Workbook

Dokumen ini adalah ringkasan implementasi, checklist pengujian manual, dan tempat mencatat temuan untuk refactor penomoran dokumen terpusat. Edit file ini langsung ketika menemukan perilaku yang tidak sesuai agar temuan dapat direproduksi dan ditangani bersama.

## Baseline yang Diuji

- Branch: `refactor/modular-document-numbering`
- Commit implementasi: `6bf9d96` (`refactor: centralize document numbering`)
- Tanggal baseline: 22 September 2026
- Database target pengujian: development/test PostgreSQL; jangan gunakan data produksi.
- Migration backfill ledger bersifat forward-only. Untuk mengulang dari kondisi sebelum migration, reset database development atau restore backup yang dibuat sebelum migration.

Validasi otomatis pada baseline:

- 733 tes relevan lulus pada Core, Distribution, Allocation, Procurement, Receiving, Recall, Expired, Stock Opname, Stock Transfer, Reports, Mobile, dan LPLPO.
- Fresh test database berhasil dibuat, seluruh migration diterapkan, enam tes inti penomoran lulus, lalu database test dihapus.
- `python manage.py check` lulus.
- `python manage.py makemigrations --check --dry-run` melaporkan `No changes detected`.
- `git diff --check` lulus. Peringatan konversi LF/CRLF di Windows bukan error diff.

Catatan: angka di atas adalah suite yang relevan terhadap refactor, bukan klaim bahwa seluruh test suite repository telah dijalankan.

## Kontrak Perilaku

### Arsitektur

- `DocumentNumberRule` menyimpan konfigurasi format yang dapat diubah pengguna.
- `DocumentNumberSequence` menyimpan counter internal per rule, period, dan scope. Counter tidak ditampilkan atau dapat diedit dari `/settings/numbering/`.
- `DocumentNumberIssue` adalah ledger nomor resmi, termasuk status `ISSUED` dan `VOID`, snapshot konfigurasi saat penerbitan, tanggal bisnis, serta `issued_at` server untuk penerbitan baru. Riwayat migrasi menampilkan waktu tidak diketahui bila checkpoint lama tidak dapat direkonstruksi.
- Riwayat penerimaan non-rencana yang dimigrasikan memakai checkpoint verifikasi (`verified_by` / `verified_at`); rencana tertaut SPJ memakai checkpoint persetujuan (`approved_by` / `approved_at`), sedangkan rencana manual tanpa checkpoint penerbitan yang pasti tetap ditandai tidak diketahui.
- Nomor lama yang masih terisi pada Alokasi, Distribusi, Recall, atau Kedaluwarsa berstatus Draft/Disiapkan setelah step-back tetap dianggap terpakai dan wajib masuk ledger/counter; Draft tanpa nomor tetap tidak diterbitkan.
- Nomor diterbitkan di dalam transaksi database yang sama dengan checkpoint workflow.
- Nomor yang pernah diterbitkan tidak boleh digunakan kembali, termasuk setelah dokumen dihapus atau dibatalkan.
- Draft baru tidak memperoleh nomor sebelum checkpoint yang ditentukan.
- Form operasional dan Django Admin tidak menerima override nomor resmi untuk workflow yang masuk cakupan.

### Rule Default

| Rule | Default template | Reset | Padding |
| --- | --- | --- | ---: |
| Allocation | `ALK-{year}-{seq}` | Tahunan | 4 |
| Distribution LPLPO | `440/{seq}/SBBK.RF/{year}` | Tahunan | 1 |
| Permintaan Khusus | `440/{seq}/KD.F/{year}` | Tahunan | 1 |
| SPJ / Kontrak | `SPJ-{year}-{seq}` | Tahunan | 5 |
| Amandemen SPJ | `SPJ/{year}/{month}/{seq}` | Bulanan | 1 |
| Receiving | `RCV-{year}-{seq}` | Tahunan | 5 |
| Recall | `REC-{year}{month}-{seq}` | Bulanan | 5 |
| Kedaluwarsa | `EXP-{year}{month}-{seq}` | Bulanan | 5 |
| Mutasi Lokasi | `TRF-{year}-{seq}` | Tahunan | 5 |
| Stock Opname | `SO-{year}{month}-{seq}` | Bulanan | 5 |

Dokumen Puskesmas dan dokumen induk LPLPO berada di luar sistem ini. Mekanisme nomor mereka tidak boleh berubah akibat konfigurasi rule di `/settings/numbering/`.

### Checkpoint Penerbitan

| Workflow | Nomor diterbitkan ketika | Tanggal bisnis |
| --- | --- | --- |
| Allocation parent | Submit | `allocation_date` |
| Allocation child | Approval parent | `allocation_date` parent |
| Distribution LPLPO standalone | Submit | `request_date` |
| Permintaan Khusus standalone | Submit | `request_date` |
| SPJ / kontrak | Submit | `contract_date` |
| Amandemen SPJ | Submit | `amendment_date` |
| Receiving plan dari SPJ | Approval SPJ | `receiving_date` |
| Receiving plan manual legacy | Submit | `receiving_date` |
| Receiving reguler | Posting stok berhasil | `receiving_date` |
| Receiving CSV | Konfirmasi grup berhasil | `receiving_date` |
| Recall | Submit | `recall_date` |
| Kedaluwarsa | Submit | `report_date` |
| Stock Transfer | Completion | `transfer_date` |
| Stock Opname | Start | `period_end` |

## Cara Mengisi Checklist

- Biarkan `[ ]` bila belum diuji.
- Ubah menjadi `[x]` bila hasil sesuai kontrak.
- Ubah menjadi `[!]` bila gagal, lalu buat entri pada bagian **Temuan** dengan ID seperti `DN-001`.
- Isi kolom catatan singkat dengan nomor dokumen, role pengguna, atau ID objek yang relevan. Jangan memasukkan password, token, atau data sensitif.

Tester: `____________________`  
Environment: `____________________`  
Commit yang diuji: `____________________`  
Tanggal mulai: `____________________`

## 1. Persiapan dan Migration

- [ ] Backup atau snapshot database development dibuat sebelum migration. Catatan: `____________________`
- [ ] `python manage.py migrate` selesai tanpa error. Catatan: `____________________`
- [ ] `/settings/` hanya menampilkan pengaturan umum, sedangkan `/settings/numbering/` menampilkan tepat sepuluh rule di atas. Catatan: `____________________`
- [ ] Draft lama yang belum mencapai checkpoint tidak memperoleh nomor resmi dari backfill. Catatan: `____________________`
- [ ] Dokumen lama yang sudah melewati checkpoint muncul di Riwayat Penomoran. Catatan: `____________________`
- [ ] Tidak ada nomor resmi lama yang berubah setelah migration. Catatan: `____________________`

## 2. Pengaturan Rule

Gunakan database development yang dapat direset. Catat nilai awal sebelum mengubah rule.

- [ ] Superuser dapat membuka `/settings/` dan `/settings/numbering/`. Catatan: `____________________`
- [ ] Role `ADMIN` dapat membuka `/settings/` dan `/settings/numbering/`. Catatan: `____________________`
- [ ] Role `KEPALA` dapat membuka `/settings/` dan `/settings/numbering/`. Catatan: `____________________`
- [ ] Role lain ditolak dengan HTTP 403 walaupun memiliki module scope tinggi. Catatan: `____________________`
- [ ] Template, reset period, dan padding dapat disimpan tanpa HTTP 500. Catatan: `____________________`
- [ ] Preview berubah mengikuti template dan padding tanpa mengonsumsi nomor. Catatan: `____________________`
- [ ] Ikon informasi pada header membuka/menutup petunjuk placeholder, reset period, dan minimum digit urutan. Catatan: `____________________`
- [ ] Petunjuk menjelaskan bahwa minimum digit menambahkan nol di depan tanpa memotong sequence yang lebih panjang. Catatan: `____________________`
- [ ] Counter atau `last_value` tidak terlihat dan tidak dapat diedit. Catatan: `____________________`
- [ ] Placeholder tidak dikenal ditolak dengan pesan validasi. Catatan: `____________________`
- [ ] Rule tahunan tanpa `{year}` ditolak. Catatan: `____________________`
- [ ] Rule bulanan tanpa `{year}` atau `{month}` ditolak. Catatan: `____________________`
- [ ] Placeholder `{parent}` ditolak sebagai placeholder yang tidak didukung. Catatan: `____________________`
- [ ] Kembalikan seluruh rule ke nilai yang ingin dipakai setelah pengujian. Catatan: `____________________`

## 3. Invariant Global

- [ ] Membuat draft baru tidak mengisi `document_number`. Catatan: `____________________`
- [ ] UI menampilkan `Belum diterbitkan` untuk draft tanpa nomor. Catatan: `____________________`
- [ ] Nomor diterbitkan tepat pada checkpoint, bukan pada `save()` biasa. Catatan: `____________________`
- [ ] Mengulangi request checkpoint tidak menerbitkan nomor kedua untuk objek yang sama. Catatan: `____________________`
- [ ] Tahun/bulan nomor mengikuti tanggal bisnis dokumen, bukan tanggal komputer saat aksi dilakukan. Catatan: `____________________`
- [ ] Dokumen dengan tanggal bisnis pada period berbeda mulai kembali dari sequence pertama untuk rule yang reset. Catatan: `____________________`
- [ ] Nomor yang di-VOID tidak digunakan kembali oleh dokumen berikutnya. Catatan: `____________________`
- [ ] Nomor resmi tidak dapat diketik atau diubah melalui form operasional. Catatan: `____________________`
- [ ] Nomor resmi read-only pada Django Admin untuk model dalam cakupan. Catatan: `____________________`

## 4. Distribution dan Allocation

### Permintaan Khusus dan LPLPO Standalone

- [ ] Draft Distribution standalone belum bernomor. Catatan: `____________________`
- [ ] Status `PREPARED` masih belum bernomor. Catatan: `____________________`
- [ ] Submit Distribution LPLPO memakai rule LPLPO dan `request_date`. Catatan: `____________________`
- [ ] Submit Permintaan Khusus memakai rule Permintaan Khusus dan `request_date`. Catatan: `____________________`
- [ ] Verification, preparation lanjutan, dan distribution final tidak mengganti nomor. Catatan: `____________________`
- [ ] Menghapus dokumen resmi yang diizinkan membuat issue ledger berstatus `VOID`. Catatan: `____________________`

### Allocation sebagai Orchestrator

- [ ] Draft Allocation belum bernomor. Catatan: `____________________`
- [ ] Submit Allocation menerbitkan nomor parent dari rule Allocation. Catatan: `____________________`
- [ ] Approval membuat satu child per fasilitas dengan `distribution_type=SPECIAL_REQUEST`. Catatan: `____________________`
- [ ] Setiap child memiliki `allocation_id` dan langsung berada pada status `VERIFIED`. Catatan: `____________________`
- [ ] Buat Permintaan Khusus standalone lebih dulu, lalu approve Allocation; nomor child melanjutkan sequence yang sama tanpa mulai dari awal. Catatan: `____________________`
- [ ] Child tampil pada laporan umum Permintaan Khusus. Catatan: `____________________`
- [ ] Child yang sama tampil pada laporan asal Allocation. Catatan: `____________________`
- [ ] Child tidak muncul di mobile approval inbox. Catatan: `____________________`
- [ ] Edit/reset/delete generik child dari modul Distribution diblokir; pengelolaan dilakukan melalui parent Allocation. Catatan: `____________________`
- [ ] Step-back parent melepaskan reservasi, menandai nomor child lama `VOID`, lalu menghapus child. Catatan: `____________________`
- [ ] Approval ulang parent membuat child baru dengan nomor berikutnya, bukan memakai ulang nomor yang di-VOID. Catatan: `____________________`

## 5. Procurement dan Planned Receiving

- [ ] Draft SPJ belum bernomor. Catatan: `____________________`
- [ ] Submit SPJ menerbitkan nomor berdasarkan `contract_date`. Catatan: `____________________`
- [ ] Approval SPJ membuat atau menyinkronkan planned Receiving dan menerbitkan nomor Receiving. Catatan: `____________________`
- [ ] Nomor planned Receiving tidak berubah saat penerimaan parsial, penuh, atau close. Catatan: `____________________`
- [ ] Amandemen pada bulan yang sama melanjutkan counter bersama walaupun berasal dari kontrak berbeda. Catatan: `____________________`
- [ ] Amandemen pada bulan berikutnya memulai periode counter baru sesuai rule bulanan. Catatan: `____________________`
- [ ] Form Procurement menyimpan satu `Nomor Dokumen Eksternal` opsional, menampilkannya pada detail/daftar, dan pencarian dapat menemukannya. Catatan: `____________________`
- [ ] Pembatalan SPJ yang diizinkan menandai nomor SPJ dan planned Receiving terkait sebagai `VOID`. Catatan: `____________________`

## 6. Receiving Reguler dan CSV

### Receiving Reguler

- [ ] Form create tidak menyediakan input nomor resmi. Catatan: `____________________`
- [ ] Nomor diterbitkan dalam transaksi yang sama dengan `ReceivingItem`, `Stock`, dan `Transaction(IN)`. Catatan: `____________________`
- [ ] Bila salah satu item gagal, seluruh create termasuk nomor dan counter rollback. Catatan: `____________________`
- [ ] Koreksi receiving mempertahankan nomor resmi dan source layer yang benar. Catatan: `____________________`
- [ ] Cancel/delete correction menandai issue `VOID` dan tidak menghapus transaksi historis. Catatan: `____________________`

### Import CSV

- [ ] Template CSV memakai kolom `import_group`, bukan `document_number`. Catatan: `____________________`
- [ ] Beberapa baris dengan `import_group` sama membentuk satu Receiving dengan beberapa item. Catatan: `____________________`
- [ ] `import_group` tersimpan sebagai identitas import tetapi tidak disalin menjadi nomor resmi. Catatan: `____________________`
- [ ] Dua grup valid memperoleh dua nomor resmi yang berbeda. Catatan: `____________________`
- [ ] Preview/dry run tidak menerbitkan nomor atau mengubah stock. Catatan: `____________________`
- [ ] Kegagalan satu baris membatalkan seluruh grup beserta nomor/counter grup tersebut. Catatan: `____________________`
- [ ] Kandidat nomor yang sudah dipakai Opening Balance dilewati; Receiving memperoleh sequence berikutnya. Catatan: `____________________`
- [ ] `Stock.source_document_number`, `Transaction.source_document_number`, dan claim menunjuk nomor Receiving resmi, bukan `import_group`. Catatan: `____________________`
- [ ] Override sumber dana per baris tetap tersimpan pada layer aktual dan dapat dibalik dengan benar saat koreksi. Catatan: `____________________`

## 7. Recall, Kedaluwarsa, Transfer, dan Stock Opname

### Recall

- [ ] Draft belum bernomor; submit menerbitkan nomor berdasarkan `recall_date`. Catatan: `____________________`
- [ ] Pergantian bulan memulai sequence baru. Catatan: `____________________`
- [ ] Nomor tidak berubah pada verify/complete. Catatan: `____________________`
- [ ] Penghapusan dokumen resmi yang diizinkan mencatat `VOID`. Catatan: `____________________`

### Kedaluwarsa

- [ ] Draft belum bernomor; submit menerbitkan nomor berdasarkan `report_date`. Catatan: `____________________`
- [ ] Pergantian bulan memulai sequence baru. Catatan: `____________________`
- [ ] Nomor tidak berubah pada verify/dispose. Catatan: `____________________`
- [ ] Penghapusan dokumen resmi yang diizinkan mencatat `VOID`. Catatan: `____________________`

### Stock Transfer

- [ ] Draft belum bernomor. Catatan: `____________________`
- [ ] Completion menerbitkan nomor berdasarkan `transfer_date` dalam transaksi yang sama dengan pasangan `OUT`/`IN`. Catatan: `____________________`
- [ ] Kegagalan completion tidak meninggalkan nomor, counter, stock mutation, atau transaksi parsial. Catatan: `____________________`

### Stock Opname

- [ ] Draft belum bernomor. Catatan: `____________________`
- [ ] Start menerbitkan nomor berdasarkan `period_end`, bukan `created_at`. Catatan: `____________________`
- [ ] Pergantian bulan `period_end` memulai sequence baru. Catatan: `____________________`
- [ ] Penghapusan opname yang sudah dimulai mencatat `VOID`. Catatan: `____________________`
- [ ] Completion tidak mengganti nomor dan tetap mengikuti aturan discrepancy/permission yang ada. Catatan: `____________________`

## 8. Riwayat Penomoran dan Export

- [ ] Riwayat Penomoran membaca `DocumentNumberIssue`, bukan menebak dari tabel workflow. Catatan: `____________________`
- [ ] Filter rule, status, tanggal bisnis, dan pencarian nomor bekerja. Catatan: `____________________`
- [ ] Baris `ISSUED` dan `VOID` dapat dibedakan dengan jelas. Catatan: `____________________`
- [ ] Alasan, pelaku, dan waktu VOID tampil sesuai aksi. Catatan: `____________________`
- [ ] Snapshot label/template/reset/padding lama tetap sama setelah rule di `/settings/numbering/` diubah. Catatan: `____________________`
- [ ] Link target aktif membuka dokumen yang benar; ledger dokumen yang sudah dihapus tetap terbaca melalui label snapshot. Catatan: `____________________`
- [ ] Export Excel menghasilkan isi/filter yang sama dengan halaman. Catatan: `____________________`
- [ ] Nilai filter berawalan `=`, `+`, `-`, atau `@` tidak menjadi formula Excel. Catatan: `____________________`

## 9. Permission dan Audit

- [ ] Hanya superuser, `ADMIN`, dan `KEPALA` yang dapat mengubah rule melalui `/settings/numbering/`. Catatan: `____________________`
- [ ] Perubahan `DocumentNumberRule` tercatat oleh django-auditlog. Catatan: `____________________`
- [ ] Perubahan status issue menjadi `VOID` tercatat oleh django-auditlog. Catatan: `____________________`
- [ ] User tanpa permission workflow tidak dapat memaksa issuance melalui POST langsung. Catatan: `____________________`
- [ ] Error konfigurasi rule ditampilkan sebagai pesan workflow yang aman dan tidak menghasilkan HTTP 500. Catatan: `____________________`

## 10. Concurrency dan Ketahanan

Pengujian manual dua-tab hanya pelengkap; tes otomatis berbasis transaksi adalah bukti utama untuk race condition.

- [ ] Dua penerbitan konkuren pada rule/period yang sama menghasilkan nomor berbeda dan berurutan. Catatan: `____________________`
- [ ] Dua Receiving konkuren tidak memperoleh source-document claim yang sama. Catatan: `____________________`
- [ ] Dua Stock Transfer completion terhadap stock yang sama tidak menyebabkan stock negatif atau transaksi parsial. Catatan: `____________________`
- [ ] Double-click atau retry POST pada objek yang sama tidak membuat issue kedua. Catatan: `____________________`
- [ ] Setelah rollback paksa, nomor yang gagal tidak terlihat sebagai issue resmi dan counter tidak maju. Catatan: `____________________`

## 11. Regression di Luar Cakupan Central Numbering

- [ ] Puskesmas Request tetap memakai format dan workflow nomor sebelumnya. Catatan: `____________________`
- [ ] Puskesmas Receipt Confirmation tetap memakai format dan workflow nomor sebelumnya. Catatan: `____________________`
- [ ] Dokumen induk LPLPO tetap memakai format dan workflow nomor sebelumnya. Catatan: `____________________`
- [ ] Perubahan rule `/settings/numbering/` tidak mengubah nomor ketiga jenis dokumen tersebut. Catatan: `____________________`
- [ ] LPLPO PIC review tetap dapat membuat Distribution LPLPO dan nomor Distribution diterbitkan pada checkpoint Distribution yang sesuai. Catatan: `____________________`

## 12. Perintah Reproduksi

Dari root repository:

```powershell
python backend/manage.py check
python backend/manage.py makemigrations --check --dry-run
.\scripts\run-django-test.ps1 -Target apps.core.tests.test_numbering -KeepDb
.\scripts\run-django-test.ps1 -Target apps.distribution.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.allocation.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.procurement.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.receiving.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.recall.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.expired.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.stock_opname.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.reports.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.mobile.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.lplpo.tests -KeepDb
.\scripts\run-django-test.ps1 -Target apps.core.tests.test_url_consistency -KeepDb
```

Tes Stock Transfer terfokus:

```powershell
.\scripts\run-django-test.ps1 -Target apps.stock.tests.StockTransferModelTests,apps.stock.tests.StockTransferConcurrencyTests,apps.stock.tests.StockTransferCreateValidationTests -KeepDb
```

## Temuan

Salin template berikut untuk setiap masalah. Beri satu ID per perilaku agar diskusi dan perbaikannya tidak bercampur.

### DN-000 — Judul singkat

- Status: `OPEN | INVESTIGATING | FIXED | RETEST | CLOSED`
- Severity: `BLOCKER | HIGH | MEDIUM | LOW`
- Modul/workflow:
- Commit yang diuji:
- Environment/database:
- Browser/device:
- User dan role/module scope:
- ID objek terkait:
- Nomor dokumen terkait:
- Prasyarat/data awal:
- Langkah reproduksi:
  1. 
  2. 
  3. 
- Hasil yang diharapkan:
- Hasil aktual:
- Apakah terjadi setiap kali:
- Bukti: screenshot, log, traceback, atau query hasil pemeriksaan
- Dampak terhadap stock/transaction/reservation:
- Workaround sementara:
- Catatan analisis:

## Ringkasan Sesi Pengujian

| Tanggal | Tester | Area | Hasil | Temuan | Catatan |
| --- | --- | --- | --- | --- | --- |
|  |  |  | `PASS / FAIL / PARTIAL` |  |  |

## Exit Criteria

Refactor siap digabung hanya jika:

- Semua checklist kritis pada migration, invariant global, checkpoint issuance, Receiving/source layer, Allocation shared sequence, VOID, permission, dan concurrency berstatus lulus.
- Setiap temuan `BLOCKER` atau `HIGH` sudah `CLOSED` setelah retest.
- Tidak ada nomor manual pada workflow dalam cakupan.
- Tidak ada stock mutation atau ledger transaction parsial ketika issuance gagal.
- Puskesmas dan LPLPO parent terbukti tidak berubah.
- `manage.py check`, migration drift check, suite inti penomoran, dan suite modul yang diperbaiki kembali hijau pada commit final.
