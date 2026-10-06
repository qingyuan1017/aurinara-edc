// Refreshes openapi/openapi.json — the schema Orval generates the client from.
//
// By default it exports the spec directly from the local backend app (no
// running server needed), which is the authoritative source for this repo:
//   python -c "import json; from app.main import create_app; ..."
//
// Pass --url (or set VITE_OPENAPI_URL) to instead fetch from a running backend:
//   node scripts/refresh-openapi.mjs --url http://localhost:8000/api/v1/openapi.json
//
// The schema is pretty-printed so diffs are reviewable, then `npm run api:gen`
// regenerates the typed client from it.

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = resolve(__dirname, "..");
const BACKEND_DIR = resolve(FRONTEND_DIR, "..", "backend");
const OUT_PATH = resolve(FRONTEND_DIR, "openapi", "openapi.json");

function parseArgs() {
  const args = process.argv.slice(2);
  const urlFlag = args.indexOf("--url");
  if (urlFlag !== -1 && args[urlFlag + 1]) return { url: args[urlFlag + 1] };
  if (process.env.VITE_OPENAPI_URL) return { url: process.env.VITE_OPENAPI_URL };
  return { url: null };
}

function backendPython() {
  // Prefer the backend virtualenv interpreter; fall back to PATH python.
  const candidates =
    process.platform === "win32"
      ? [resolve(BACKEND_DIR, ".venv", "Scripts", "python.exe"), "python"]
      : [resolve(BACKEND_DIR, ".venv", "bin", "python"), "python3", "python"];
  return candidates.find((c) => c === "python" || c === "python3" || existsSync(c)) ?? "python";
}

async function fromLocalApp() {
  const py = backendPython();
  console.log(`Exporting OpenAPI schema from the local backend app (${py}) ...`);
  const code =
    "import json,sys; from app.main import create_app; " +
    "sys.stdout.write(json.dumps(create_app().openapi()))";
  const result = spawnSync(py, ["-c", code], {
    cwd: BACKEND_DIR,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.status !== 0) {
    console.error(
      "Failed to export schema from the local backend app.\n" +
        "Ensure backend dependencies are installed in backend/.venv.\n",
    );
    console.error(result.stderr || result.error);
    process.exit(1);
  }
  return JSON.parse(result.stdout);
}

async function fromUrl(url) {
  console.log(`Fetching OpenAPI schema from ${url} ...`);
  let response;
  try {
    response = await fetch(url);
  } catch (error) {
    console.error(`Failed to reach ${url}. Is the backend running?`);
    console.error(String(error));
    process.exit(1);
  }
  if (!response.ok) {
    console.error(`Request failed: ${response.status} ${response.statusText}`);
    process.exit(1);
  }
  return response.json();
}

async function main() {
  const { url } = parseArgs();
  const schema = url ? await fromUrl(url) : await fromLocalApp();

  const pathCount = Object.keys(schema.paths ?? {}).length;
  const schemaCount = Object.keys(schema.components?.schemas ?? {}).length;

  await mkdir(dirname(OUT_PATH), { recursive: true });
  await writeFile(OUT_PATH, `${JSON.stringify(schema, null, 2)}\n`, "utf8");

  console.log(
    `Wrote ${OUT_PATH}\n` +
      `  ${schema.info?.title} | openapi ${schema.openapi} | ${pathCount} paths | ${schemaCount} schemas\n` +
      "Next: run `npm run api:gen` to regenerate the typed client.",
  );
}

main();
