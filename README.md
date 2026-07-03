# Sistem Manajemen Inventaris Farmasi dan Alat Kesehatan

Platform inventaris berbasis web untuk pengelolaan obat dan alat kesehatan di lingkungan Dinas Kesehatan, khususnya pada bidang atau UPT Instalasi Farmasi. Aplikasi ini dirancang untuk menghadirkan pencatatan yang lebih tertib, proses yang lebih terkendali, dan jejak audit yang lebih mudah ditelusuri.

## Gambaran Singkat

Solusi ini membantu proses inventaris berjalan lebih konsisten melalui alur dokumen yang terstruktur, kontrol akses berbasis peran, dan jejak mutasi stok yang tidak dapat diubah. Platform ini relevan untuk operasional gudang kesehatan yang membutuhkan akurasi batch, keterlacakan sumber dana, dan disiplin administrasi.

## Teknologi Inti

| Lapisan | Teknologi |
| --- | --- |
| Bahasa | Python 3.13+ |
| Framework | Django 6.0.6 |
| Database | PostgreSQL 16 |
| Cache/Broker | None (In-Memory / LocMemCache) |
| Antarmuka | Django Templates + Bootstrap 5 |
| Form | django-crispy-forms + crispy-bootstrap5 |
| Import Data | django-import-export |
| Keamanan | django-axes + django-ratelimit |

## Kapabilitas Utama

- Pengelolaan master barang dan data referensi seperti satuan, kategori, program, terapi obat, sumber dana, lokasi, supplier, dan fasilitas. Barang dapat ditandai sebagai program item `[P]` atau esensial `[E]`, serta dapat dipetakan ke satu atau lebih kelompok terapi obat untuk kebutuhan pelaporan.
- Pencatatan stok per batch dengan pendekatan FEFO agar distribusi lebih terkendali dan masa kedaluwarsa lebih mudah dipantau.
- Alur kerja end-to-end untuk penerimaan, distribusi, recall, barang kedaluwarsa, transfer stok, dan stock opname.
- Dukungan tipe penerimaan bawaan dan tipe kustom melalui `ReceivingTypeOption`, termasuk quick-create dari form penerimaan.
- Pelaporan LPLPO bulanan dan pengajuan permintaan barang secara ad-hoc dari Puskesmas, dengan pembuatan dokumen yang terkunci berurutan dari Januari pada tahun server aktif. Januari diperlakukan sebagai bootstrap tahunan: `stock_awal` tetap diisi manual, sedangkan `penerimaan` dan `harga_satuan` dapat diusulkan dari konfirmasi penerimaan Puskesmas Januari yang sudah `CONFIRMED` memakai total kuantitas dan rata-rata tertimbang harga per item, namun tetap editable oleh operator. Bulan berikutnya membawa carry-over `sisa stok` bulan sebelumnya ke `stock_awal` termasuk bila bernilai negatif, mengisi `penerimaan` dari konfirmasi penerimaan Puskesmas bulan berjalan, dan mengisi `harga_satuan` dari rata-rata tertimbang harga konfirmasi penerimaan bulan berjalan lalu fallback ke harga bulan sebelumnya bila tidak ada penerimaan baru.
- Log `Transaction` yang imutabel untuk seluruh pergerakan stok, sehingga histori tetap terjaga.
- Pengendalian akses melalui kombinasi permission Django dan `ModuleAccess` per pengguna.
- Dukungan import CSV dari Django Admin, termasuk endpoint khusus untuk penerimaan barang yang mengelompokkan baris per `document_number` dan langsung membentuk stok serta `Transaction(IN)`.

## Modul Saat Ini

### Modul aktif

