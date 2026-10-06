# Clinical EDC — Frontend

React 19 + TypeScript + Vite SPA for the Clinical EDC platform. Server state is
managed with TanStack Query, and the typed API client is generated from the
backend's OpenAPI schema with [Orval](https://orval.dev).

## Getting started

```bash
npm install
npm run dev
```

The dev server runs at `http://localhost:5173` and proxies `/api` to the
backend (default `http://localhost:8000`).

## Scripts

| Script                       | Purpose                                         |
| ---------------------------- | ----------------------------------------------- |
| `npm run dev`                | Start the Vite dev server with HMR              |
| `npm run build`              | Type-check and build the production bundle      |
| `npm run lint`               | Run ESLint                                      |
| `npm run test`               | Run unit/component tests (Vitest)               |
| `npm run e2e`                | Run Playwright end-to-end tests                 |
| `npm run api:refresh-schema` | Refresh `openapi/openapi.json` from the backend |
| `npm run api:gen`            | Regenerate the typed API client from the schema |

## Configuration

Configuration is read from Vite env vars (prefix `VITE_`). Copy `.env.example`
to `.env` (or `.env.local`) and adjust. See `.env.example` for the full list.

| Variable            | Default                 | Purpose                                                                                                                                                                                             |
| ------------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VITE_API_BASE_URL` | `/api/v1`               | Base URL for all API requests. Leave relative to use the dev proxy / same-origin in production, or set an absolute URL (e.g. `https://api.example.com/api/v1`) to target a remote backend directly. |
| `VITE_PROXY_TARGET` | `http://localhost:8000` | Backend the Vite dev server proxies `/api` to. Only used when `VITE_API_BASE_URL` is relative.                                                                                                      |
| `VITE_OPENAPI_URL`  | _(unset)_               | When set, `api:refresh-schema` fetches the spec from this URL instead of exporting it from the local backend app.                                                                                   |

### Pointing the frontend at a different backend

- **Dev, same-origin via proxy:** leave `VITE_API_BASE_URL` unset and set
  `VITE_PROXY_TARGET=http://my-backend:8000`.
- **Direct to a remote backend:** set
  `VITE_API_BASE_URL=https://api.example.com/api/v1`. Requests go straight
  there (ensure CORS is configured on that backend).

## Generated API client (Orval)

The typed client lives under `src/api/` and is generated from
`openapi/openapi.json`:

- `src/api/endpoints/` — TanStack Query hooks, one file per OpenAPI tag
  (GET → `useQuery`, POST/PUT/PATCH/DELETE → `useMutation`). **Generated — do
  not edit.**
- `src/api/model/` — TypeScript types for every schema. **Generated — do not
  edit.**
- `src/api/mutator.ts` — hand-written Axios adapter. Every generated call routes
  through the shared instance in `src/lib/api.ts`, so it inherits the
  configurable base URL, the Bearer-token request interceptor, and the 401
  refresh/retry logic. **Edit this, not the generated files.**
- `openapi/openapi.json` — the committed source schema. Checked in so the client
  is reproducible without a running backend.

`src/api/endpoints/` and `src/api/model/` are git-ignored because they are fully
reproducible from the committed schema. Run `npm run api:gen` after cloning (or
let it run as needed) to materialize them.

### Regenerating after a backend change

```bash
npm run api:refresh-schema   # export the latest spec from the local backend app
npm run api:gen              # regenerate hooks + types from the spec
```

`api:refresh-schema` exports the schema directly from the backend application
(`backend/app/main.py:create_app().openapi()`) using the backend virtualenv — no
running server required, and immune to whatever happens to be listening on a
port. Pass `--url <openapi-url>` (or set `VITE_OPENAPI_URL`) to pull from a
running server instead.

### Using a generated hook

```tsx
import {
  getListStudiesApiV1StudiesGetQueryKey,
  useCreateStudyApiV1StudiesPost,
  useListStudiesApiV1StudiesGet,
} from "@/api/endpoints/studies/studies";
import type { StudyResponse } from "@/api/model";

// Query (GET) — fully typed response
const { data } = useListStudiesApiV1StudiesGet({ page: 1, page_size: 20 });

// Mutation (POST) — body passed as { data }
const create = useCreateStudyApiV1StudiesPost({
  mutation: {
    onSuccess: () => {
      /* invalidate, close dialog, ... */
    },
  },
});
create.mutate({ data: { study_code: "S-1", title: "My study" } });
```

See `src/features/studies/StudyListPage.tsx` for a complete reference migration
from hand-written `api.get/post` calls to the generated hooks.
