# Panduan Developer

Dokumen ini menampung instruksi teknis dan operasional untuk pengembang yang bekerja di repositori Healthcare IMS.

## Ringkasan

Healthcare IMS dibangun dengan Django 6, PostgreSQL, dan Redis untuk mendukung proses inventaris kesehatan yang membutuhkan keterlacakan stok, workflow dokumen, dan kontrol akses yang konsisten.

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
- `DATA_UPLOAD_MAX_NUMBER_FIELDS`
- `SECURE_SSL_REDIRECT`

Catatan:

- `manage.py`, `config/wsgi.py`, dan `config/asgi.py` sudah default ke `config.settings`, sehingga `DJANGO_SETTINGS_MODULE` tidak perlu diubah untuk setup standar.
- `DATA_UPLOAD_MAX_NUMBER_FIELDS` default `10000` untuk mengakomodasi form LPLPO dan form bulk serupa yang mengirim banyak field dalam satu request.

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

## Testing

Metode yang direkomendasikan di Windows adalah menggunakan helper script dari root repositori:

```powershell
.\scripts\run-django-test.ps1 -Target apps.items
.\scripts\run-django-test.ps1 -Target apps.stock_opname
```

Script ini akan berpindah ke direktori `backend/`, mengaktifkan virtual environment bila tersedia, lalu menjalankan test target.

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
- menjalankan `python manage.py test apps.core`
- membuat tag git `v<version>` bila belum ada
- membuat GitHub Release untuk tag tersebut

## Seed dan Import

- Template seed tersedia di `backend/seed/`.
- Urutan import kanonis: `units -> categories -> funding_sources -> programs -> locations -> suppliers -> facilities -> items -> receiving`.
- Untuk stok awal, gunakan `receiving.csv` melalui endpoint import Receiving Admin di `/admin/receiving/receiving/import-csv/` agar stok dan `Transaction(IN)` terbentuk dalam satu alur yang konsisten.
- Import penerimaan mengelompokkan baris berdasarkan `document_number`; baris pertama menjadi header dokumen, sementara `sumber_dana_code` dan `location_code` per baris dapat override nilai header.
- Kolom opsional `receiving_type` pada import penerimaan default ke `GRANT` bila tidak diisi.

Dokumen terkait:

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
