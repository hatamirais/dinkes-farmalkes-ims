# TODO LIST

## Version 1

1. ~~Create new module for Instalasi Farmasi to handle borrowing and swapping items between them and Rumah Sakit~~
2. ~~Ensure `Permintaan Khusus` flow is connected with the Instalasi Farmasi distribution flow~~
3. ~~Laporan are~~:
   - ~~Laporan persediaan triwulan, semester, dan tahun~~
   - ~~Laporan penerimaan hibah provinsi~~
   - ~~Laporan pengadaan~~
   - ~~Laporan kadaluarsa~~
   - ~~Laporan pengeluaran~~
4. ~~Create new tags for the Items if the items is part of Essensial~~
5. ~~Create new part on the Dashboard telling Instalasi Farmasi that there is a new request~~
6. Do another security audit using:
   - OWASP top 10
   - ISO 27001
   - OWASP ASVS level 2
7. ~~Add in-app settings for the Dashboard (logo, facility names, header fields) to use when generating document headers~~
8. ~~Test the remaining Alokasi flow end-to-end, especially submit, approve, generated distribution creation per facility, and delivery-progress synchronization.~~
9. ~~Implement institutional document numbering rules for generated distribution documents~~:
   - ~~LPLPO distribution format follows paper numbering: `440/{seq}/SBBK.RF/{year}`~~
   - ~~Permintaan Khusus distribution format follows paper numbering: `440/{seq}/KD.F/{year}`~~
   - ~~Counter is separate for each rule/template~~
   - ~~Counter resets yearly~~
   - ~~Use the full formatted value as `document_number`~~
10. ~~Refactor document number generation into a shared numbering service/helper instead of keeping rule logic duplicated inside model `save()` methods.~~
11. ~~Update distribution numbering generation to branch by `distribution_type`~~:

    - ~~`LPLPO` uses the `SBBK.RF` rule~~
    - ~~`SPECIAL_REQUEST` uses the `KD.F` rule~~
    - ~~keep existing numbering for other distribution types unless a new institutional rule is defined~~

12. ~~Add focused tests for numbering behavior~~:

    - ~~sequence increments correctly for LPLPO documents~~
    - ~~sequence increments correctly for Permintaan Khusus documents~~
    - ~~counters are independent between LPLPO and Permintaan Khusus~~
    - ~~counters reset per year~~
    - ~~legacy document numbers do not break the new parser/generator~~

13. ~~Create a new submenu under `Laporan` for document numbering history~~:

    - ~~show numbering history for LPLPO distribution documents~~
    - ~~show numbering history for Permintaan Khusus distribution documents~~

14. ~~Build numbering history list UI with per-row details~~:

    - ~~document number~~
    - ~~document type~~
    - ~~year/counter context~~
    - ~~document status~~
    - ~~created date~~

15. ~~Add `Lihat Dokumen` action on numbering history rows~~:

    - ~~opens a modal with a summary of the selected document~~
    - ~~modal includes a button to open the full workflow/detail page in a new tab~~

16. ~~Add supporting backend/view tasks for numbering history~~:

    - ~~query/filter numbering history by document type and year~~
    - ~~provide summary data for modal preview~~
    - ~~map each history row to the correct workflow detail URL~~

17. ~~Update documentation and release notes after implementation~~:

    - ~~`CHANGELOG.md`~~
    - ~~`SYSTEM_MODEL.md`~~
    - ~~`AGENTS.md` if numbering/report navigation conventions change~~

18. ``Printable Kartu Stok``

19. Add new column on Puskesmas's LPLPO for `Pengadaan` data that adding up to the `Persediaan` for those item

## Version 2

1. Mobile clients, whether dedicated mobile apps or PWA
2. Storage system to store images, documents, and so on using MinIO
3. Redis for cache storage, especially for expiry-date data that is refreshed daily on the user's dashboard