- `items`: CRUD master barang dan lookup, filter daftar termasuk atribut esensial `[E]`, export XLSX daftar barang terfilter untuk kebutuhan operasional, endpoint AJAX untuk pembuatan referensi cepat, serta pengelompokan multi-nilai `Terapi Obat` untuk pelaporan.
- `stock`: daftar stok, daftar transaksi, kartu stok, pencarian stok per lokasi, alur transfer stok antar lokasi, serta halaman baca-saja `Stok Puskesmas` untuk membantu Instalasi Farmasi memantau snapshot stok per Puskesmas dari LPLPO terakhir yang disesuaikan dengan konfirmasi penerimaan terkonfirmasi dan pemakaian rinci setelahnya.
- `receiving`: alur penerimaan reguler dan rencana penerimaan, quick-create referensi dari form, tipe penerimaan kustom, serta lampiran dokumen yang disimpan di private storage dan diunduh lewat route terautentikasi pada detail penerimaan. Untuk pengadaan baru, rencana penerimaan procurement sekarang dibuat otomatis dari kontrak SPJ yang disetujui; dokumen `Receiving(is_planned=True, contract IS NULL)` lama tetap berjalan sebagai scope kompatibilitas.
- `procurement`: sumber kebenaran kontrak SPJ / pengadaan dan dokumen amandemennya. Form SPJ juga mendukung quick-create supplier dan sumber dana tanpa meninggalkan halaman create/edit. Approval kontrak atau amandemen oleh Kepala akan menyinkronkan tepat satu rencana penerimaan procurement terbuka tanpa memutasi stok sampai barang benar-benar diterima.
- `distribution`: alur persiapan, pengajuan, verifikasi, hingga distribusi dengan penugasan petugas per dokumen. Distribusi reguler dan permintaan khusus kini menempatkan kontrol tahap persiapan pada petugas yang ditugaskan, sementara approver memverifikasi dokumen yang sudah diajukan sebelum distribusi. Reset, step-back, dan delete untuk dokumen yang masih mutable mengikuti rule otorisasi object-level yang sama dengan edit/persiapan/pengajuan: petugas yang ditugaskan berwenang, dan approver menjadi fallback hanya bila belum ada penugasan petugas. Permintaan khusus menampilkan nomor dokumen usulan dari rule aktif dan mengharuskan konfirmasi sebelum edit manual. Distribusi draft yang dihasilkan dari LPLPO mengunci baris item serta kuantitas diminta/disetujui pada layar edit agar tahap tersebut dipakai khusus untuk pemilihan batch, catatan, dan petugas, dan dapat dibatalkan untuk mengembalikan LPLPO induk ke Puskesmas sebelum distribusi selesai. Untuk kebutuhan rollout atau catch-up tengah tahun, Instalasi Farmasi juga dapat membuat distribusi LPLPO manual dari modul distribusi tanpa harus menunggu backfill dokumen LPLPO bulanan; distribusi manual ini tetap masuk bucket nomor dan laporan LPLPO, tetapi tidak terhubung ke dokumen LPLPO sumber.
- `allocation`: perencanaan dan orkestrasi pra-distribusi. Lifecycle Draftâ†’Submittedâ†’Approved membuat satu `Distribution` per fasilitas secara otomatis pada saat approval. Allocation yang sudah disetujui dapat dikembalikan ke Submitted oleh approver, yang menghapus child distributions agar approval dapat diulang. Pengurangan stok ditangguhkan ke konfirmasi pengiriman per distribusi.
- `recall`: alur retur ke supplier dari draft sampai selesai.
- `expired`: alur penanganan barang kedaluwarsa dari draft sampai disposal, termasuk halaman alert kedaluwarsa.
- `stock_opname`: proses hitung fisik dan cetak laporan selisih. Dokumen hanya dapat diselesaikan setelah seluruh baris snapshot dihitung, sistem menyimpan petugas penyelesai beserta waktu penyelesaiannya, dan setiap baris hasil snapshot kini memiliki cap waktu `created_at` / `updated_at`.
- `puskesmas`: pengajuan permintaan barang ad-hoc dari unit Puskesmas, konfirmasi penerimaan barang yang benar-benar diterima dari Instalasi Farmasi, master subunit layanan per fasilitas, dan input pemakaian rinci bulanan per ruang tindakan / Puskesmas pembantu. Seluruh surface operasional modul ini sekarang mewajibkan `facility` pada akun untuk semua non-superuser dan selalu membatasi akses objek ke fasilitas akun tersebut. Konfirmasi penerimaan menjadi sumber kebenaran `penerimaan` LPLPO, sementara pemakaian rinci menjadi sumber kebenaran `pemakaian` LPLPO. Dokumen linked receipt confirmation baru memakai checklist tetap per baris `DistributionItem`: operator dapat `Simpan Draft` saat barang belum lengkap dan status draft diberi label jelas pada daftar/detail, sedangkan `Simpan Konfirmasi` hanya berhasil bila semua baris distribusi sudah dicentang sesuai fisik. Hanya dokumen berstatus `CONFIRMED` yang ikut mengisi LPLPO. Dokumen konfirmasi lama hasil migrasi tetap dapat diedit tanpa tautan `distribution` / `distribution_item`, tetapi dokumen baru tetap wajib memakai tautan distribusi.
- `lplpo`: pelaporan pemakaian dan permintaan rutin bulanan dari Puskesmas, termasuk pelacakan `harga_satuan` per baris untuk valuasi aset pada rekap persediaan. Untuk Februari dan seterusnya, autofill `penerimaan` dan `harga_satuan` kini bersumber dari konfirmasi penerimaan Puskesmas bulan berjalan, bukan dari `Distribution`. Saat operator membuka atau menyimpan ulang dokumen `DRAFT` / `REJECTED_PUSKESMAS`, sistem juga me-refresh nilai sumber bulan yang sama dari konfirmasi penerimaan terkonfirmasi dan pemakaian rinci yang sudah ada agar draft lama tidak tertinggal dari data operasional terbaru. Dokumen `DRAFT` / `REJECTED_PUSKESMAS` kini juga mendukung alur input offline berbasis XLSX: operator tetap membuat LPLPO bulanan melalui flow situs biasa, lalu dapat mengekspor workbook dokumen tersebut, mengisi kolom editable secara offline, dan mengimpornya kembali ke dokumen yang sama.
  Super Admin tetap dapat mengelola LPLPO lintas fasilitas. Untuk non-superuser, stage Puskesmas (`DRAFT`, `REJECTED_PUSKESMAS`, edit, submit, delete, XLSX import/export, dan helper prefill) tetap terkunci ke fasilitas akun sendiri. Stage proses Instalasi Farmasi bersifat lintas fasilitas secara terbatas: `GUDANG` memproses dokumen `SUBMITTED`, `PIC_VERIFIED`, dan `REJECTED_PIC`, sedangkan `KEPALA` hanya memakai akses lintas fasilitas pada jalur kompatibilitas legacy `REVIEWED/finalize` serta visibilitas historis `APPROVED` / `CLOSED`.
