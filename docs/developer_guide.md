# Panduan Developer

Dokumen ini menampung instruksi teknis dan operasional untuk pengembang yang bekerja di repositori Healthcare IMS.

## Ringkasan

Healthcare IMS dibangun dengan Django 6 dan PostgreSQL untuk mendukung proses inventaris kesehatan yang membutuhkan keterlacakan stok, workflow dokumen, dan kontrol akses yang konsisten.

## Struktur Repositori

```text
dinkes-farmalkes-ims/
|- README.md
|- AGENTS.md
|- SYSTEM_MODEL.md
|- docker-compose.yml
|- .env.example
|- backend/
|  |- manage.py
|  |- requirements.txt
|  |- config/
|  |- apps/
|  |- templates/
|  |- static/
|  |- seed/
|  `- tests/
`- scripts/
```

## Persiapan Lokal

### 1. Clone repositori

```bash
git clone git@github.com:hatamirais/dinkes-farmalkes-ims.git
cd dinkes-farmalkes-ims
```

### 2. Siapkan environment file

```bash
cp .env.example .env
```

Minimal variabel yang perlu diisi:

- `DJANGO_SECRET_KEY`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `ALLOWED_HOSTS`

Variabel opsional yang saat ini dibaca oleh aplikasi:

- `DJANGO_DEBUG` (`DEBUG` remains a lower-priority compatibility fallback)
- `CSRF_TRUSTED_ORIGINS`
- `EMAIL_BACKEND`
- `PRIVATE_MEDIA_ROOT`
- `LOGIN_RATE_LIMIT`
- `USER_BULK_ACTION_RATE_LIMIT`
- `USER_MUTATION_RATE_LIMIT`
- `ITEM_MUTATION_RATE_LIMIT`
- `RECEIVING_MUTATION_RATE_LIMIT`
- `USER_PASSWORD_RESET_RATE_LIMIT`
- `PASSWORD_CHANGE_RATE_LIMIT`
- `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT`
- `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT` (legacy compatibility fallback)
- `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT`
- `PROCUREMENT_MUTATION_RATE_LIMIT`
- `LPLPO_IMPORT_RATE_LIMIT`
- `DATA_UPLOAD_MAX_NUMBER_FIELDS`
- `FEATURE_ALLOCATION_UI_ENABLED`
- `REDIS_URL`
- `DJANGO_LOG_LEVEL`
- `SECURE_SSL_REDIRECT`
- `AUTH_AUDIT_TRUSTED_PROXIES`

Catatan:

