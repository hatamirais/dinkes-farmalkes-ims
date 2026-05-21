# Sistem Manajemen Inventaris Farmasi dan Alat Kesehatan

Platform inventaris berbasis web untuk pengelolaan obat dan alat kesehatan di lingkungan Dinas Kesehatan, khususnya pada bidang atau UPT Instalasi Farmasi. Aplikasi ini dirancang untuk menghadirkan pencatatan yang lebih tertib, proses yang lebih terkendali, dan jejak audit yang lebih mudah ditelusuri.

## Gambaran Singkat

Solusi ini membantu proses inventaris berjalan lebih konsisten melalui alur dokumen yang terstruktur, kontrol akses berbasis peran, dan jejak mutasi stok yang tidak dapat diubah. Platform ini relevan untuk operasional gudang kesehatan yang membutuhkan akurasi batch, keterlacakan sumber dana, dan disiplin administrasi.

## Teknologi Inti

| Lapisan | Teknologi |
| --- | --- |
| Bahasa | Python 3.13+ |
| Framework | Django 6.0.5 |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis 7 |
| Antarmuka | Django Templates + Bootstrap 5 |
| Form | django-crispy-forms + crispy-bootstrap5 |
| Import Data | django-import-export |
| Keamanan | django-axes |

## Kapabilitas Utama

- Pengelolaan master barang dan data referensi seperti satuan, kategori, program, sumber dana, lokasi, supplier, dan fasilitas. Barang dapat ditandai sebagai program item `[P]` atau esensial `[E]`.
- Pencatatan stok per batch dengan pendekatan FEFO agar distribusi lebih terkendali dan masa kedaluwarsa lebih mudah dipantau.
- Alur kerja end-to-end untuk penerimaan, distribusi, recall, barang kedaluwarsa, transfer stok, dan stock opname.
- Dukungan tipe penerimaan bawaan dan tipe kustom melalui `ReceivingTypeOption`, termasuk quick-create dari form penerimaan.
- Pelaporan LPLPO bulanan dan pengajuan permintaan barang secara ad-hoc dari Puskesmas, dengan pembuatan dokumen yang terkunci berurutan dari Januari pada tahun server aktif serta carry-over `sisa stok` bulan sebelumnya ke `stock_awal` bulan berikutnya selama dokumen bulan sebelumnya tidak berstatus `REJECTED_PUSKESMAS` atau `REJECTED_PIC`.
- Log `Transaction` yang imutabel untuk seluruh pergerakan stok, sehingga histori tetap terjaga.
- Pengendalian akses melalui kombinasi permission Django dan `ModuleAccess` per pengguna.
- Dukungan import CSV dari Django Admin, termasuk endpoint khusus untuk penerimaan barang yang mengelompokkan baris per `document_number` dan langsung membentuk stok serta `Transaction(IN)`.

## Modul Saat Ini

### Modul aktif

- `items`: CRUD master barang dan lookup, filter daftar, serta endpoint AJAX untuk pembuatan referensi cepat.
- `stock`: daftar stok, daftar transaksi, kartu stok, pencarian stok per lokasi, dan alur transfer stok antar lokasi.
- `receiving`: alur penerimaan reguler dan rencana penerimaan, quick-create referensi dari form, dan tipe penerimaan kustom.
- `distribution`: alur persiapan, pengajuan, verifikasi, hingga distribusi dengan penugasan petugas per dokumen. Distribusi reguler dan permintaan khusus kini menempatkan kontrol tahap persiapan pada petugas yang ditugaskan, sementara approver memverifikasi dokumen yang sudah diajukan sebelum distribusi. Reset dan step-back tetap tersedia sebelum dokumen terdistribusi. Permintaan khusus menampilkan nomor dokumen usulan dari rule aktif dan mengharuskan konfirmasi sebelum edit manual.
- `allocation`: perencanaan dan orkestrasi pra-distribusi. Lifecycle Draft→Submitted→Approved membuat satu `Distribution` per fasilitas secara otomatis pada saat approval. Allocation yang sudah disetujui dapat dikembalikan ke Submitted oleh approver, yang menghapus child distributions agar approval dapat diulang. Pengurangan stok ditangguhkan ke konfirmasi pengiriman per distribusi.
- `recall`: alur retur ke supplier dari draft sampai selesai.
- `expired`: alur penanganan barang kedaluwarsa dari draft sampai disposal, termasuk halaman alert kedaluwarsa.
- `stock_opname`: proses hitung fisik dan cetak laporan selisih.
- `puskesmas`: pengajuan permintaan barang ad-hoc dari unit Puskesmas.
- `lplpo`: pelaporan pemakaian dan permintaan rutin bulanan dari Puskesmas.
  Super Admin dapat mengelola LPLPO lintas fasilitas, sementara operator Puskesmas tetap dibatasi ke fasilitasnya sendiri.
- `users`: manajemen pengguna dan pengaturan cakupan akses modul.

- `core`: dashboard, middleware akses panel admin, pengaturan sistem (label platform login, logo, header dokumen, nama fasilitas, serta template penomoran dokumen distribusi) secara dinamis, placeholder riwayat administrasi terpisah untuk penerimaan serta pengeluaran, dan handler error terpusat untuk `400/403/404/500` plus halaman maintenance `503`.
- `reports`: halaman ringkasan laporan dengan keluaran `rekap`, `penerimaan hibah`, `pengadaan`, `kadaluarsa`, dan `pengeluaran`.

