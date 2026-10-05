# Instructions for coding agents

## Repository purpose and architecture

This repository is a clinical Electronic Data Capture (EDC) platform with a first-party pharmacovigilance/safety module and CTMS capabilities. It is organized as:

- **Backend:** FastAPI on Python 3.11+, Pydantic v2, SQLAlchemy 2.x, Alembic, and PostgreSQL. Uvicorn serves development; Gunicorn with Uvicorn workers is the documented production shape.
- **Frontend:** React, TypeScript, Vite, shadcn/ui, Tailwind CSS, TanStack Query/Router/Table, React Hook Form, Zod, and Zustand.
- **Database and migrations:** PostgreSQL is the system database; SQLAlchemy models and Alembic revisions define schema changes.

Important directories:

- `backend/app/api/` — FastAPI dependencies, pagination, and route registration.
- `backend/app/api/routes/` — versioned EDC, CTMS, and PV HTTP routes.
- `backend/app/core/` — configuration, database, security, request context, exceptions, and OpenAPI support.
- `backend/app/models/`, `repositories/`, `schemas/`, `services/`, and `workers/` — persistence models, database access, Pydantic contracts, business logic, and background jobs.
- `backend/app/tests/` — backend unit, integration, and property-based tests.
- `backend/alembic/versions/` — committed database migrations; `backend/alembic.ini` is the Alembic configuration.
- `frontend/src/components/` and `frontend/src/lib/` — shared UI and client infrastructure.
- `frontend/src/features/` — feature areas for EDC, CTMS, PV, and other workflows; `frontend/src/features/pv/` is the PV application boundary.
- `frontend/src/__tests__/` and `frontend/e2e/` — frontend/component and Playwright end-to-end tests.
- `docs/` — repository operating documentation, especially `docs/local-development.md`.
- `.kiro/specs/` — feature requirements, designs, and task plans.
- `docker-compose.yml` — local PostgreSQL service.

Existing repository documentation and the applicable `.kiro/specs/*/requirements.md`, `design.md`, and `tasks.md` files are authoritative for feature work. Resolve conflicts against those documents before implementing a feature.

## Local development

Prerequisites are Python 3.11+, Node.js 20+ with npm, and Docker Desktop/Compose or a compatible PostgreSQL installation. The documented local flow is:

```bash
# From the repository root
source .venv/bin/activate                 # or create .venv with: python3 -m venv .venv
docker compose up -d postgres
docker compose ps

# From backend/
pip install -e ".[dev]"
alembic upgrade head
python -m scripts.seed_dev_user
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# In a second terminal, from frontend/
npm install
npm run dev
```

The API is at `http://localhost:8000`, with `/api/v1/docs`, `/api/v1/openapi.json`, `/api/v1/health/live`, and `/api/v1/health/ready`. Vite serves the SPA at `http://localhost:5173` and proxies `/api` to the backend. Run backend commands from `backend/` and frontend commands from `frontend/` so the configured environment and tooling are found.

## Validation commands

Run targeted checks for the changed area first. The repository documents these commands:

```bash
# backend/
pytest
ruff check .
ruff format --check .
python -m compileall app

# frontend/
npm run test
npm run lint
npm run build
npm run e2e                         # when browser coverage is relevant
```

`npm run build` performs the TypeScript build and Vite production bundle. Do not invent alternate scripts; check `backend/pyproject.toml` and `frontend/package.json` when in doubt. Add or update unit tests and, where the behavior is universal or regulated, Hypothesis/property tests or frontend tests appropriate to the change.

## Database migrations and safety

Before changing schema, inspect the database revision state from `backend/`:

```bash
alembic current
alembic heads
alembic history
```

