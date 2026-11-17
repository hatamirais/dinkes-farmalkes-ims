# Puskesmas opening import performance

## Tracking

Milestone: [Puskesmas opening import performance](https://github.com/hatamirais/dinkes-farmalkes-ims/milestone/1). No due date.

[Tracking issue #323](https://github.com/hatamirais/dinkes-farmalkes-ims/issues/323)
records the work and is assigned to that milestone (verified 2026-11-17).

Planned actionable work:

- [x] Measure parsing/validation, preview persistence and detail rendering separately locally.
- [x] Batch source, item and funding lookups during CSV parsing and validate locally.
- [ ] Evaluate and reduce repeated database checks during preview preparation.
- [ ] Show processing feedback and prevent repeated form submission while pending.
- [ ] Compare performance and verify facility isolation, exact source snapshots,
  validation, atomic posting and concurrency behavior on staging/demo after rollout.

Evaluate batch inserts, pagination and background processing after the first
measurements and lookup improvements. These options need separate scope decisions.

## Verified baseline

Read-only profiling on 16 November 2026 used the local operator CSV at
`.dev/note/new-seeding/SALDO-AWAL-LPLPO-PUSKESMAS.csv`, facility FAC2, year 2026.
The file is an ignored local input and is not a distributable benchmark fixture.

| Parsing run | Selected rows | Database queries | Seconds |
| --- | ---: | ---: | ---: |
| 1 | 334 | 1,333 | 3.012 |
| 2 | 334 | 1,333 | 3.234 |
| 3 | 334 | 1,333 | 2.992 |

These timings include query instrumentation through Django's CaptureQueriesContext.
They cover `parse_csv()` only. Preview persistence, HTTP upload time and browser
rendering were not measured in this baseline. Staging/demo performance requires
measurement in those environments.

## Batch lookup implementation

Collect only references used by selected CSV rows and load the corresponding
active items, funding records and eligible source records together. Keep reference
maps local to a single parse call. Restore protected source text against those
source snapshots, then validate each row with its original CSV row number.

Keep the live locked source validation at preparation and posting checkpoints.
The existing guarded per-row save path continues to apply to draft persistence.
The current work focuses on parser database reads.

`csv_reference_maps()` collects references from structurally valid, nonblank-quantity
rows in the bounded CSV input. Eligible sources are loaded with their related
metadata using `in_bulk()`. Active item/funding dictionaries include both CSV codes
and the original linked codes, so spreadsheet-safe text can round-trip correctly.
The row pass checks exact source identities against these request-local objects.
The existing live source queries under locks still run when preparing and posting.

Baseline implementation commit: `05d1e94abd3c203177dced5b693b1a3c408d7371`.

## Verified results

The same local operator CSV produced identical parsed row data before and after
batching, including reference keys, catalog IDs, quantities, prices, batch/expiry,
funding, source numbers, notes and source links. Each of the six runs produced
the same canonical data fingerprint.

| Version | Selected rows | Queries per parse | Three local parse timings |
| --- | ---: | ---: | --- |
| Before | 334 | 1,333 | 2.842 s, 3.217 s, 3.358 s |
| Batched reads | 334 | 3 | 0.069 s, 0.072 s, 0.076 s |

A separate controlled test-database benchmark used 334 warehouse-source rows with
the existing real-ORM InventoryTests fixture. Each before/after preview was rolled
back in the test database. It measured parsing, `prepare_opening()` and a normal
detail GET separately. This workload has no manual rows, hence its before-parser
count differs from the operator file.

| Measured phase | Before | After |
| --- | --- | --- |
| Parse and validate | 2.708 s / 1,336 queries | 0.050 s / 3 queries |
| Prepare preview | 5.188 s / 5,359 queries | 5.203 s / 5,359 queries |
| Detail GET/render | 0.159 s / 37 queries | 0.108 s / 37 queries |
| Combined phases | 8.055 s | 5.362 s |

This single controlled pipeline comparison measures roughly one-third less time.
Preview preparation is now the dominant measured cost. Its guarded saves and
per-row validations are the next tracked optimization. HTTP transfer, browser
rendering and staging/demo infrastructure were outside this benchmark.

All 35 inventory tests passed on PostgreSQL. Mixed warehouse/distribution/manual
parser tests stay at four queries for 3 and 33 selected rows. Other checks cover
row-numbered errors, oversized/malformed files, request-local source snapshots,
source changes before preparation/posting, exact decimal values, authority and
concurrent workflow checkpoints. Django system and migration-drift checks passed.

## Validation plan

- Run `scripts/run-django-test.ps1 -Target apps.puskesmas.test_inventory -KeepDb`.
- Compare parser query counts for one and many selected source rows.
- Exercise warehouse, distribution and manual rows, both legacy formats,
  formula-safe text, exact prices and blank-quantity rows.
- Check malformed headers/rows, duplicate keys, missing or inactive catalog
  records, unknown source IDs, facility/date mismatch and stale source snapshots.
- Re-run the local CSV profile with CaptureQueriesContext and compare row data.
- Verify a normal upload still creates a preview, and posting revalidates live
  records under locks.

For profiling, clear query logs before each measured phase and capture its query
count before clearing again. The initial pipeline attempt exceeded Django's query
log limit, so its affected counts were discarded and the measurement rerun with
per-phase resets. The table above uses the corrected run.

Framework references:

- [Django database optimization](https://docs.djangoproject.com/en/6.0/topics/db/optimization/)
- [Django QuerySet in_bulk](https://docs.djangoproject.com/en/6.0/ref/models/querysets/#in-bulk)

Use before/after query counts and measured phase timings when reporting gains.
