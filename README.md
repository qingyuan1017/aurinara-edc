# Clinical EDC System - AWS Kiro Implementation Package

This package contains implementation-ready requirements for building a clinical Electronic Data Capture system using:

- Backend: FastAPI, Python, PostgreSQL, SQLAlchemy, Alembic
- Frontend: React, TypeScript, Vite, shadcn/ui, Tailwind CSS
- Optional infrastructure: AWS ECS/Lambda, RDS PostgreSQL, S3, Cognito, CloudWatch

The system is intended for clinical trial data collection, review, query management, SDV, audit trail, data locking, and export.

## Recommended Kiro workflow

1. Open this folder in AWS Kiro.
2. Start with `kiro/implementation_prompt.md`.
3. Ask Kiro to generate the application incrementally using `kiro/task_breakdown.md`.
4. Use `docs/user_requirements.md` as the source of truth for scope.
5. Use `docs/api_requirements.md` and `docs/data_model.md` for backend design.
6. Use `frontend/frontend_requirements.md` for UI implementation.
7. Use `validation/validation_requirements.md` for regulated-system readiness.

## MVP recommendation

Build the system in three phases:

- Phase 1: Auth, study/site/user management, subject creation, visit schedule, form builder, form data entry, audit trail, manual queries, CSV export.
- Phase 2: Edit checks, repeating forms, SDV, clinical review, freeze/lock, export center.
- Phase 3: Electronic signatures, study build versioning, SAS XPT/ODM export, SDTM mapping metadata, validation package.


---

## Project Structure

```
edc/
  backend/      FastAPI + SQLAlchemy + Alembic API (Python 3.11+)
  frontend/     React + TypeScript + Vite SPA
```

## Prerequisites

- Python 3.11+
- Node.js 20+ and npm
- Docker Desktop (recommended for local PostgreSQL), or PostgreSQL 14+ running locally
- Optional: Redis (background jobs), AWS account (Cognito, S3, RDS, ECS/Fargate)

---

## Backend

### Local setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install the app plus dev tooling (pytest, ruff, hypothesis)
pip install -e ".[dev]"

# Create your environment file and edit values
cp .env.example .env
```

Set `DATABASE_URL` in `.env` to point at your PostgreSQL instance, for example:

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/edc
```

### PostgreSQL with Docker

From the repository root, start the local PostgreSQL container:

```bash
docker compose up -d postgres
docker compose ps
```

The Compose configuration creates database `edc` and user `edetek`, matching the
default `backend/.env` configuration. Stop the container with:

```bash
docker compose stop postgres
```

The database is persisted in the `edc-postgres-data` Docker volume. To remove the
container and its data completely, run `docker compose down -v`.

Generate a strong `SECRET_KEY` for anything beyond local development:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Database migrations

```bash
cd backend
alembic upgrade head          # apply all migrations
alembic downgrade -1          # roll back the latest migration
alembic revision --autogenerate -m "describe change"   # create a new migration
```

### Run the API (development)

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- API base path: `http://localhost:8000/api/v1`
- Interactive docs (Swagger UI): `http://localhost:8000/api/v1/docs`
- OpenAPI schema: `http://localhost:8000/api/v1/openapi.json`
- Health checks: `GET /api/v1/health/live`, `GET /api/v1/health/ready`
- Metrics: `GET /api/v1/metrics`

### Tests and linting

```bash
cd backend
pytest                 # run the full test suite (unit + property-based)
ruff check .           # lint
ruff format .          # format
```

### Run the API (production)

Use Gunicorn with Uvicorn workers behind a reverse proxy (or an ALB on AWS):

```bash
cd backend
gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 0.0.0.0:8000
```

Production checklist:

- Set `ENVIRONMENT=production`, `DEBUG=false`, and a unique `SECRET_KEY`.
- Point `DATABASE_URL` at managed PostgreSQL (e.g. AWS RDS).
- Run `alembic upgrade head` as part of the release/deploy step.
- Set `LOG_JSON=true` for structured logs (CloudWatch-friendly).
- Configure optional `COGNITO_*`, `S3_*`, and `REDIS_URL` values as needed.

---

## Frontend

### Local setup

```bash
cd frontend
npm install
```

The dev server proxies `/api` to the backend at `http://localhost:8000` (see `vite.config.ts`), so run the backend alongside it.

### Run the SPA (development)

```bash
cd frontend
npm run dev
```

The app is served at `http://localhost:5173` by default.

### Build and preview (production bundle)

```bash
cd frontend
npm run build          # type-check + bundle to dist/
npm run preview        # serve the production build locally
npm run lint           # lint the codebase
```

The build outputs static assets to `frontend/dist/`.

### Configure the API endpoint

In development, requests to `/api` are proxied to the backend by Vite. For production, serve the contents of `frontend/dist/` from any static host (S3 + CloudFront, Nginx, etc.) and route `/api` to the backend. If you deploy the frontend and backend on different origins, update the proxy/rewrite rule (or the API base URL in `src/lib/api.ts`) and enable CORS on the backend accordingly.

---

## Deployment overview

A typical AWS deployment:

- Backend container (`uvicorn`/`gunicorn`) on ECS/Fargate behind an Application Load Balancer.
- PostgreSQL on RDS; run `alembic upgrade head` on deploy.
- Frontend static bundle (`frontend/dist/`) on S3 served via CloudFront; `/api/*` routed to the backend ALB.
- Secrets and environment via task definitions / Secrets Manager (never commit `.env`).
- Logs and metrics shipped to CloudWatch (`LOG_JSON=true`).
- Optional: S3 for file/export storage, Cognito for authentication, Redis for background jobs.
