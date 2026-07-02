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

- `DEBUG`
- `CSRF_TRUSTED_ORIGINS`
- `EMAIL_BACKEND`
- `PRIVATE_MEDIA_ROOT`
- `USER_BULK_ACTION_RATE_LIMIT`
- `USER_MUTATION_RATE_LIMIT`
- `ITEM_MUTATION_RATE_LIMIT`
- `USER_PASSWORD_RESET_RATE_LIMIT`
- `PASSWORD_CHANGE_RATE_LIMIT`
- `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT`
- `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT` (legacy compatibility fallback)
- `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT`
- `PROCUREMENT_MUTATION_RATE_LIMIT`
- `LPLPO_IMPORT_RATE_LIMIT`
- `DATA_UPLOAD_MAX_NUMBER_FIELDS`
- `FEATURE_ALLOCATION_UI_ENABLED`
- `DJANGO_LOG_LEVEL`
- `SECURE_SSL_REDIRECT`

Catatan:

- `manage.py`, `config/wsgi.py`, dan `config/asgi.py` sudah default ke `config.settings`, sehingga `DJANGO_SETTINGS_MODULE` tidak perlu diubah untuk setup standar.
- `DATA_UPLOAD_MAX_NUMBER_FIELDS` default `10000` untuk mengakomodasi form LPLPO dan form bulk serupa yang mengirim banyak field dalam satu request.
- `FEATURE_ALLOCATION_UI_ENABLED` masih dibaca ke Django settings untuk kompatibilitas dan test override, tetapi route/UI runtime Allocation saat ini tidak bercabang pada flag tersebut; akses tetap dikendalikan oleh permission Django + `ModuleAccess`.
- Endpoint POST sensitif memakai `django-ratelimit`; saat limit terlampaui aplikasi mengembalikan halaman `429` melalui handler error terpusat.
- Mutasi simpan/edit/hapus konfirmasi penerimaan Puskesmas (`/puskesmas/penerimaan/*`) juga memakai `django-ratelimit`; gunakan `PUSKESMAS_RECEIPT_CONFIRMATION_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput operator fasilitas. Pratinjau pemuatan baris distribusi pada form buat berjalan lewat `GET` non-mutasi dan tidak memakai kuota ini. Nama lama `PUSKESMAS_SBBK_MUTATION_RATE_LIMIT` tetap dibaca sebagai fallback kompatibilitas.
- Mutasi pemakaian rinci Puskesmas (`/puskesmas/pemakaian/*`) juga memakai `django-ratelimit`; gunakan `PUSKESMAS_CONSUMPTION_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput operator fasilitas.
- Mutasi create/update/delete barang dan quick-create lookup pada modul `items` juga memakai `django-ratelimit`; gunakan `ITEM_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput operator katalog tanpa memakan kuota mutasi modul `users`.
- Mutasi impor XLSX LPLPO (`/lplpo/<pk>/import-xlsx/`) juga memakai `django-ratelimit`; gunakan `LPLPO_IMPORT_RATE_LIMIT` bila perlu menyesuaikan throughput input offline per operator.
- Mutasi modul `procurement` (`/procurement/*`) juga memakai `django-ratelimit`; gunakan `PROCUREMENT_MUTATION_RATE_LIMIT` bila perlu menyesuaikan throughput pembuatan, pengajuan, approval, dan amandemen SPJ.
- Lampiran dokumen penerimaan disimpan di `PRIVATE_MEDIA_ROOT` dan diunduh melalui route aplikasi yang membutuhkan login, jadi jangan arahkan web server publik langsung ke direktori ini.
- Setelah sebuah migration pernah dibagikan, di-review, atau diaplikasikan di environment mana pun, nama file migration tersebut harus dianggap immutable. Jangan rename, hapus, atau tulis ulang history migration yang sudah terpublikasi; gunakan migration kompatibilitas dan merge migration bila ada dua lineage yang sempat beredar.

### 3. Jalankan infrastruktur

```bash
docker compose up -d
```

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

### 6. Jalankan server pengembangan

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

## Versioning

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
- Urutan import kanonis: `units -> categories -> funding_sources -> programs -> therapeutic_classes -> locations -> suppliers -> facilities -> items -> receiving`.
- Lookup `Terapi Obat` di-seed melalui `therapeutic_classes.csv`, lalu relasi itemnya diisi melalui import `items.csv` memakai kolom `therapeutic_classes` berisi satu atau lebih `TherapeuticClass.code` yang dipisahkan `|`.
- Relasi `Terapi Obat` tidak disimpan sebagai kolom fisik pada tabel `items`; admin import `items` akan menulis ke relasi many-to-many `items_therapeutic_classes`.
- Bulk update `Terapi Obat` saat ini masih mengikuti workflow re-import penuh `items.csv` dan dicocokkan berdasarkan `nama_barang`; belum ada importer khusus mapping-only berbasis `kode_barang`.
- Untuk stok awal, gunakan `receiving.csv` melalui endpoint import Receiving Admin di `/admin/receiving/receiving/import-csv/` agar stok dan `Transaction(IN)` terbentuk dalam satu alur yang konsisten.
- Import penerimaan mengelompokkan baris berdasarkan `document_number`; baris pertama menjadi header dokumen, sementara `sumber_dana_code` dan `location_code` per baris dapat override nilai header.
- Untuk procurement baru, jangan buat rencana penerimaan manual di modul `receiving`; approval kontrak SPJ di modul `procurement` akan membuat atau memperbarui tepat satu planned receiving yang ditautkan ke kontrak tersebut.
- Kolom opsional `receiving_type` pada import penerimaan default ke `GRANT` bila tidak diisi.
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

## Referensi Teknis

- `AGENTS.md`: orientasi coding agent dan konvensi repositori
- `SYSTEM_MODEL.md`: referensi skema dan workflow utama
- `CHANGELOG.md`: riwayat rilis
- `security-audit/OWASP_TOP10_NON_PERSONAL_INFO_AUDIT_2026-02-27.md`: audit keamanan
