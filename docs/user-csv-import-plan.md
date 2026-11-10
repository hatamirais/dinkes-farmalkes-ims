# User CSV creation plan

Date: 2026-11-09. Status: implemented on `feat/user-csv-import`.

The design below records the agreed scope. Actual runtime/import contracts are now
documented in SYSTEM_MODEL.md, users/AGENTS.md and backend/seed/README.md.
Implementation uses `UserImportBatch` staging (15-minute expiry) and
`UserCreationLock` for import/ordinary UI creation. CLI/Admin creation and edits
remain outside that serialization protocol; there is no new global identity
uniqueness constraint. The cleanup command is `cleanup_user_imports`.

## Objective and confirmed baseline

Create multiple new users from a CSV in the existing Django users module. Existing accounts must never be edited, reactivated, or have credentials reset by import.

Verified against repository code:

- `backend/requirements.txt` pins Django 6.0.8.
- Before this feature, `apps/users/urls.py` had create/export routes but no import route. The current CSV export is a presentation report, with translated roles/facility names and last-login metadata; it is not an import template.
- `views._can_add_users()` accepts superuser, Django `users.add_user`, or the existing module-scope fallback. User creation uses `user_mutation_ratelimit` and centralized permission denial.
- `UserCreateForm` rejects ADMIN, checks username/email case-insensitively, and limits selectable facilities to active Puskesmas. PUSKESMAS requires a facility; ADMIN_UMUM/GUDANG may optionally have one.
- `signals.sync_user_group()` assigns role groups and module defaults on per-user saves. Auditlog tracks User and ModuleAccess; password is excluded and email/NIP are masked in settings.
- Before this feature, `UserCreateForm.clean()` called `validate_password(password1)` without a user. Validation now runs in `_post_clean()` with the populated user argument.

Read guidance: root AGENTS.md, SYSTEM_MODEL.md, users/AGENTS.md, core/AGENTS.md. Targeted inspection provided enough context; Graphify was unnecessary. Read DESIGN.md before implementing UI; read items/AGENTS.md if implementation changes facility behavior rather than using existing Facility lookups.

## Implemented workflow

1. Add an `Import User CSV` action next to user creation, shown only to callers authorized to add users. Keep single-user creation available.
2. Offer a blank machine-readable CSV template and an active-Puskesmas code reference. Both downloads require add-user authorization.
3. Upload and validate the entire file. Show Indonesian row/field errors or an escaped preview with role, facility and effective default scopes. Preview makes no account, group, or audit mutations.
4. An explicit CSRF-protected confirmation POST creates all rows atomically. Recheck authorization, duplicate identities and current facility eligibility at confirmation. Any failure creates zero accounts.
5. Redirect after success with the created count. Cancel discards the preview. Repeated submissions must never create another batch.

Implemented routes: `/users/import/` and `/users/import/template/`, with names `user_import_csv` and `user_import_csv_template`. Upload/preview and confirm share the first route using explicit actions. Routes use reverse()/template URL tags and trailing slashes.

## CSV contract

Header: `username,full_name,nip,email,role,facility_code,is_active,password`.