- Laporan Puskesmas (`Riwayat Penerimaan`, `Riwayat Pemakaian`, `Rincian Persediaan`, dan `Rekap Persediaan`) kini hanya mendukung cakupan lintas fasilitas untuk superuser. Pengguna non-superuser selalu dipaksa ke `facility` akun mereka sendiri dan akan ditolak bila akun belum terhubung ke fasilitas. `Riwayat Penerimaan` menampilkan histori konfirmasi penerimaan Puskesmas, bukan histori dispatch distribusi dari Instalasi Farmasi.
- `users`: manajemen pengguna dan pengaturan cakupan akses modul.

- `core`: dashboard, middleware akses panel admin, pengaturan sistem (label platform login, logo, header dokumen, nama fasilitas, serta template penomoran dokumen distribusi) secara dinamis, placeholder riwayat administrasi terpisah untuk penerimaan serta pengeluaran, dan handler error terpusat untuk `400/403/404/500` plus halaman maintenance `503`.
- `reports`: halaman ringkasan laporan dengan keluaran `rekap`, `penerimaan hibah`, `pengadaan`, `kadaluarsa`, dan `pengeluaran`; laporan `pengeluaran` tetap tersedia sebagai ringkasan gabungan di `/reports/pengeluaran/`, sedangkan riwayat distribusi menyediakan endpoint khusus di `/distribution/report/`, `/distribution/report/special-requests/`, `/distribution/report/allocation/`, dan `/distribution/report/lplpo/`.

## Ringkasan Workflow

- Receiving terencana manual legacy: `DRAFT -> SUBMITTED -> APPROVED -> PARTIAL/RECEIVED -> CLOSED`; receiving plan procurement baru mengikuti approval kontrak/amandemen SPJ lalu dieksekusi pada status `APPROVED -> PARTIAL/RECEIVED -> CLOSED` tanpa approval receiving terpisah.
- Receiving reguler, tipe kustom, atau hasil import: umumnya tercatat sebagai `VERIFIED` setelah posting.
- Procurement contract: `DRAFT -> SUBMITTED -> APPROVED -> CLOSED`; amendment: `DRAFT -> SUBMITTED -> APPROVED`. Approval Kepala hanya menyinkronkan rencana penerimaan procurement, tidak memutasi stok.
- Distribution: `DRAFT -> SUBMITTED -> VERIFIED -> PREPARED -> DISTRIBUTED`, dapat berakhir `REJECTED`, dan dokumen yang belum terdistribusi dapat dikembalikan ke `DRAFT`. Distribution hasil approval Allocation langsung dibuat pada status `VERIFIED`.
- Allocation: `DRAFT -> SUBMITTED -> APPROVED -> PARTIALLY_FULFILLED -> FULFILLED`, dapat berakhir `REJECTED`. Child distributions otomatis dibuat saat approval dan dihapus saat step-back ke SUBMITTED.
- Recall: `DRAFT -> SUBMITTED -> VERIFIED -> COMPLETED`
- Expired: `DRAFT -> SUBMITTED -> VERIFIED -> DISPOSED`
- Stock transfer: `DRAFT -> COMPLETED`
- Stock opname: `DRAFT -> IN_PROGRESS -> COMPLETED`. Status `COMPLETED` hanya diberikan setelah seluruh baris snapshot sudah memiliki `actual_quantity`, lalu sistem merekam `completed_by` dan `completed_at`.
- Distribution: `DRAFT/REJECTED -> PREPARED -> SUBMITTED -> VERIFIED -> DISTRIBUTED`. Petugas yang ditugaskan menyiapkan dokumen, lalu approver memverifikasi dan akhirnya mendistribusikan stok. Distribution hasil approval Allocation tetap langsung dibuat pada status `VERIFIED`. Untuk distribution draft hasil LPLPO, nilai `quantity_requested` dan `quantity_approved` tetap mengikuti hasil LPLPO sumber selama tahap edit; pengguna hanya memilih batch stok dan melengkapi metadata persiapan. Distribusi LPLPO manual yang dibuat dari modul distribution tetap mengikuti workflow distribusi biasa dan tetap bisa diedit selama masih draft/ditolak karena tidak membawa dokumen sumber LPLPO.
- LPLPO: `DRAFT -> SUBMITTED -> PIC_VERIFIED -> APPROVED -> CLOSED` untuk alur aktif. Setelah PIC Gudang meninjau dan menetapkan `pemberian`, sistem langsung membuat dokumen Distribution LPLPO draft dan menandai LPLPO siap distribusi. Status `REVIEWED` dan `REJECTED_PIC` dipertahankan hanya sebagai kompatibilitas untuk dokumen lama yang belum selesai pada alur sebelumnya. Selama distribusi hasil tinjauan itu belum selesai, approver masih dapat membatalkan distribusi tersebut dan mengembalikan LPLPO ke `REJECTED_PUSKESMAS` dengan alasan revisi.
  `Rekap Laporan Persediaan` Puskesmas kini merangkum dimensi nilai aset per kategori dari `harga_satuan` LPLPO.
  Filter `Rincian` dan `Rekap Laporan Persediaan` Puskesmas memakai periode tahunan, triwulan, atau semester.
  LPLPO tidak lagi memakai kolom `pembelian_puskesmas`; `persediaan` dihitung dari `stock_awal + penerimaan`, sehingga sisa stok negatif menjadi indikator langsung bila input stok tidak konsisten.
  Kolom `pemakaian` LPLPO kini dibaca dari modul `Pemakaian Rinci Puskesmas` per fasilitas/periode dan tidak lagi diedit langsung di layar LPLPO.
