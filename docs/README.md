# Docs Index

This folder contains implementation notes, developer guidance, ERD references, testing plans, and the code wiki baseline for the Django monolith.

## Start Here

- [Project Overview](../README.md): purpose, capabilities, and documentation entry points
- [Application Reference](application_reference.md): detailed functional descriptions moved from the root README
- [System Model](../SYSTEM_MODEL.md): schema, routes, permissions, and stock mutation contracts
- [Agent Guidance](../AGENTS.md): shared coding rules; read the owning app's guide before changes
- [Code Wiki](code-wiki/README.md): orientation map for developers reading the codebase
- [Developer Guide](developer_guide.md): local setup, testing, versioning, and documentation process
- [ERD](erd.md): schema visualization reference
- [Testing Plan](staged-testing-plan/README.md): test priorities and implementation guidance
- [Infrastructure Plan](infrastructure_plan.md): deployment and infrastructure notes

## Feature Notes

These specifications and implementation notes provide design context. Verify current behavior against code and the System Model.

- [Allocation Feature Spec](FEATURE_ALOKASI.md)
- [Allocation Implementation Notes](ALLOCATION_IMPLEMENTATION.md)
- [LPLPO Implementation Notes](LPLPO_IMPLEMENTATION.md)

## Working Docs

- [Staged Testing Plan](staged-testing-plan/README.md)
- [Tailwind CSS Migration Plan](css-refactoring/TAILWIND_CSS_MIGRATION_PLAN.md): phased migration and verification gates
- [Approved UI Design](../DESIGN.md) and [Concept Review](css-refactoring/CONCEPT_REVIEW.md): target visual direction
- [Tailwind Design System](css-refactoring/DESIGN_SYSTEM.md): implemented foundation tokens and components
- [Tailwind Migration Ledger](css-refactoring/MIGRATION_LEDGER.md): current surface status and remaining work
- [Tailwind Migration Closeout](css-refactoring/MIGRATION_CLOSEOUT.md): verification evidence and outstanding device/PWA acceptance
- `work-report/`: historical work reports

## Data Files

This folder also contains several spreadsheet and CSV artifacts used for implementation support and analysis. Treat them as supporting assets, not as the source of truth for runtime behavior.
