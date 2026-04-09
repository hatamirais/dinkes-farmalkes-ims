# Panduan Developer

Dokumen ini menampung instruksi teknis dan operasional untuk pengembang yang bekerja di repositori Healthcare IMS.

## Ringkasan

Healthcare IMS dibangun dengan Django 6, PostgreSQL, dan Redis untuk mendukung proses inventaris kesehatan yang membutuhkan keterlacakan stok, workflow dokumen, dan kontrol akses yang konsisten.

## Struktur Repositori

```text
Healthcare-Inventory-Management-System/
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
git clone git@github.com:ahliweb/Healthcare-Inventory-Management-System.git
cd Healthcare-Inventory-Management-System
```

### 2. Siapkan environment file

```bash
cp .env.example .env
```

Minimal variabel yang perlu diisi:

- `DJANGO_SECRET_KEY`
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `ALLOWED_HOSTS`

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
4. Klasifikasikan drift dokumentasi berdasarkan tingkat dampak:
   - Critical: skema, workflow, otorisasi, atau perilaku keamanan tidak sesuai
   - Major: command, route, atau environment variable sudah usang
   - Minor: istilah, redaksi, atau format tidak konsisten
5. Perbarui dokumen kanonis terlebih dahulu: `SYSTEM_MODEL.md`, `AGENTS.md`, `README.md`, lalu `backend/seed/README.md` atau dokumen `docs/` yang relevan.
6. Tambahkan metadata verifikasi terakhir dan sumber verifikasinya jika relevan.
7. Lakukan QA dokumentasi sebelum merge:
   - tidak ada route mismatch
   - tidak ada model atau tabel yang keliru
   - command dapat dijalankan sesuai dokumentasi
   - environment key benar-benar tersedia

## Referensi Teknis

- `AGENTS.md`: orientasi coding agent dan konvensi repositori
- `SYSTEM_MODEL.md`: referensi skema dan workflow utama
- `CHANGELOG.md`: riwayat rilis
- `security-audit/OWASP_TOP10_NON_PERSONAL_INFO_AUDIT_2026-02-27.md`: audit keamanan