For a schema change, update the SQLAlchemy models, generate or write a focused revision, inspect the generated SQL and constraints, and verify upgrade/downgrade behavior before applying it locally:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic downgrade -1                  # only when intentionally testing rollback
```

Prefer additive, reviewable migrations with explicit data/backfill handling, indexes, constraints, and a safe downgrade where possible. Confirm the current and head revisions before applying a migration. Never run `alembic upgrade` against staging or production without explicit confirmation and an approved deployment/backup plan. Do not use `docker compose down -v` unless local database deletion is intentional.

Never commit `.env`, `backend/.env`, credentials, tokens, generated keys, or other secrets. Use environment-specific secret management and keep sensitive values out of source, migrations, test fixtures, logs, and documentation.

## API, schema, and module conventions

- Use the versioned REST/JSON API under `/api/v1`; PV routes are under `/api/v1/pv`.
- Keep FastAPI route handlers thin: authenticate, validate/request-map, enforce permission, delegate to a service, and return the schema response. Database access belongs in repositories/services rather than route handlers.
- Use Pydantic v2 schemas and the shared contracts in `backend/app/schemas/base.py`. List responses use `{items, page, page_size, total}`; page is at least 1 and the current shared schema limits `page_size` to 100.
- Serialize aware timestamps as UTC ISO-8601 values (`Z`). Preserve the repository's UUID, scope, request/correlation ID, and audit metadata conventions.
- Use the shared error envelope `{error: {code, message, details, request_id, correlation_id}}`. Errors must be sanitized: do not expose stack traces, SQL/database internals, credentials, raw coordination payloads, or sensitive safety data.
- Server-side authentication and authorization are authoritative. Frontend checks improve navigation and affordances but must never be treated as security enforcement.

## PV/Safety boundaries

PV is the safety case system of record. Its primary boundaries are:

- `backend/app/api/routes/pv/` — PV HTTP resources under `/api/v1/pv`.
- `backend/app/models/pv/` — PV safety case, assessment, coding, narrative, regulatory, reconciliation, coordination, and retention models.
- `backend/app/repositories/pv/` — PV database access.
- `backend/app/schemas/pv/` — PV request/response contracts.
- `backend/app/services/` — shared services plus PV service modules such as `safety_case_service.py`, `assessment_service.py`, `regulatory_reporting_service.py`, `reconciliation_service.py`, `pv_ownership_guard.py`, and PV integration services. Reuse shared services; do not fork them.
- `backend/app/workers/` and `backend/app/workers/pv/` — export, projection, reconciliation, retention, and related worker boundaries.
- `frontend/src/features/pv/` — PV pages, API client, capability manifest handling, navigation, forms, and components.

Use the capability manifest and permission model together. The API is authoritative for capability availability and permission/scope enforcement; the frontend may hide unavailable or unauthorized routes/actions only as a convenience. If PV is disabled, empty, or unavailable, preserve normal EDC and CTMS navigation and behavior.

EDC owns clinical configuration, subjects, visits, captured clinical data, clinical queries/review/lock/signatures, and clinical exports. CTMS owns operational study/site, enrollment, monitoring, work, and operational exports. PV may reference canonical Study/Site and EDC Subject/Visit identities and consume approved, minimized EDC adverse-event projections for reconciliation, but those projections are read-only. PV must not create duplicate clinical identities, mutate EDC clinical records, mutate CTMS operational records, or become a second clinical data-capture system of record. Do not add cross-module mutation paths.

## Regulated-data and security guidance

Treat clinical and safety data as regulated data:

- Enforce authorization server-side at route and object level using study/site scope, including list filtering and download access.
- Keep PV mutations and their immutable audit events atomic; retain actor, UTC timestamp, entity, action, request/correlation context, and applicable old/new values or reason for change.
- Preserve submitted/versioned records and use the repository's soft-delete/retention conventions rather than physical deletion of regulated records or audit events.
- Keep error messages and structured logs sanitized. Never log tokens, passwords, connection strings, full sensitive payloads, or unnecessary subject/safety details. Prefer IDs, event types, reason codes, and correlation/request IDs.
- Make ownership explicit in models, services, projections, and exports. Read-only projections must be source-labeled and excluded from unauthorized mutation and PV-owned metric calculations.
- Validate lifecycle transitions, closed/frozen/locked state, reason-for-change requirements, and UTC/date semantics in services, not only in the UI.

## Testing and change scope

Every behavior change should include focused tests for successful paths, authorization failures, validation boundaries, lifecycle/retention behavior, and cross-module ownership. Use existing test patterns and real service contracts rather than mocks that bypass the behavior under test. Run the smallest relevant backend/frontend checks, then broader checks when practical; do not change unrelated tests or generated build output.

Keep changes minimal and module-scoped. Review `git status` and the diff before handoff, preserve existing migrations and docs, and do not rewrite unrelated code. Do not commit or push unless the user explicitly asks. When a commit is requested, stage only the intended files and keep secrets and local artifacts out of it.
