# Changelog

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog and follows Semantic Versioning (`MAJOR.MINOR.PATCH`).

## [1.0.3] - 2026-03-23

### Added

- GitHub Actions workflow `.github/workflows/release-on-version-change.yml` to automatically verify versioning, create tag `v<version>`, and publish a GitHub Release when `VERSION` changes on `main`.
- Pull request template checklist item requiring `VERSION` and `CHANGELOG.md` updates for release-impacting changes.

### Changed

- Updated `README.md` with automatic release behavior for `VERSION` bumps.
- Updated `.gitignore` to allow tracking `.github/` workflow files.

## [1.0.2] - 2026-03-18

### Added

- Root `VERSION` file as the single source of truth for application version.
- Semantic version helpers in `backend/apps/core/versioning.py`.
- Django management command `python manage.py app_version` with `--major`, `--minor`, `--patch`, and `--set` options.
- Template context processor to expose app version in templates.
- Header badge in authenticated UI showing the active app version.
- Unit tests for semantic version parsing, bumping, and file read/write behavior.

### Changed

- Settings now load `APP_VERSION` from the root `VERSION` file.
- Project documentation updated to include the versioning workflow and command usage.

### Notes

- `app_version` command name is used to avoid collision with Django's built-in `version` command.