## Ringkasan Workflow

- Receiving terencana: `DRAFT -> SUBMITTED -> APPROVED -> PARTIAL/RECEIVED -> CLOSED`
- Receiving reguler, tipe kustom, atau hasil import: umumnya tercatat sebagai `VERIFIED` setelah posting.
- Distribution: `DRAFT -> SUBMITTED -> VERIFIED -> PREPARED -> DISTRIBUTED`, dapat berakhir `REJECTED`, dan dokumen yang belum terdistribusi dapat dikembalikan ke `DRAFT`. Distribution hasil approval Allocation langsung dibuat pada status `VERIFIED`.
- Allocation: `DRAFT -> SUBMITTED -> APPROVED -> PARTIALLY_FULFILLED -> FULFILLED`, dapat berakhir `REJECTED`. Child distributions otomatis dibuat saat approval dan dihapus saat step-back ke SUBMITTED.
- Recall: `DRAFT -> SUBMITTED -> VERIFIED -> COMPLETED`
- Expired: `DRAFT -> SUBMITTED -> VERIFIED -> DISPOSED`
- Stock transfer: `DRAFT -> COMPLETED`
- Stock opname: `DRAFT -> IN_PROGRESS -> COMPLETED`
- Distribution: `DRAFT/REJECTED -> PREPARED -> SUBMITTED -> VERIFIED -> DISTRIBUTED`. Petugas yang ditugaskan menyiapkan dokumen, lalu approver memverifikasi dan akhirnya mendistribusikan stok. Distribution hasil approval Allocation tetap langsung dibuat pada status `VERIFIED`.
- LPLPO: `DRAFT -> SUBMITTED -> PIC_VERIFIED -> REVIEWED -> APPROVED -> CLOSED`, dengan dua loop penolakan: `SUBMITTED -> REJECTED_PUSKESMAS` untuk koreksi operator Puskesmas dan `REVIEWED -> REJECTED_PIC` untuk koreksi PIC Gudang. Approval Kepala membuat dokumen Distribution LPLPO, lalu LPLPO ditutup saat distribusi terkait selesai.
- Puskesmas Request: `DRAFT -> SUBMITTED -> APPROVED -> REJECTED`

## Model Data Singkat

- Tabel inti inventaris: `items`, `stock`, `transactions`
- Header dokumen: `receivings`, `distributions`, `allocations`, `recalls`, `expired_docs`, `stock_transfers`, `stock_opnames`
- Baris dokumen: `receiving_items`, `receiving_order_items`, `distribution_items`, `allocation_items`, `allocation_item_facilities`, `recall_items`, `expired_items`, `stock_transfer_items`, `stock_opname_items`
- Penugasan petugas: `distribution_staff_assignments`, `allocation_staff_assignments`
- Penghubung fasilitas alokasi: `allocation_facilities`
- Tabel otorisasi: `users`, `user_module_accesses`

Rincian skema kanonis tersedia di `SYSTEM_MODEL.md`.

## Keamanan

- Perlindungan brute-force login menggunakan `django-axes`.
- Validasi kata sandi kuat dengan minimum 10 karakter dan validator kustom tambahan.
- Kombinasi pengamanan sesi dan CSRF dengan `HttpOnly` serta `SameSite=Lax`.
- Hardening produksi aktif saat `DEBUG=False`, termasuk secure cookie dan header keamanan terkait.
- Dukungan `CSRF_TRUSTED_ORIGINS`, backend email berbasis environment, dan batas field upload yang dinaikkan untuk form LPLPO berukuran besar.
- Error umum `400/403/404/500` dirender lewat halaman khusus yang konsisten, mencatat event ke logger aplikasi, dan menyediakan tombol kembali ke halaman sebelumnya dengan fallback dinamis ke login atau dashboard.
- Route `/maintenance/` tersedia sebagai halaman maintenance/manual preview dengan status `503 Service Unavailable`.

## Dokumentasi

- `docs/developer_guide.md`: panduan developer untuk setup lokal, testing, versioning, seed, import, dan tata kelola dokumentasi.
- `docs/FEATURE_ALOKASI.md`: spesifikasi fitur Alokasi dan aturan bisnis.
- `docs/ALLOCATION_IMPLEMENTATION.md`: draft rancangan awal pemisahan modul Alokasi (referensi historis).
- `SYSTEM_MODEL.md`: referensi skema data dan peta workflow.
- `CHANGELOG.md`: riwayat perubahan dan rilis.
- `backend/seed/README.md`: spesifikasi template CSV seed.
- `docs/erd.md`: referensi ERD.
- `docs/infrastructure_plan.md`: rencana infrastruktur dan deployment.

## Panduan Developer

Instruksi setup environment, migrasi database, pengujian, versioning, dan proses import tersedia di `docs/developer_guide.md`.

## Bantuan dan Kustomisasi

Untuk kebutuhan implementasi, konsultasi, atau penyesuaian sistem sesuai kebutuhan institusi Anda, silakan hubungi `hatamirais@proton.me`. Dukungan pengembangan dan kustomisasi proyek tersedia sesuai ruang lingkup kebutuhan.

## Lisensi

MIT. Lihat `LICENSE`.
