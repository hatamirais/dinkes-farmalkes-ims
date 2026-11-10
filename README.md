# Sistem Manajemen Inventaris Farmasi dan Alat Kesehatan

Platform inventaris berbasis web untuk pengelolaan obat dan alat kesehatan di lingkungan Dinas Kesehatan, khususnya bidang atau UPT Instalasi Farmasi.

## Kapabilitas Utama

- Master barang dan referensi fasilitas, supplier, lokasi, serta sumber dana.
- Stok per batch dan dokumen sumber, pemilihan FEFO, reservasi, serta ledger mutasi stok.
- Pengadaan, penerimaan, alokasi, distribusi, recall, penanganan kedaluwarsa, transfer, dan stock opname.
- Operasional Puskesmas: konfirmasi penerimaan, pemakaian rinci, permintaan barang, dan LPLPO bulanan.
- Laporan inventaris, kontrol akses, delegasi wewenang sementara, dan audit perubahan.
- Antarmuka mobile/PWA untuk pencarian stok dan persetujuan yang didukung.

Rincian modul dan aturan operasional tersedia di [referensi fungsional aplikasi](docs/application_reference.md).

## Teknologi

Django dengan template server-rendered, PostgreSQL, Tailwind CSS, dan WhiteNoise. Redis dipakai bila dikonfigurasi. Desktop mempertahankan Bootstrap JavaScript; Django Admin memakai styling native.

Versi dependensi ada di [requirements.txt](backend/requirements.txt) dan [package.json](package.json); versi aplikasi ada di [VERSION](VERSION).

## Mulai Mengembangkan

Ikuti [panduan developer](docs/developer_guide.md#persiapan-lokal) untuk konfigurasi environment, PostgreSQL/Redis lokal, instalasi dependensi, migrasi, dan menjalankan server.

- [Pengujian Django dan Playwright](docs/developer_guide.md#testing)
- [Build dan pemeriksaan CSS](docs/developer_guide.md#build-css-tailwind)
- [Seed dan import CSV](backend/seed/README.md)

Import pengguna dilakukan dari **Manajemen Pengguna → Import CSV**. Deployment harus menjalankan migrasi dan menjadwalkan `python manage.py cleanup_user_imports` setiap 15 menit; lihat [kontrak import pengguna](backend/seed/README.md#user-creation-csv-main-application).

## Peta Dokumentasi

| Kebutuhan | Referensi |
| --- | --- |
| Seluruh dokumentasi | [Indeks docs](docs/README.md) |
| Kapabilitas dan workflow aplikasi | [Referensi fungsional](docs/application_reference.md) |
| Setup, testing, tooling, dan rilis | [Panduan developer](docs/developer_guide.md) |
| Skema, route, izin, dan checkpoint stok | [System model](SYSTEM_MODEL.md) |
| Aturan kerja coding agent | [AGENTS.md](AGENTS.md) dan panduan tiap app |
| Kontrak visual UI | [DESIGN.md](DESIGN.md) |
| Riwayat rilis | [CHANGELOG.md](CHANGELOG.md) |

Catatan implementasi dan rencana historis diindeks terpisah di `docs/`; kode menjadi sumber kebenaran bila ada perbedaan dengan dokumentasi.

## Bantuan dan Kustomisasi

Untuk implementasi, konsultasi, atau penyesuaian sistem, hubungi `hatamirais@proton.me`.

## Lisensi

MIT. Lihat [LICENSE](LICENSE).
