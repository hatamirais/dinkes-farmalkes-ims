# Program Pengujian Bertahap

Dokumen di folder ini menggantikan pendekatan satu dokumen rencana uji dengan program pengujian bertahap yang lebih formal, terstruktur, dan selaras dengan praktik rekayasa perangkat lunak yang baik.

## Tujuan Program

- Membangun cakupan pengujian secara bertahap berdasarkan dependency dan risiko bisnis.
- Menerapkan gerbang mutu per modul: satu modul direncanakan, direview, lalu baru dilanjutkan ke modul berikutnya.
- Menstandarkan struktur dokumen agar setiap modul memiliki tujuan, cakupan, risiko, matriks skenario, kriteria masuk, dan kriteria selesai yang konsisten.

## Standar Yang Digunakan

Program ini mengikuti prinsip umum yang lazim dipakai pada tim QA dan software engineering modern:

- Pengujian berbasis risiko: prioritas ditentukan oleh dampak bisnis dan peluang kegagalan.
- Piramida pengujian: lebih banyak pengujian unit dan layanan, lebih sedikit pengujian integrasi yang berat di UI.
- Shift-left testing: aturan bisnis divalidasi sedekat mungkin dengan model, form, service, signal, dan kontrak view.
- Keterlacakan: setiap modul memiliki pemetaan yang jelas antara area risiko dan target pengujian.
- Review bertahap: satu rencana per modul direview sebelum dilanjutkan ke modul berikutnya.
- Disiplin regresi: setiap defect penting harus menghasilkan regression test.

## Struktur Dokumen Per Modul

Setiap file rencana pengujian modul wajib memuat:

1. Tujuan
2. Cakupan yang diuji
3. Cakupan di luar pengujian
4. Dependency dan modul terkait
5. Penilaian risiko
6. Tingkat pengujian
7. Matriks skenario
8. Strategi data uji
9. Kriteria masuk
10. Kriteria selesai
11. Hasil akhir yang diharapkan
12. Urutan pelaksanaan yang direkomendasikan

## Urutan Tahap Semua Modul

Urutan ini disusun dari fondasi sistem ke alur kerja bisnis tingkat atas.

### Tahap 1: Fondasi Integritas Inventaris

- `stock`

Alasan:

- Menjadi fondasi mutasi stok, buku besar transaksi, kartu stok, mutasi lokasi, dan API pencarian stok.
- Hampir semua alur kerja lain bergantung pada ketepatan modul ini.

### Tahap 2: Fondasi Keandalan Data Master

- `items`

Alasan:

- Menentukan validitas referensi item, satuan, kategori, program, lokasi, sumber dana, pemasok, dan fasilitas.
- Kegagalan di sini menyebar ke `receiving`, `distribution`, `stock`, dan `reports`.

### Tahap 3: Lapisan Akses dan Platform Bersama

- `core`
- `users`

Alasan:

- Menentukan kontrol akses, perilaku decorator, dashboard bersama, sinkronisasi role/group, dan fallback module scope.

### Tahap 4: Alur Masuk Inventaris

- `receiving`

Alasan:

- Menjadi titik masuk utama penambahan stok dan sumber transaksi `IN`.
- Memiliki impor CSV, penerimaan reguler, penerimaan terencana, dan pengembalian RS.

### Tahap 5: Alur Keluar Inventaris

- `distribution`

Alasan:

- Merupakan alur kerja stok keluar paling penting dan paling sensitif secara operasional.
- Memiliki cabang bisnis tambahan: `LPLPO`, `BORROW_RS`, dan `SWAP_RS`.

### Tahap 6: Alur Retur dan Pemusnahan

- `recall`
- `expired`

Alasan:

- Keduanya mengurangi stok dan menulis `Transaction(OUT)` dengan aturan bisnis yang berbeda.

### Tahap 7: Rekonsiliasi dan Pengendalian Fisik

- `stock_opname`

Alasan:

- Menjadi kontrol fisik atas akurasi stok sistem.
- Harus memverifikasi perilaku selisih, bukan hanya akses.

### Tahap 8: Permintaan Fasilitas dan Perencanaan Rutin

- `puskesmas`
- `lplpo`

Alasan:

- Sangat bergantung pada isolasi fasilitas, alur kerja lintas modul, dan tautan ke `distribution`.

### Tahap 9: Pelaporan dan Dukungan Keputusan

- `reports`

Alasan:

- Bergantung pada akurasi semua modul di hulu.
- Paling tepat direncanakan setelah transaksi inti memiliki cakupan dasar yang kuat.

## Alur Review

- Detail rencana hanya dibuat untuk satu modul aktif pada satu waktu.
- Setelah modul aktif direview dan disetujui, barulah dilanjutkan ke file rencana modul berikutnya.
- Jika ada koreksi pada format atau kedalaman bahasan, format itu dibawa ke modul-modul berikutnya agar tetap konsisten.

## Dokumen Peta Jalan Program

Peta jalan tingkat program tersedia di:

- [PROGRAM-STAGE-ROADMAP.md](PROGRAM-STAGE-ROADMAP.md)

## Modul Yang Sudah Disiapkan

- [01-stock-module-test-plan.md](01-stock-module-test-plan.md)
- [02-items-module-test-plan.md](02-items-module-test-plan.md)
- [03-users-uac-module-test-plan.md](03-users-uac-module-test-plan.md)
- [04-users-crud-module-test-plan.md](04-users-crud-module-test-plan.md)
- [05-core-module-test-plan.md](05-core-module-test-plan.md)
- [06-receiving-module-test-plan.md](06-receiving-module-test-plan.md)
- [07-distribution-module-test-plan.md](07-distribution-module-test-plan.md)
- [08-recall-module-test-plan.md](08-recall-module-test-plan.md)

## Modul Aktif Saat Ini

Modul aktif untuk review berikutnya:

- [08-recall-module-test-plan.md](08-recall-module-test-plan.md)

## Aturan Hasil Akhir

- Nama file memakai awalan numerik untuk menjaga urutan review.
- Satu file hanya untuk satu modul utama.
- Modul terkait boleh disebut di dalam rencana, tetapi tidak dibuatkan file terpisah sampai modul tersebut menjadi giliran aktif.
