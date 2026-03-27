# Sistem Manajemen Inventaris Farmasi dan Alat Kesehatan

Platform inventaris berbasis web untuk pengelolaan obat dan alat kesehatan di lingkungan Dinas Kesehatan, khususnya pada bidang atau UPT Instalasi Farmasi. Aplikasi ini dirancang untuk menghadirkan pencatatan yang lebih tertib, proses yang lebih terkendali, dan jejak audit yang lebih mudah ditelusuri.

## Gambaran Singkat

Solusi ini membantu proses inventaris berjalan lebih konsisten melalui alur dokumen yang terstruktur, kontrol akses berbasis peran, dan jejak mutasi stok yang tidak dapat diubah. Platform ini relevan untuk operasional gudang kesehatan yang membutuhkan akurasi batch, keterlacakan sumber dana, dan disiplin administrasi.

## Teknologi Inti

| Lapisan | Teknologi |
| --- | --- |
| Bahasa | Python 3.13+ |
| Framework | Django 6.0.2 |
| Database | PostgreSQL 16 |
| Cache/Broker | Redis 7 |
| Antarmuka | Django Templates + Bootstrap 5 |
| Form | django-crispy-forms + crispy-bootstrap5 |
| Import Data | django-import-export |
| Keamanan | django-axes |

## Kapabilitas Utama

- Pengelolaan master barang dan data referensi seperti satuan, kategori, program, sumber dana, lokasi, supplier, dan fasilitas.
- Pencatatan stok per batch dengan pendekatan FEFO agar distribusi lebih terkendali dan masa kedaluwarsa lebih mudah dipantau.
- Alur kerja end-to-end untuk penerimaan, distribusi, recall, barang kedaluwarsa, transfer stok, dan stock opname.
- Log `Transaction` yang imutabel untuk seluruh pergerakan stok, sehingga histori tetap terjaga.
- Pengendalian akses melalui kombinasi permission Django dan `ModuleAccess` per pengguna.
- Dukungan import CSV dari Django Admin, termasuk endpoint khusus untuk penerimaan barang.

## Modul Saat Ini

### Modul aktif

- `items`: CRUD master barang dan lookup, filter daftar, serta endpoint AJAX untuk pembuatan referensi cepat.
- `stock`: daftar stok, daftar transaksi, kartu stok, dan alur transfer stok.
- `receiving`: alur penerimaan reguler dan rencana penerimaan.
- `distribution`: alur permintaan, verifikasi, persiapan, hingga distribusi dengan penugasan petugas per dokumen.
- `recall`: alur retur ke supplier dari draft sampai selesai.
- `expired`: alur penanganan barang kedaluwarsa dari draft sampai disposal, termasuk halaman alert kedaluwarsa.
- `stock_opname`: proses hitung fisik dan cetak laporan selisih.
- `users`: manajemen pengguna dan pengaturan cakupan akses modul.

### Modul pengembangan lanjutan

- `reports`: rute indeks sudah tersedia, tetapi lapisan model masih berupa placeholder.

## Ringkasan Workflow

- Receiving terencana: `DRAFT -> SUBMITTED -> APPROVED -> PARTIAL/RECEIVED -> CLOSED`
- Receiving reguler atau hasil import: umumnya tercatat sebagai `VERIFIED` setelah posting.
- Distribution: `DRAFT -> SUBMITTED -> VERIFIED -> PREPARED -> DISTRIBUTED`, dapat berakhir `REJECTED`, dan dokumen yang belum terdistribusi dapat dikembalikan ke `DRAFT`.
- Recall: `DRAFT -> SUBMITTED -> VERIFIED -> COMPLETED`
- Expired: `DRAFT -> SUBMITTED -> VERIFIED -> DISPOSED`
- Stock transfer: `DRAFT -> COMPLETED`
- Stock opname: `DRAFT -> IN_PROGRESS -> COMPLETED`

## Model Data Singkat

- Tabel inti inventaris: `items`, `stock`, `transactions`
- Header dokumen: `receivings`, `distributions`, `recalls`, `expired_docs`, `stock_transfers`, `stock_opnames`
- Baris dokumen: `receiving_items`, `receiving_order_items`, `distribution_items`, `recall_items`, `expired_items`, `stock_transfer_items`, `stock_opname_items`
- Penugasan petugas distribusi: `distribution_staff_assignments`
- Tabel otorisasi: `users`, `user_module_accesses`

Rincian skema kanonis tersedia di `SYSTEM_MODEL.md`.

## Keamanan

- Perlindungan brute-force login menggunakan `django-axes`.
- Kombinasi pengamanan sesi dan CSRF dengan `HttpOnly` serta `SameSite=Lax`.
- Hardening produksi aktif saat `DEBUG=False`, termasuk secure cookie dan header keamanan terkait.

## Dokumentasi

- `docs/developer_guide.md`: panduan developer untuk setup lokal, testing, versioning, seed, import, dan tata kelola dokumentasi.
- `SYSTEM_MODEL.md`: referensi skema data dan peta workflow.
- `CHANGELOG.md`: riwayat perubahan dan rilis.
- `backend/seed/README.md`: spesifikasi template CSV seed.
- `docs/README.md`: catatan workflow import dan migrasi.
- `docs/system_design_renew.md`: narasi desain fungsional dan arsitektur.
- `docs/erd.md`: referensi ERD.
- `docs/infrastructure_plan.md`: rencana infrastruktur dan deployment.

## Panduan Developer

Instruksi setup environment, migrasi database, pengujian, versioning, dan proses import dipindahkan ke `docs/developer_guide.md` agar README tetap fokus sebagai gambaran produk dan titik masuk utama repositori.

## Bantuan dan Kustomisasi

Untuk kebutuhan implementasi, konsultasi, atau penyesuaian sistem sesuai kebutuhan institusi Anda, silakan hubungi `hatamirais@proton.me`. Dukungan pengembangan dan kustomisasi proyek tersedia sesuai ruang lingkup kebutuhan.

## Lisensi

MIT. Lihat `LICENSE`.
