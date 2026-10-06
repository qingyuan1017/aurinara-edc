import { defineConfig } from "orval";

/**
 * Orval configuration — generates a typed TanStack Query client from the
 * backend's committed OpenAPI schema (`openapi/openapi.json`).
 *
 * Workflow:
 *   npm run api:refresh-schema   # pull a fresh spec from the running backend
 *   npm run api:gen              # regenerate the typed client from the spec
 *
 * Generated output lives under `src/api/` and is reproducible from the schema,
 * so it is regenerated rather than hand-edited.
 */
export default defineConfig({
  edc: {
    input: {
      target: "./openapi/openapi.json",
    },
    output: {
      // One file per OpenAPI tag keeps the generated surface navigable.
      mode: "tags-split",
      target: "./src/api/endpoints",
      schemas: "./src/api/model",
      client: "react-query",
      httpClient: "axios",
      // Clean the generated dirs on each run so removed endpoints disappear.
      clean: true,
      prettier: true,
      override: {
        // Route every generated request through the shared Axios instance so
        // auth, 401 refresh, and the configurable base URL all apply.
        mutator: {
          path: "./src/api/mutator.ts",
          name: "customInstance",
        },
        query: {
          // Orval's defaults map GET -> useQuery and POST/PUT/PATCH/DELETE ->
          // useMutation. Leaving useQuery/useMutation unset avoids generating
          // redundant mutation variants for GET endpoints.
          signal: true,
        },
      },
    },
  },
});