- Puskesmas Request: `DRAFT -> SUBMITTED -> APPROVED -> REJECTED`

## Model Data Singkat

- Tabel inti inventaris: `items`, `stock`, `transactions`
- Header dokumen: `procurement_contracts`, `procurement_amendments`, `receivings`, `distributions`, `allocations`, `recalls`, `expired_docs`, `stock_transfers`, `stock_opnames`
- Baris dokumen: `procurement_contract_lines`, `procurement_amendment_lines`, `receiving_items`, `receiving_order_items`, `distribution_items`, `allocation_items`, `allocation_item_facilities`, `recall_items`, `expired_items`, `stock_transfer_items`, `stock_opname_items`
- Penugasan petugas: `distribution_staff_assignments`, `allocation_staff_assignments`
- Penghubung fasilitas alokasi: `allocation_facilities`
- Tabel otorisasi: `users`, `user_module_accesses`

Rincian skema kanonis tersedia di `SYSTEM_MODEL.md`.

## Keamanan

- Perlindungan brute-force login menggunakan `django-axes`.
- Rate limiting untuk endpoint POST sensitif seperti perubahan password, mutasi master barang, dan aksi manajemen pengguna menggunakan `django-ratelimit`.
- Endpoint simpan/edit/hapus konfirmasi penerimaan Puskesmas dibatasi melalui `django-ratelimit` dengan knob environment `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT`; pratinjau pemuatan checklist distribusi pada form buat memakai `GET` non-mutasi dan tidak dihitung ke kuota ini. Nama lama `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT` tetap diterima sebagai fallback kompatibilitas.
- Endpoint mutasi pemakaian rinci Puskesmas juga dibatasi melalui `django-ratelimit` dengan knob environment `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT`.
- Endpoint mutasi master barang dan quick-create lookup `items`, serta quick-create supplier/sumber dana pada form receiving dan procurement, dibatasi melalui `django-ratelimit` dengan knob environment `ITEM_MUTATION_RATE_LIMIT`, terpisah dari kuota mutasi modul `users`.
- Endpoint import XLSX LPLPO (`/lplpo/<pk>/import-xlsx/`) dibatasi melalui `django-ratelimit` dengan knob environment `LPLPO_IMPORT_RATE_LIMIT`.
- Validasi kata sandi kuat dengan minimum 10 karakter dan validator kustom tambahan.
- Kombinasi pengamanan sesi dan CSRF dengan `HttpOnly` serta `SameSite=Lax`.
- Hardening produksi aktif saat `DEBUG=False`, termasuk secure cookie dan header keamanan terkait.
- Lampiran `ReceivingDocument` tidak lagi mengandalkan `MEDIA_URL`; file disimpan di `PRIVATE_MEDIA_ROOT` dan hanya diakses melalui endpoint unduh yang membutuhkan login + permission `receiving.view_receiving`.
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
