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
python -m scripts.seed_builtin_roles
python -m scripts.seed_dev_user
```

`seed_builtin_roles` is idempotent. In standalone mode it seeds the local fallback roles.
When Platform authorization is enabled, it registers only the EDC-owned permission
catalog; role composition and assignment are configured in Platform. It also synchronizes
existing Sites for Platform-managed Studies. In enforced mode, missing synchronization
credentials fail startup setup instead of leaving Platform incomplete.

Start FastAPI and leave this terminal running:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Start the EDC clinical export worker in another terminal. It processes queued
exports and stores generated files under `backend/exports/`:

```bash
cd backend
python -m app.workers.export_queue_worker --watch
```

To process only one bounded batch and exit, omit `--watch`. The default batch
size is 10; it can be changed with `--batch-size`. When using Docker Compose,
start the equivalent service from the repository root:

```bash
docker compose up -d edc-export-worker
docker compose logs -f edc-export-worker
```

When the shared control plane is enabled, keep the canonical projection worker running
as well:

```bash
docker compose up -d platform-projection-worker
```

The worker applies canonical user, study, and membership events. Membership role UUIDs are
the EDC role UUIDs registered with Platform, so no role mapping is required. The Studies page
refreshes its list every 30 seconds while active. Running FastAPI alone does not consume
the platform SQS subscription.

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

Stop the API, frontend, and any host-run export worker with `Ctrl+C` in their respective terminals. From the repository root, stop PostgreSQL and the Compose export worker without removing database data:

```bash
cd /Users/jason/Aurinara/edc
docker compose stop edc-export-worker postgres
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

Cognito authenticates the person. The API maps each verified identity by its immutable `(issuer, subject)` pair in `users.external_issuer` and `users.external_subject`; provider labels and email addresses are not identity keys. During local or shadow rollout, a legacy local user can be linked once from a verified Cognito ID token when the email is present and verified and no external mapping exists. In enforced platform mode, email linking and just-in-time local users are disabled because the control-plane projection is authoritative. Access tokens without a verified email cannot perform legacy linking, and Cognito groups and claims never grant application permissions. Set `LOCAL_AUTH_ENABLED=false` only after Cognito enrollment and rollback-window reconciliation are complete to disable the local password lifecycle endpoints.

## Optional custom Python runtime

Custom Python is disabled by default. The API never evaluates submitted source itself and has no local fallback. Configure these values only after deploying a separate sandbox runtime:

```dotenv
CUSTOM_FUNCTION_RUNTIME_ENABLED=true
CUSTOM_FUNCTION_RUNTIME_URL=https://custom-function-runtime.internal
CUSTOM_FUNCTION_RUNTIME_TOKEN=<runtime-service-token>
CUSTOM_FUNCTION_RUNTIME_TIMEOUT_SECONDS=3
CUSTOM_FUNCTION_EXECUTION_TIMEOUT_MS=1000
CUSTOM_FUNCTION_MEMORY_LIMIT_MB=64
CUSTOM_FUNCTION_MAX_INPUT_BYTES=65536
CUSTOM_FUNCTION_MAX_OUTPUT_BYTES=65536
```

The runtime must expose `POST /v1/executions`, authenticate the API service, verify the supplied SHA-256 source hash, and run each request in a fresh rootless sandbox with network disabled, no host mounts, no database or platform credentials, a read-only base filesystem, a writable ephemeral working directory, and enforced CPU/time, memory, process, and output limits. Its response status must be `succeeded` or `failed`; commands are limited to `set_value`, `clear_value`, `open_query`, `show`, `hide`, and `require`. Returning a command does not grant mutation authority—the platform must validate and authorize it separately.

Grant `designer.custom_function.author`, `designer.custom_function.approve`, and `designer.custom_function.execute` through the Platform role configuration. Approval is maker-checker: the approver cannot be the version's author or submitter. Do not place the runtime token in source control or frontend environment variables.