- `username`, `role` and `password` required. Preserve NIP as text, including leading zeroes. Other profile fields follow model/form requiredness and lengths.
- Roles use enum codes: KEPALA, ADMIN_UMUM, GUDANG, AUDITOR, PUSKESMAS. ADMIN is forbidden, including for a superuser importing through the UI.
- `facility_code` resolves an existing active Puskesmas by its unique code. Required for PUSKESMAS, optional for ADMIN_UMUM/GUDANG; reject a populated code for other roles rather than silently discarding it. Never create a facility during import.
- `is_active` accepts only explicit `true` or `false`; require a value to avoid accidental activation.
- Use role-default module scopes only in v1. Reject scope, group, direct-permission, staff and superuser columns; the preview makes resulting access visible. Custom access remains a separate authorized edit.
- Accept UTF-8 with optional BOM, comma or semicolon delimiter, and quoted fields. Reject duplicate/unknown/missing headers, malformed rows, empty files, null bytes anywhere and oversized cells. Normalize profile text with stripping and NFC before validation; preserve the decoded password exactly, without stripping or Unicode normalization.
- Reject duplicate usernames and nonblank emails case-insensitively, both within the file and against existing users. Blank email may repeat. NIP has no observed uniqueness contract; do not invent one.
- Bounds: 1 MiB and 25 data rows, defined in `users.csv_import`. The initial 100-row proposal was reduced after a local benchmark took 68.21 seconds to validate/hash 100 test rows with the configured hasher; a 25-row check took 18.15 seconds. Neither benchmark wrote accounts or staging records. Larger inputs must be split into files. These timings are local measurements, not production latency guarantees.

### Initial password decision

Confirmed by the user on 2026-11-09: each CSV row supplies an initial password, with no mandatory first-login password change.

- Require one `password` column, validate against the configured validators with the fully populated unsaved user, and hash using `set_password()` before staging the preview. Never generate a shared default or echo passwords or hashes in previews/errors/downloads.
- On confirmation, save the validated Django hash from protected server-side staging; do not hash the encoded hash again. The account uses that initial password until changed through the existing password-change/reset flows.
- The administrator supplies and communicates each initial password outside the application. CSV import does not deliver credentials or require a separate administrator reset.

Do not add email invitations, automatic delivery or forced first-login changes without a separately agreed workflow.

## Implementation and integrity

- Add a focused parser/service module under users and an upload form; keep HTTP handling thin. Reuse `core.upload_validation.validate_csv_upload()` plus full-file parsing checks, since that helper samples only the beginning.
- Share identity, role/facility and user-aware password validation with single-user creation where practical, preserving its documented behavior. Test any shared-form change separately.
- Use per-user `save()` inside `transaction.atomic()` so group/default-scope provisioning and audit entries participate in rollback. Do not use bulk_create or ignore_conflicts. Catch IntegrityError outside the failed atomic block.
- On confirmation, lock/reload the actor and relevant authorization rows, then lock/revalidate referenced facilities in a stable order. Revalidate account identities immediately before insertion.
- The current case-insensitive identity checks are application checks; email has no model uniqueness constraint. Locking existing matching rows does not protect absent identities. Serialize importer and ordinary UI creation through the same database lock protocol, and document whether CLI/Admin writes participate. Do not claim global case-insensitive uniqueness without database enforcement. Any new constraint requires the mandated existing-data audit and separate data-fix/constraint migrations.
- Bind the preview to actor, exact payload and expiry; reject tampering, expiry, actor changes and replay. Do not put credentials into signed HTML fields (signing does not encrypt). Use a short-lived server-side staging record containing only hashed passwords, and a single-use confirmation marker consumed in the same database transaction as account creation. Migration 0014 adds staging and creation-lock tables; `cleanup_user_imports` removes expired staging. Do not rely solely on LocMemCache for cross-worker replay protection.
- Do not persist raw uploads or plaintext passwords. Keep hashes only in protected staging and the final user password field; exclude staging credentials from audit history. Scrub staging data after completion/cancellation/expiry and document cleanup. Never include passwords or hashes in logs, session cookies or audit details. Render all preview/error values with normal template escaping.

## Validation and delivery

Focused tests to implement without test doubles:

- Authorization via Django permission and module scope; unauthorized GET/upload/template/confirm returns centralized 403; CSRF and mutation throttling.
- Both delimiters/BOM, quoted values and leading-zero NIP; header/encoding/MIME/extension/path/size/row-limit failures; full-file null bytes, normalization and lengths.
- Every allowed role; ADMIN/privilege-column rejection; missing/inactive/wrong-type facilities; role-default scopes and role-group assignment.
- In-file/existing case-insensitive duplicates, repeated blank emails, no updates to existing accounts.
- Initial-password workflow: required password, user-aware validation, usable final hash and successful login for an active account with the original supplied password; verify the staged hash is not hashed again. No plaintext in staging, and no password/hash disclosure in HTML/log/audit. Verify normal application access without a forced password-change redirect, and voluntary password change through the existing flow.
- Preview creates only a private staging record, with zero account/group/audit mutations; valid confirmation creates exactly the expected rows and attributable audit entries; invalid final row rolls back the whole batch. Expiry, tampering, cancel, double submit and stale facility/actor permissions.
- PostgreSQL TransactionTestCase coverage for competing imports and import versus UI create, validating the chosen identity serialization protocol and single-use confirmation.

Run the new focused import tests, affected users tests, `apps.core.tests.test_auditlog_integration`, and `apps.core.tests.test_url_consistency` through `scripts/run-django-test.ps1`. Rebuild/check generated CSS if classes/styles change.

Manual acceptance on a disposable development database: download template as an authorized operator; import two allowed users with individual initial passwords; inspect preview and confirm no accounts yet and no exposed credentials; confirm once; verify roles/facilities/default scopes and audit actor; repeat confirmation and verify no new accounts; submit a file with one invalid row and verify zero creations; log in as an active imported user with the supplied initial password, confirm normal access without a forced password change, then voluntarily change the password and verify the old one fails. Repeat denied access with an unauthorized account and inspect desktop/narrow-screen rendering.

When implemented, update SYSTEM_MODEL.md first, then affected README.md, root/users AGENTS.md, docs/developer_guide.md and backend/seed/README.md with actual routes, columns, limits, credential handoff, atomic failure behavior, staging schema/cleanup and permission requirements. Keep proposed behavior out of current-contract docs until it exists.

## Primary references

Context7 `/django/django` was consulted; its returned material includes main-branch documentation, so the APIs were cross-checked against the project's Django 6.0 documentation:

- [Password validation and user context](https://docs.djangoproject.com/en/6.0/topics/auth/passwords/#password-validation): validation is not automatic in create_user; some validators need the user argument.
- [Transactions](https://docs.djangoproject.com/en/6.0/topics/db/transactions/): atomic rollback and catching database errors outside atomic blocks.
- [bulk_create caveats](https://docs.djangoproject.com/en/6.0/ref/models/querysets/#bulk-create): model save and pre/post-save signals do not run.

Baseline verification on 2026-11-09: `./scripts/run-django-test.ps1 -Target apps.users.tests.HybridUserAuthorizationTest -KeepDb` passed all 7 tests before implementation.

Implementation verification on 2026-11-09: the existing users suite (82 tests),
audit integration (5 tests), URL consistency (5 tests) and CSS migration guards
(5 tests) passed. Focused import
tests (16 cases) cover real PostgreSQL concurrency, single-use confirmation, rollback,
permissions/throttling, passwords, normalization and file validation. Migration
0014 applied locally; migration drift and generated CSS checks passed.

Browser smoke check used regular Playwright because the Browser plugin was not
available. A separate local development server at `http://127.0.0.1:8011/` served
the current branch. Verified `/users/` → Import CSV → upload header-only CSV →
visible validation error, at 1440×960 and 390×844; no console errors and no mobile
page overflow after the sidebar transition. No accounts were created by this
browser check. Full confirmation/login/password-change acceptance is covered by
Django tests; screenshots were saved outside the repository.

Pre-PR review found and reproduced an unrelated required-file error on failed
confirmation. Confirmation errors now render separately from upload validation;
the regression assertion is included in the existing invalid-preview test.
Release closeout on 2026-11-10: VERSION advances from 2.0.0 to 2.1.0 and the
current Unreleased changelog entries move into the dated 2.1.0 section. PR #319
includes this version bump; the existing release workflow runs when VERSION
changes on main.
