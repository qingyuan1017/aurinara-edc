# Local development

This guide runs the Clinical EDC backend, PostgreSQL, and React frontend on a local machine.

## Prerequisites

Install or have available:

- Python 3.11 or newer
- Node.js 20 or newer and npm
- Docker Desktop with Docker Compose, or a compatible local PostgreSQL installation

The commands below assume the repository is at `/Users/jason/Aurinara/edc` and use Docker Compose PostgreSQL.

## Start PostgreSQL and the backend

Run these commands from the repository root:

```bash
cd /Users/jason/Aurinara/edc
docker compose up -d postgres
docker compose ps
```

The Compose service creates PostgreSQL database `edc` on `localhost:5432` with the local development credentials configured by the repository.

Activate the existing root virtual environment when it is present:

```bash
source .venv/bin/activate
```

If the root environment does not exist, create it once and activate it:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Enter the backend directory and apply the database setup:

```bash
cd backend

# Optional: install the package and development tools (pytest, Hypothesis, ruff, etc.)
pip install -e ".[dev]"

alembic upgrade head
python -m scripts.seed_dev_user
```

Start FastAPI and leave this terminal running:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend reads `backend/.env` when commands are run from `backend`. The seed command is idempotent and creates or repairs the local development administrator.

### Backend URLs

- Swagger UI: <http://localhost:8000/api/v1/docs>
- OpenAPI JSON: <http://localhost:8000/api/v1/openapi.json>
- Liveness: <http://localhost:8000/api/v1/health/live>
- Readiness: <http://localhost:8000/api/v1/health/ready>
- Metrics: <http://localhost:8000/api/v1/metrics>

The liveness response is `{"status":"alive"}`. Readiness checks PostgreSQL and returns `{"status":"ready"}` when the database is reachable.

### Development-only seed credentials

Use these credentials only for local development; do not reuse them in shared, staging, or production environments:

- Email: `admin@edc-dev.example.com`
- Password: `Admin123!`
- Role: System Administrator

## Start the frontend

Open a second terminal and run:

```bash
cd /Users/jason/Aurinara/edc/frontend

# Run this once, or whenever package dependencies change
npm install

npm run dev
```

Vite serves the frontend at <http://localhost:5173> by default. The frontend Axios client uses `/api/v1`; Vite proxies requests under `/api` to `http://localhost:8000`, so the browser can use the frontend origin while FastAPI handles the API requests. Keep the backend running on port 8000 for this proxy to work.

## Build, test, and lint

Backend commands run from `/Users/jason/Aurinara/edc/backend` with the virtual environment active:

```bash
pytest
ruff check .
ruff format --check .
```

The backend has no separate production bundle step; installing it with `pip install -e ".[dev]"` and running the checks above validates the Python package. For a syntax-only check, run `python -m compileall app`.

Frontend commands run from `/Users/jason/Aurinara/edc/frontend`:

```bash
npm run test
npm run lint
npm run build
```

`npm run build` type-checks and creates the production bundle in `frontend/dist/`. To preview that bundle locally, run `npm run preview`.

## Stop and restart

Stop the API and frontend with `Ctrl+C` in their respective terminals. From the repository root, stop PostgreSQL without removing its data:

```bash
cd /Users/jason/Aurinara/edc
docker compose stop postgres
```

Start it again later:

```bash
docker compose start postgres
```

Restart the PostgreSQL container in place:

```bash
docker compose restart postgres
```

To stop and remove the Compose container and network while keeping the named database volume:

```bash
docker compose down
```

Do not use `docker compose down -v` unless you intend to delete the local PostgreSQL data volume and recreate the database from scratch.

## Troubleshooting

### Docker or PostgreSQL does not start

Check the service and its health status:

```bash
cd /Users/jason/Aurinara/edc
docker compose ps
docker compose logs postgres
```

If port 5432 is already in use, stop the other PostgreSQL service or change the Compose port mapping and the backend `DATABASE_URL` together. After changing the database port, rerun `alembic upgrade head` from `backend`.

### Migrations fail

Make sure PostgreSQL is running and healthy, the root virtual environment is active, and the command is run from `backend` so its `.env` file is loaded:

```bash
cd /Users/jason/Aurinara/edc
source .venv/bin/activate
cd backend
alembic current
alembic upgrade head
```

A connection error usually means PostgreSQL is not ready or `DATABASE_URL` does not match the running container. The database must be reachable before running the seed script.

### A port is already occupied

The default ports are PostgreSQL `5432`, FastAPI `8000`, and Vite `5173`. Identify a process using a port with:

```bash
lsof -nP -iTCP:5432 -sTCP:LISTEN
lsof -nP -iTCP:8000 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

Keep FastAPI on port 8000 unless you also update the Vite proxy target. If Vite moves to another available port, use the URL printed by `npm run dev`.

### API readiness is not ready

Check the endpoint directly:

```bash
curl -i http://localhost:8000/api/v1/health/ready
```

A `503` response means the API process is running but cannot reach PostgreSQL. Inspect `docker compose ps`, verify the database container is healthy, confirm `backend/.env` points to `postgresql+asyncpg://edetek:edetekpassword@localhost:5432/edc`, and rerun the migration after the database becomes ready. A successful response contains `{"status":"ready"}`.
## Optional AWS Cognito browser authentication

Cognito is disabled unless all required values are configured. The backend uses these non-secret variables: `COGNITO_USER_POOL_ID`, `COGNITO_REGION`, `COGNITO_APP_CLIENT_ID`, `COGNITO_DOMAIN`, and `COGNITO_REDIRECT_URI`; `COGNITO_SCOPES` defaults to `openid email`, and `COGNITO_JWKS_CACHE_TTL_SECONDS` defaults to 3600. The frontend uses matching `VITE_COGNITO_DOMAIN`, `VITE_COGNITO_CLIENT_ID`, `VITE_COGNITO_REDIRECT_URI`, and optional `VITE_COGNITO_SCOPES` values.

Use a Cognito **public app client with no client secret** for the SPA. Register the exact callback URL (for local development, typically `http://localhost:5173/auth/callback`) in the user pool app client. The SPA stores only short-lived OAuth state/PKCE verifier material in session storage and sends the authorization code to the backend exchange endpoint; it never handles a client secret. Do not put tokens or secrets in URLs.

Cognito authenticates the person, but the application database remains authoritative for `users`, active/inactive status, roles, permissions, and study/site scopes. The API maps the verified immutable Cognito `sub` to a nullable `users.external_identity_provider`/`users.external_subject` pair. A legacy local user can be linked once from a verified Cognito ID token when the email is present and verified and no external mapping exists; access tokens without an email cannot perform that link. Cognito groups and claims are never used to grant application permissions.