- `manage.py`, `config/wsgi.py`, dan `config/asgi.py` sudah default ke `config.settings`, sehingga `DJANGO_SETTINGS_MODULE` tidak perlu diubah untuk setup standar.
- Gunakan `DJANGO_DEBUG=True` untuk development lokal. Nama ini diprioritaskan di atas fallback lama `DEBUG` agar environment variable generik dari tool lain (misalnya `DEBUG=release`) tidak mengaktifkan hardening produksi dan redirect HTTPS secara tidak sengaja.
- `DATA_UPLOAD_MAX_NUMBER_FIELDS` default `10000` untuk mengakomodasi form LPLPO dan form bulk serupa yang mengirim banyak field dalam satu request.
- `FEATURE_ALLOCATION_UI_ENABLED` masih dibaca ke Django settings untuk kompatibilitas dan test override, tetapi route/UI runtime Allocation saat ini tidak bercabang pada flag tersebut; akses tetap dikendalikan oleh permission Django + `ModuleAccess`.
- Endpoint POST sensitif memakai `django-ratelimit`; saat limit terlampaui aplikasi mengembalikan halaman `429` melalui handler error terpusat.
- Delegasi Plh. Kepala dikelola pada `/users/acting-authority/`. Create/revoke memakai bucket `USER_MUTATION_RATE_LIMIT`; record tidak diedit atau dihapus. Form mewajibkan pilihan eksplisit antara periode tertentu dan `Sampai dicabut`; mode kedua menyimpan `ends_at=NULL`. Field tanggal/waktunya memakai aset Flatpickr 4.6.13 yang disimpan lokal di `backend/static/vendor/flatpickr/`, menampilkan format Indonesia 24 jam `DD/MM/YYYY HH:mm`, dan tetap mengirim `YYYY-MM-DDTHH:mm` ke Django. Konflik per modul ditolak oleh validasi aplikasi plus PostgreSQL `ExclusionConstraint` (`btree_gist`), dan rentang tanpa batas atas memblokir delegasi berikutnya sampai record dicabut. Pencabutan hanya tersedia selama aktor masih berwenang mendelegasikan modul terkait; endpoint mengunci dan memuat ulang aktor serta `ModuleAccess` sebelum mengunci row delegasi dan memeriksa ulang kewenangannya. Aksi approval harus memakai resolver di `apps.users.access`, mengunci/revalidasi delegasi sebelum row workflow dengan urutan yang konsisten, dan menulis `AuthorityExercise` hanya setelah mutasi workflow berhasil. Akun `ADMIN_UMUM`/`GUDANG` boleh diberi fasilitas Puskesmas aktif secara opsional untuk delegasi Puskesmas/LPLPO; jenis fasilitas lain ditolak dan `PUSKESMAS` tidak pernah menjadi delegat. Target yang sudah direferensikan `AuthorityExercise` dilindungi dari hard delete, termasuk bulk/queryset delete. View approval harus menandai fallback delegasi sebelum outer `perm_required` dijalankan; generated Distribution dari Allocation membaca signature Plh. dari exercise `approve` induk tanpa membuat exercise `verify` turunan. Queue LPLPO untuk `GUDANG` tetap lintas fasilitas pada status operasional biasa, tetapi tambahan legacy `REVIEWED` dari delegasi harus selalu difilter ke `user.facility` dan hanya muncul selama delegasi aktif.
- Pada workflow permintaan Puskesmas, delegasi hanya membuka approve/reject yang diaudit dan tidak membuka reset-to-draft; reset tersebut tetap membutuhkan kewenangan review permanen atau kewenangan manage yang sesuai.
- Saat membuat delegasi, jalur penyimpanan mengunci dan memuat ulang pemberi, delegat, serta `ModuleAccess` terkait dalam urutan stabil; delegasi Puskesmas/LPLPO juga mengunci dan memastikan fasilitas delegat merupakan Puskesmas aktif sebelum satu pun row delegasi dibuat.
- Resolver approval transaksional memakai urutan lock `User -> ModuleAccess -> Facility (untuk Puskesmas/LPLPO) -> AuthorityDelegation -> row workflow`; fasilitas delegat harus tetap berupa Puskesmas aktif, dan waktu efektif serta kelayakan aktor diperiksa setelah lock terkait diperoleh. Field aktor checkpoint serta snapshot `AuthorityExercise` memakai aktor yang dimuat ulang oleh resolver, bukan objek sesi yang mungkin sudah usang.
- Mutasi delegasi yang dibatasi fasilitas (permintaan Puskesmas dan kompatibilitas legacy LPLPO) memeriksa ulang fasilitas aktor terkunci terhadap objek workflow terkunci sebelum perubahan status, lalu memakai aktor terkunci untuk ownership dan snapshot audit.
- Log autentikasi, error terpusat, dan lockout IP `django-axes` memakai `REMOTE_ADDR` sebagai IP klien default. Isi `AUTH_AUDIT_TRUSTED_PROXIES` hanya dengan IP/CIDR reverse proxy langsung yang Anda kontrol dan yang menghapus header `X-Forwarded-For` dari client sebelum menulis nilainya sendiri. Jika deployment berada di belakang reverse proxy tetapi setting ini kosong atau salah, counter IP Axes dapat memakai IP proxy bersama dan mengunci banyak pengguna yang tidak terkait selama cooldown.
- Perubahan create/update/delete pada model penting dicatat melalui `django-auditlog`. Webview awalnya tersedia di Django Admin `/admin/` sebagai `LogEntry` untuk staff/admin yang berwenang.
- Auditlog bersifat signal-driven; `bulk_create`, `bulk_update`, dan `QuerySet.update()` tidak otomatis menghasilkan audit entry per objek. Untuk jalur bulk yang kritis, tambahkan log eksplisit atau test yang mendokumentasikan gap tersebut. Bulk activate/deactivate user memakai per-row `save(update_fields=["is_active"])` dengan row lock agar perubahan status akun tetap tercatat.
- `stock.Transaction` tetap menjadi ledger mutasi stok yang authoritative dan append-only; jangan menggantinya dengan auditlog.
- Mutasi simpan/edit/hapus konfirmasi penerimaan Puskesmas (`/puskesmas/penerimaan/*`) juga memakai `django-ratelimit`; gunakan `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput operator fasilitas. Pratinjau pemuatan baris distribusi pada form buat berjalan lewat `GET` non-mutasi dan tidak memakai kuota ini. Nama lama `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT` tetap dibaca sebagai fallback kompatibilitas.
- Mutasi pemakaian rinci Puskesmas (`/puskesmas/pemakaian/*`) juga memakai `django-ratelimit`; gunakan `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput operator fasilitas.
- Form matriks pemakaian rinci menampilkan Total per barang dari kolom Poli/Pustu. `puskesmas-consumption-total.js` memperbarui tampilan saat input berubah; nilai Total tidak dikirim sebagai field POST. Server tetap memvalidasi dan menjumlahkan field `qty_<item>_<subunit>`.
- Form buat/edit permintaan Puskesmas memakai `items` inline formset. `puskesmas-form.js` menambah baris dengan menaikkan `items-TOTAL_FORMS` dan menginisialisasi ulang pencarian barang; penghapusan baris menandai `items-<index>-DELETE` tanpa memutus indeks, mempertahankan ID baris lama, dan menonaktifkan input editable agar validasi browser tidak menghalangi simpan. Satu baris tetap terlihat. Validasi jumlah dan fasilitas tetap dilakukan server.
- Daftar permintaan Puskesmas hanya memakai filter pencarian dan status; parameter lama `program` pada URL diabaikan. Form dan detail tidak menampilkan Program tingkat dokumen, tetapi field nullable tetap tersimpan untuk data historis dan alur distribusi. Penanda `[P]` pada barang tetap tampil di detail.
- Mutasi create/update/delete barang dan quick-create lookup pada modul `items`, serta quick-create supplier/sumber dana pada form `receiving` dan `procurement`, juga memakai `django-ratelimit`; gunakan `ITEM_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput operator katalog tanpa memakan kuota mutasi modul `users`.
- Mutasi koreksi/batal penerimaan reguler (`/receiving/<pk>/edit/`, `/receiving/<pk>/delete/`) juga memakai `django-ratelimit`; gunakan `RECEIVING_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput koreksi petugas gudang.
- Mutasi impor XLSX LPLPO (`/lplpo/<pk>/import-xlsx/`) juga memakai `django-ratelimit`; gunakan `LPLPO_IMPORT_RATE_LIMIT` bila perlu menyesuaikan throughput input offline per operator.
- Mutasi modul `procurement` (`/procurement/*`) juga memakai `django-ratelimit`; gunakan `PROCUREMENT_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput pembuatan, pengajuan, approval, pembatalan, penutupan, dan amandemen SPJ.
- Surface mobile/PWA tersedia di `/mobile/` dan tetap memakai login/session, CSRF, permission Django, serta fallback `ModuleAccess` yang sama dengan aplikasi utama. Shell desktop menampilkan discovery link untuk pengguna yang dapat melihat stok atau menyetujui Distribusi/Kedaluwarsa. Pintasan PWA dan brand mobile menuju `/mobile/`, yang membuka stok bagi pengguna dengan akses stok atau antrean bagi approval-only; tanpa keduanya akses ditolak 403. Shell mobile menampilkan panduan install PWA yang dapat ditutup. Alur stok mobile memakai pencarian barang teragregasi lebih dulu, lalu detail batch/lokasi pada kartu stok barang.
- Antrean `/mobile/approvals/` hanya tersedia bagi superuser atau role `ADMIN`/`KEPALA` yang memiliki module scope `APPROVE` pada modul terkait. Antrean menampilkan Distribusi berstatus `SUBMITTED` selain child Allocation dan dokumen Kedaluwarsa berstatus `SUBMITTED`. Detail persetujuan menampilkan sumber dana dan nomor dokumen asal dari layer stok yang dipilih agar approver dapat membedakan batch/lokasi yang tampak sama. Approval Distribusi hanya mereservasi stok; verifikasi Kedaluwarsa langsung mengurangi stok dan menambahkan `Transaction(OUT)`. Seluruh aksi approval mobile wajib memakai POST online dengan CSRF; penyelesaian distribusi dan pemusnahan fisik tetap dilakukan melalui workflow desktop oleh petugas yang berwenang.
- `REDIS_URL` mengaktifkan Django Redis cache untuk `CACHES["default"]`; bila kosong, aplikasi memakai fallback `LocMemCache` untuk development dan test lokal.
- Lampiran dokumen penerimaan disimpan di `PRIVATE_MEDIA_ROOT` dan diunduh melalui route aplikasi yang membutuhkan login, jadi jangan arahkan web server publik langsung ke direktori ini.
- Setelah sebuah migration pernah dibagikan, di-review, atau diaplikasikan di environment mana pun, nama file migration tersebut harus dianggap immutable. Jangan rename, hapus, atau tulis ulang history migration yang sudah terpublikasi; gunakan migration kompatibilitas dan merge migration bila ada dua lineage yang sempat beredar.

### Penomoran dokumen terpusat

- `DocumentNumberRule` menyimpan template/reset/padding yang dapat diubah di `/settings/numbering/`; `/settings/` hanya memuat branding dan identitas umum. `DocumentNumberSequence` adalah counter internal dengan row lock, dan `DocumentNumberIssue` adalah ledger penerbitan/VOID dengan `issued_at` eksplisit. Timestamp riwayat migrasi dibiarkan kosong bila checkpoint aslinya tidak dapat direkonstruksi; waktu migrasi tidak boleh dipakai sebagai waktu penerbitan. Jangan menerbitkan nomor dengan menghitung `MAX(document_number)` atau menambahkan generator pada `model.save()`.
- Panggil `apps.core.numbering.issue_document_number()` di dalam transaksi checkpoint workflow yang sama dengan perubahan status/posting terkait. Gunakan tanggal bisnis objek untuk `business_date`; jangan memakai `timezone.now()` sebagai periode kecuali memang itu tanggal bisnis yang tersimpan.
- Pengulangan pada target yang sama idempotent, tetapi target yang sudah memiliki nomor tanpa issue ledger ditolak. `void_document_number()` menandai ledger dan tidak mengembalikan counter.
- `_document_number_taken()` juga memeriksa nomor nonblank pada baris Distribusi historis bertipe `BORROW_RS` / `SWAP_RS`. Tipe pensiun ini tidak memiliki rule aktif dan tidak boleh diberi metadata issue buatan, tetapi nomornya tetap menjadi reservasi global yang dilewati oleh preview maupun penerbitan semua rule.
- Seluruh workflow saat ini memakai `scope_key` kosong dan token generik `{seq}`, `{year}`, serta `{month}`. Amandemen Procurement memakai counter periodenya sendiri dan tidak menurunkan nomor dari kontrak induk.
- Puskesmas dan dokumen induk LPLPO tetap memakai generator modul masing-masing dan tidak boleh dipindahkan ke ledger ini tanpa keputusan terpisah.
- Data migration backfill ledger bersifat forward-only karena setelah nomor diterbitkan tidak ada reverse migration yang aman untuk mengembalikan counter, issue, nomor draft lama, dan klaim source document secara konsisten. Pada environment development tanpa data produksi, rollback dilakukan dengan reset database atau restore backup sebelum migration; jangan migrate mundur melewati backfill setelah workflow baru dipakai.
- Validasi minimum setelah mengubah numbering: `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `python manage.py test apps.core.tests.test_numbering`, lalu suite workflow modul yang checkpoint-nya berubah.

### 3. Jalankan infrastruktur

```bash
docker compose up -d
```

Compose development mengikat Redis ke `127.0.0.1:6379`, bukan ke semua interface host. Ini menjaga cache tetap dapat diakses oleh Django yang berjalan langsung di host development, sambil mencegah Redis unauthenticated terbuka ke jaringan lokal. Untuk deployment, jalankan Redis pada private network dan/atau aktifkan autentikasi lalu gunakan credential tersebut di `REDIS_URL`.

### 4. Buat virtual environment dan install dependency

Linux atau macOS:

```bash
python -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

Windows PowerShell:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r backend/requirements.txt
```

### 5. Migrasi database dan buat akun admin

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser
```

### 6. Kumpulkan static assets untuk deployment

WhiteNoise melayani hasil `collectstatic` dari `STATIC_ROOT` (`backend/staticfiles`) untuk halaman admin dan aset aplikasi pada deployment. Jalankan perintah ini setelah dependency terpasang dan sebelum menjalankan build/image produksi:

```bash
python manage.py collectstatic --noinput
```

Untuk validasi tanpa menulis file, gunakan:

```bash
python manage.py collectstatic --noinput --dry-run
```

### 7. Jalankan server pengembangan

```bash
python manage.py runserver
```

Alamat aplikasi: `http://localhost:8000`

Alamat admin: `http://localhost:8000/admin/`

Preview halaman maintenance: `http://localhost:8000/maintenance/`

Catatan akun admin:

- Akun dengan role `ADMIN` atau superuser hanya dibuat melalui `python manage.py createsuperuser`.
- Halaman Manajemen Pengguna di dashboard tidak menyediakan pembuatan role `ADMIN`.

## Testing

Metode yang direkomendasikan di Windows adalah menggunakan helper script dari root repositori:

```powershell
.\scripts\run-django-test.ps1 -Target apps.items
.\scripts\run-django-test.ps1 -Target apps.stock_opname
```

Script ini akan berpindah ke direktori `backend/`, mengaktifkan virtual environment bila tersedia, lalu menjalankan test target.
Jika target hanya berupa nama app seperti `apps.items`, script akan menormalkan target itu menjadi `apps.items.tests`.

Opsi tambahan yang tersedia:

- `-KeepDb` untuk mempercepat iterasi test lokal dengan reuse database test.
- `-NoActivate` bila environment Python sudah aktif di shell saat ini.

Alternatif dari dalam direktori `backend/`:

```bash
python manage.py test
python manage.py test apps.items
python manage.py test apps.items.tests.ItemModelTest
python manage.py test apps.items.tests.ItemModelTest.test_generate_kode_barang
```

Untuk prioritas coverage, fase implementasi, dan standar penulisan test, lihat `docs/testing_plan.md`.

### Playwright lokal untuk verifikasi multi-role

Helper ini ditujukan untuk pengujian manual lokal dengan tujuh window Chromium terpisah untuk enam role: `PUSKESMAS`, `GUDANG`, `GUDANG2`, `KEPALA`, `ADMIN_UMUM`, `AUDITOR`, dan `ADMIN`.

Langkah setup dari root repositori:

```powershell
Copy-Item .env.playwright.local.example .env.playwright.local
bun ci
bun run playwright:bootstrap
bun run playwright:open
```

Isi `.env.playwright.local` dengan kredensial akun lokal yang sudah ada di database:

- `PLAYWRIGHT_BASE_URL`
- `PW_PUSKESMAS_USERNAME`, `PW_PUSKESMAS_PASSWORD`
- `PW_GUDANG_USERNAME`, `PW_GUDANG_PASSWORD`
- `PW_GUDANG2_USERNAME`, `PW_GUDANG2_PASSWORD`
- `PW_KEPALA_USERNAME`, `PW_KEPALA_PASSWORD`
- `PW_ADMIN_UMUM_USERNAME`, `PW_ADMIN_UMUM_PASSWORD`
- `PW_AUDITOR_USERNAME`, `PW_AUDITOR_PASSWORD`
- `PW_ADMIN_USERNAME`, `PW_ADMIN_PASSWORD`

Perintah yang tersedia:

- `bun run playwright:install` untuk mengunduh Chromium Playwright.
- `bun run playwright:auth` untuk membuat atau memperbarui profil login tiap role tanpa membuka window manual.
- `bun run playwright:refresh-auth` untuk menghapus profil lokal lalu login ulang dari nol.
- `bun run playwright:open` untuk membuka tujuh window profil memakai sesi persisten yang sudah tersimpan.
- `bun run playwright:test` untuk menjalankan committed browser regression specs di folder `playwright/`.
- `bun run playwright:bootstrap` untuk instal Chromium lalu menyiapkan sesi role awal.

Profil browser disimpan secara lokal di `.playwright-profiles/` dan diabaikan oleh git. Bila password akun berubah atau sesi rusak, jalankan `bun run playwright:refresh-auth` lalu buka kembali window dengan `bun run playwright:open`. Committed specs dipakai hemat untuk regresi frontend yang sulit ditutup oleh test Django saja; helper multi-role tetap tersedia untuk verifikasi manual lintas role. Browser helper masih memakai runtime Node lokal karena peluncuran Chromium persisten macet ketika dijalankan langsung oleh Bun 1.3.14 di Windows.

### Build CSS Tailwind

Gunakan Bun 1.3.14 untuk manajemen paket dan perintah frontend, serta Node.js 24 untuk runtime Tailwind CLI. `bun.lock` mengunci dependensi; instal dengan `bun ci`. Sumber Tailwind berada di `backend/static_src/css/app.css`, di luar `STATICFILES_DIRS`. Hasil produksi yang harus dikomit berada di `backend/static/css/app.tailwind.css`.

```powershell
bun run css:watch
bun run css:build
bun run css:check
```

`css:check` membangun ulang CSS dan gagal jika hasilnya berbeda dari file yang dikomit. `.gitattributes` mempertahankan akhiran baris LF pada CSS hasil build di Windows agar perbandingan byte tetap konsisten dengan output Tailwind. Tailwind memindai template Django, berkas Python app, dan JavaScript proyek yang ditentukan eksplisit di sumber CSS. Nama kelas yang dirangkai secara dinamis tidak dapat dideteksi; tulis token kelas lengkap atau gunakan kelas komponen semantik. CI `.github/workflows/css-check.yml` menjalankan `bun ci` dan `bun run css:check` pada Linux dan Windows ketika sumber, konfigurasi, atau `.gitattributes` berubah.

`backend/templates/dashboard.html`, `backend/templates/dashboard_puskesmas.html`, `backend/templates/items/item_list.html`, formulir Barang/lookup dan konfirmasi hapus Barang, daftar serta formulir akun Manajemen Pengguna, empat template baca-saja stok desktop (daftar stok, pemilih/detail kartu stok, riwayat transaksi), laporan Stok Puskesmas, daftar/detail penerimaan reguler dan terencana, daftar/detail procurement/distribution/allocation/recall/expired/stock-opname dan LPLPO, tujuh template laporan termasuk riwayat penomoran, dan template autentikasi memuat `base_tailwind.html` dan CSS hasil build tanpa Bootstrap CSS. Error terpusat memuat CSS hasil build langsung sebagai halaman standalone. Halaman cetak standalone memakai aturan terisolasi di `backend/static_src/css/print.css`; laporan desktop tetap mempertahankan konten dan formatnya. Override panduan impor Admin memakai `backend/static/admin/css/ims-import.css` dengan variabel tema Django, tanpa memuat stylesheet Tailwind aplikasi. Tombol Cetak antrean LPLPO memakai hook eksternal `data-action="print"` agar sesuai CSP. Kelima halaman mobile/PWA memakai `mobile/base.html` dengan CSS hasil build dari sumber `mobile.css`, tanpa Bootstrap CSS atau bundle JavaScript. `mobile.js` dan Bootstrap Icons tetap dipakai; CSS mobile lama telah dihapus. `base.html` menjadi alias kompatibilitas ke `base_tailwind.html`; `base_bootstrap.html`, Bootstrap CSS, CSS legacy, tema Tom Select Bootstrap dan paket Crispy telah dihapus. Semua form IMS merender bound fields Django melalui komponen proyek. Sidebar dan isi menu pengguna pada kedua base memakai partial bersama di `backend/templates/components/navigation/`. Bootstrap JavaScript tetap aktif pada shell desktop; CSS bridge Tailwind untuk collapse, dropdown, modal, dan flash toast dicatat di `docs/css-refactoring/MIGRATION_LEDGER.md`. Alpine.js ditunda. Deployment Django/WhiteNoise hanya menjalankan `collectstatic` atas CSS hasil build; Bun tidak diperlukan di runtime produksi.

Kontrak visual ada di root `DESIGN.md`, daftar kelas fondasi di `docs/css-refactoring/DESIGN_SYSTEM.md`, dan status halaman di `docs/css-refactoring/MIGRATION_LEDGER.md`. Pratinjau statis `docs/css-refactoring/foundation-preview.html` dipakai untuk QA komponen; halaman itu bukan bagian dari aplikasi. Bila konten, kontrol, tindakan, atau perilaku UI saat ini bertentangan dengan dokumentasi di luar perubahan visual yang disetujui, tanyakan kepada pengguna sebelum mengubah UI tersebut.

## Versioning

Rilis 2.0.0 menandai kontrak presentasi Tailwind setelah implementasi migrasi CSS Wave 1–9 digabung. Audit penutupan dan pengecualian penerimaan PWA/perangkat tercatat di [MIGRATION_CLOSEOUT.md](css-refactoring/MIGRATION_CLOSEOUT.md); jangan menandai issue #309 atau pemeriksaan perangkat lulus tanpa bukti.

Repositori menggunakan semantic versioning dengan format `MAJOR.MINOR.PATCH` pada file `VERSION` di root.

- Melihat versi aktif: `python manage.py app_version`
- Naikkan patch: `python manage.py app_version --patch`
- Naikkan minor: `python manage.py app_version --minor`
- Naikkan major: `python manage.py app_version --major`
- Set versi manual: `python manage.py app_version --set 2.0.0`

Versi aplikasi dibaca dari file `VERSION` saat startup dan ditampilkan di header UI setelah pengguna login.

### Rilis otomatis saat versi berubah

Saat file `VERSION` berubah di branch `main`, GitHub Actions menjalankan `.github/workflows/release-on-version-change.yml` untuk:

- memverifikasi hasil `python manage.py app_version` sama dengan isi file `VERSION`
- menjalankan `python manage.py test apps.core.tests`
- membuat tag git `v<version>` bila belum ada
- membuat GitHub Release untuk tag tersebut

## Seed dan Import

- Template seed tersedia di `backend/seed/`.
- Urutan import kanonis: `units -> categories -> funding_sources -> programs -> therapeutic_classes -> locations -> suppliers -> facilities -> items -> opening balance -> receiving`.
- Lookup `Terapi Obat` di-seed melalui `therapeutic_classes.csv`, lalu relasi itemnya diisi melalui import `items.csv` memakai kolom `therapeutic_classes` berisi satu atau lebih `TherapeuticClass.code` yang dipisahkan `|`.
- Relasi `Terapi Obat` tidak disimpan sebagai kolom fisik pada tabel `items`; admin import `items` akan menulis ke relasi many-to-many `items_therapeutic_classes`.
- `items.kode_barang` tetap menjadi kode internal barang, sedangkan `items.barcode` adalah kolom unik opsional untuk kesiapan workflow pemindaian di masa depan; nilai kosong disimpan sebagai `NULL`.
- Bulk update `Terapi Obat` saat ini masih mengikuti workflow re-import penuh `items.csv` dan dicocokkan berdasarkan `nama_barang`; belum ada importer khusus mapping-only berbasis `kode_barang`.
- Untuk stok awal, gunakan import Saldo Awal admin-only di `/admin/stock/stock/opening-balance/import-csv/`; template kosong dapat diunduh dari `/admin/stock/stock/opening-balance/export-csv-template/`. Upload CSV menjalankan validasi dan pratinjau terlebih dahulu; data baru masuk ke sistem setelah admin menekan `Konfirmasi Import`. Import terkonfirmasi membuat `OpeningBalanceImport`, `OpeningBalanceImportItem`, `Stock`, dan `Transaction(IN, reference_type=INITIAL_IMPORT)` agar saldo awal tidak tercampur dengan penerimaan operasional. Import generik bawaan serta add/change/delete langsung untuk model `Stock` dinonaktifkan supaya stok tidak dapat ditulis tanpa transaksi ledger.
- Import Saldo Awal dibatasi untuk superuser / role `ADMIN`, memakai `effective_date` sebagai tanggal efektif laporan, menolak tanggal efektif di masa depan karena stok diposting langsung, dan menolak nilai `receiving_type` atau `supplier_code` bila kolom tersebut ikut terbawa dari template penerimaan.
- Seluruh baris dalam satu `document_number` saldo awal harus memakai `effective_date` yang sama. CSV Saldo Awal dapat memakai delimiter koma atau titik koma. `document_number` saldo awal tidak boleh sama dengan dokumen receiving atau klaim sumber non-saldo-awal karena nomor tersebut menjadi identitas source layer stok; pengecualian hanya untuk reimport dokumen Saldo Awal lama yang sudah dimigrasikan ke source layer disambiguasi `OBI-...` karena pernah bertabrakan dengan dokumen receiving. Konfirmasi Saldo Awal dan pembuatan Receiving juga mengklaim nomor baru melalui `SourceDocumentNumberClaim` agar klaim lintas workflow terserialisasi di database. `document_number` saldo awal yang sudah diposting boleh dipakai ulang untuk melengkapi import parsial: baris dengan total layer stok yang sudah persis sama dilewati, baris dengan total lebih tinggi memposting selisih quantity saja, sedangkan baris baru diposting ke header import yang sudah ada. `batch_lot` wajib diisi saat reimport dokumen saldo awal yang sudah diposting karena nama batch otomatis untuk nilai kosong memakai nomor baris CSV. `quantity` divalidasi sesuai presisi kolom tujuan, sedangkan `unit_price` mendukung `max_digits=23` dan `decimal_places=10`, menerima koma desimal seperti `8893,31985`, dan tidak boleh negatif. Batch kosong pada import pertama dibuat dengan identitas dokumen, dan stok serta transaksi ledger disimpan sebagai layer `item + lokasi + batch + sumber dana + document_number` atau layer kompatibilitas `OBI-...` untuk collision lama. Baris duplikat untuk layer stok yang sama dalam satu CSV ditolak; gabungkan `quantity` dalam satu baris atau gunakan `batch_lot` / `document_number` berbeda. Konflik `expiry_date` atau exact `unit_price` ditolak dalam layer dokumen sumber yang sama; batch yang sama dari dokumen sumber berbeda tetap dipisah dan tidak dirata-ratakan.
- Import penerimaan mengelompokkan baris berdasarkan `import_group`; baris pertama menjadi header dokumen, sementara `sumber_dana_code` dan `location_code` per baris dapat override nilai header. `import_group` tidak menjadi nomor dokumen resmi.
- Nomor Receiving diterbitkan setelah seluruh grup lolos validasi dan di dalam transaksi yang sama dengan posting stok. Generator melewati nomor yang sudah diklaim dokumen Saldo Awal agar identitas source layer tidak bertabrakan lintas workflow.
- Nomor dokumen Receiving tidak dapat diubah dan klaim `SourceDocumentNumberClaim` tetap disimpan setelah pembatalan/penghapusan agar nomor resmi tidak digunakan ulang.
- Tipe penerimaan divalidasi terhadap baris aktif `ReceivingTypeOption`; migrasi data men-seed tipe sistem `PROCUREMENT` / `Pengadaan` dan `GRANT` / `Hibah`. Baris dengan `requires_supplier=True` wajib memiliki supplier.
- Untuk procurement berbasis SPJ, approval kontrak di modul `procurement` akan membuat atau memperbarui tepat satu planned receiving yang ditautkan ke kontrak tersebut. Route create rencana penerimaan manual di modul `receiving` sekarang mengarahkan pengguna ke form SPJ; dokumen planned receiving tanpa kontrak hanya dipertahankan sebagai kompatibilitas data lama. SPJ dapat dibatalkan secara soft-cancel dengan alasan selama belum ada realisasi penerimaan. Form SPJ juga menyediakan quick-create supplier dan sumber dana serta satu `external_document_number` opsional untuk nomor referensi dari aplikasi lain. Nilai eksternal ini bukan nomor IMS dan tidak memengaruhi counter internal.
- Kolom opsional `receiving_type` pada import penerimaan default ke `GRANT` bila tidak diisi dan nilainya harus cocok dengan `ReceivingTypeOption.code` yang aktif; jangan gunakan default ini untuk saldo awal karena stok bootstrap sudah memiliki import khusus.
- Kolom `expiry_date` pada `receiving.csv` kosong hanya valid untuk item dengan `requires_expiry_date=False`; untuk item lain importer menolak baris tersebut. Data lama yang memakai sentinel `2099-12-31` dimigrasikan ke `NULL` setelah field batch dibuat nullable, lalu item katalog yang terdampak ditandai sebagai `requires_expiry_date=False`. Import penerimaan dan Saldo Awal mengikuti aturan kondisional yang sama untuk nilai `expiry_date` kosong. Nilai sentinel yang sebelumnya sudah tersalin ke histori distribusi (`issued_expiry_date`) dan konfirmasi penerimaan Puskesmas (`expiry_date`) juga dinormalisasi ke `NULL` oleh migrasi lanjutan.
- LPLPO draft/rejected mendukung input offline berbasis XLSX setelah dokumen bulanan dibuat dari flow situs biasa. Operator mengekspor workbook dari dokumen yang sudah ada, mengisi kolom editable secara offline, lalu mengimpornya kembali ke dokumen yang sama; `pemakaian` tetap dibaca dari modul Pemakaian Rinci dan seluruh nilai turunan dihitung ulang saat impor.
- Modul `items` juga menyediakan export XLSX daftar barang aktif dari halaman daftar barang. Export mengikuti filter aktif (termasuk `Esensial`, program, kategori, terapi obat, dan pencarian) sehingga operator dapat menyiapkan data untuk aplikasi eksternal tanpa mengubah rule pemilihan item internal.

Dokumen terkait:

- `docs/FEATURE_ALOKASI.md`: spesifikasi fitur Alokasi
- `docs/ALLOCATION_IMPLEMENTATION.md`: draft rancangan awal modul Alokasi (referensi historis)
- `backend/seed/README.md`
- `README.md`
- `SYSTEM_MODEL.md`

## Tata Kelola Dokumentasi

Gunakan siklus berikut agar dokumentasi tetap sinkron dengan kode:

1. Inventaris seluruh file dokumentasi di root repositori, `docs/`, dan `backend/seed/`.
2. Petakan setiap klaim ke source of truth:
   - model ke `backend/apps/*/models.py`
   - route ke `backend/config/urls.py` dan `backend/apps/*/urls.py`
   - security dan settings ke `backend/config/settings.py`
   - script ke `scripts/`
   - error handler global ke `backend/config/urls.py`, `backend/apps/core/views.py`, dan template di `backend/templates/`
3. Validasi panduan pihak ketiga menggunakan referensi utama:
   - `/django/django`
   - `/websites/django-import-export_readthedocs_io_en`
   - `/jazzband/django-axes`
   - `/jazzband/django-auditlog`
4. Cocokkan environment variables yang terdokumentasi dengan `backend/config/settings.py` dan `.env.example`; jangan mendokumentasikan key yang tidak benar-benar dibaca aplikasi tanpa memberi catatan konteksnya.
5. Klasifikasikan drift dokumentasi berdasarkan tingkat dampak:
   - Critical: skema, workflow, otorisasi, atau perilaku keamanan tidak sesuai
   - Major: command, route, atau environment variable sudah usang
   - Minor: istilah, redaksi, atau format tidak konsisten
6. Perbarui dokumen kanonis terlebih dahulu: `SYSTEM_MODEL.md`, `AGENTS.md`, `README.md`, lalu `backend/seed/README.md` atau dokumen `docs/` yang relevan.
7. Tambahkan metadata verifikasi terakhir dan sumber verifikasinya jika relevan.
8. Lakukan QA dokumentasi sebelum merge:
   - tidak ada route mismatch
   - tidak ada model atau tabel yang keliru
   - command dapat dijalankan sesuai dokumentasi
   - environment key benar-benar tersedia

## Validasi Rincian Persediaan Puskesmas

- Route: `/puskesmas/laporan/persediaan/`. Gunakan akun yang sudah memiliki akses laporan; perubahan kejelasan laporan #219 tidak mengubah hak akses atau sidebar (ditangani terpisah dalam #313).
- Jalankan `.\scripts\run-django-test.ps1 -Target apps.puskesmas.tests.PuskesmasReportViewTests -KeepDb` untuk memeriksa sumber stok, isolasi fasilitas, metadata baseline, penomoran lintas kategori, hasil kosong, dan Excel.
- Periksa layar serta print preview untuk satu fasilitas dan `Semua Fasilitas`: label `Stok Akhir Digital`, bulan batas, status baseline termasuk Draft, rentang penyesuaian, jumlah baris sumber, dan fasilitas yang dilewati harus sama. Nilai nol berbeda dari baseline yang tidak ada. Filter triwulan/semester menentukan batas akhir stok.
- Unduh Excel dan cocokkan baris barang dengan layar. Header tetap pada baris 4 dan barang mulai baris 5; sheet `Sumber dan Cakupan` menyimpan metadata dan fasilitas yang dilewati. Hasil valid tanpa barang tetap menghasilkan workbook berisi penjelasan; filter tidak valid tetap menampilkan error HTML. Teks harus tetap diamankan terhadap formula Excel.
- Verifikasi desktop, viewport sempit, dan print preview; informasi sumber tidak boleh tersembunyi saat mencetak. Setelah mengubah template/CSS jalankan `bun run css:build` dan `bun run css:check`.

## Referensi Teknis

- `AGENTS.md`: orientasi coding agent dan konvensi repositori
- `SYSTEM_MODEL.md`: referensi skema dan workflow utama
- `CHANGELOG.md`: riwayat rilis
- `security-audit/OWASP_TOP10_NON_PERSONAL_INFO_AUDIT_2026-02-27.md`: audit keamanan




### Allocation matrix validation

Create/edit matrix inputs use `alloc_<form_row_index>_<facility_id>` consistently, including existing items. Validation runs before database writes; each form instance supplies its saved item ID. Run `.\scripts\run-django-test.ps1 -Target apps.allocation.tests.AllocationMatrixSaveTest -KeepDb` to verify create, edit, deletion, index/PK collisions and invalid matrix rollback.

### Allocation-generated distribution staff

Approval snapshots all parent staff into each child in the approval transaction. Detail/SBBK use child assignments, falling back to current parent assignments only for historical empty children; no historical backfill is performed. Every assigned name appears in the handover signature list in full-name/username order. Re-approval regenerates the snapshot. Assigned staff do not replace workflow actors or the parent delegated approval signer.

Run `.\scripts\run-django-test.ps1 -Target apps.allocation.tests.AllocationDistributionStaffTest -KeepDb` for multi-staff approval, rendered detail/SBBK, historical fallback, re-approval and standalone checks. For manual print verification, approve an allocation with three staff and two facilities, open each child, and use Cetak SBBK; confirm all three names appear in Petugas and Yang Menyerahkan. Physical print layout remains a manual check.


### Puskesmas report authorization (#313)

The read-only `puskesmas_reports` module is independent of central REPORTS.
PUSKESMAS defaults to VIEW; ADMIN, KEPALA, ADMIN_UMUM, GUDANG, and AUDITOR default
to NONE. NONE explicitly denies access; higher scopes provide only read access.
Without staff capabilities, a reader needs an active Puskesmas facility link and
is forced to it, including for Excel exports and forged facility parameters.

To authorize internal staff, set `Laporan Puskesmas` to VIEW in user module access,
then explicitly assign `users.select_puskesmas_report_facility` through Django
Admin user/group permissions. Also assign `users.aggregate_puskesmas_reports`
only when all-facility aggregation is authorized. Aggregation requires both
permissions; these capabilities cannot widen role PUSKESMAS access. AUDITOR
remains read-only and sees the report submenu without operational navigation.
Selection-only staff default to the first active Puskesmas; invalid selections
denied with 403 never widen to all facilities. Superusers retain full scope.

Deployment: run `python manage.py migrate` to register both custom permissions
and the new module choice. No account/group permission backfill is performed.
Existing accounts without a new module row use role defaults immediately;
new/save provisioning seeds that row. Existing explicit module rows are preserved.
Optional `python manage.py sync_module_access` materializes missing rows without
`--overwrite`; do not reset customized scopes. Existing generic Reports grants
are retained but do not authorize these facility reports. Review staff grants
individually; no staff cross-facility grants are automatic.

Validate with `./scripts/run-django-test.ps1 -Target apps.users.tests -KeepDb`
and `./scripts/run-django-test.ps1 -Target apps.puskesmas.tests.PuskesmasReportViewTests -KeepDb`.
The report tests exercise all four routes, HTML/Excel isolation, explicit denials,
staff capabilities, inactive links, superusers, and sidebar expansion/highlighting.
