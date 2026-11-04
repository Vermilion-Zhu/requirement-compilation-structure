"""Step 12 test infrastructure: real application servers and isolated SQLite data.

Compiler-owned Playwright, Vite, Node-runner, and fixture source strings are written
by prepare_e2e(). One server pair is started per application and reused across the
E2E invocations of a stage, because restarting Vite for every spec dominated stage
12. Ports stay stable so a reused Vite proxy keeps pointing at the backend; a new
backend is started whenever backend sources change, and test cases still reset the
database before each run. Business handlers and scenario assertions are generated
separately.
"""

import json
import os
from pathlib import Path
import shutil
import signal

from infrastructure.utils.files import save_text

CONFIG = "frontend/playwright.e2e.config.ts"
FIXTURE = "frontend/tests/e2e/support/context.ts"
RUNNER = "frontend/scripts/test-e2e.mjs"
VITE_CONFIG = "frontend/vite.e2e.config.ts"
STATE = ".arc/e2e-servers.json"

CONFIG_SOURCE = '''import { defineConfig } from "@playwright/test";
const frontendPort = process.env.ARC_E2E_FRONTEND_PORT;
const backendPort = process.env.ARC_E2E_BACKEND_PORT;
const database = process.env.ARC_E2E_DB_FILE;
if (!frontendPort || !backendPort || !database) throw new Error("Use npm run test:e2e or the step 12 runner");
// The runner starts and keeps one server pair per application; these flags let
// Playwright reuse it instead of spawning Vite and the backend for every spec.
const reuseBackend = process.env.ARC_E2E_REUSE_BACKEND === "1";
const reuseFrontend = process.env.ARC_E2E_REUSE_FRONTEND === "1";
export default defineConfig({
  testDir: "./tests/e2e", outputDir: "./test-results/e2e", workers: 1,
  fullyParallel: false, retries: 0, forbidOnly: true,
  timeout: 30000, expect: { timeout: 5000 }, reporter: "json",
  use: { baseURL: `http://127.0.0.1:${frontendPort}`, browserName: "chromium", headless: true,
    trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    { command: "node --import tsx ../backend/src/server.ts",
      url: `http://127.0.0.1:${backendPort}/api/health`, reuseExistingServer: reuseBackend, timeout: 600000,
      ...(process.platform === "win32" ? {} : { gracefulShutdown: { signal: "SIGTERM" as const, timeout: 3000 } }),
      env: { PORT: backendPort, DATABASE_URL: database } },
    { command: `node ../node_modules/vite/bin/vite.js --config vite.e2e.config.ts --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      url: `http://127.0.0.1:${frontendPort}`, reuseExistingServer: reuseFrontend, timeout: 600000,
      ...(process.platform === "win32" ? {} : { gracefulShutdown: { signal: "SIGTERM" as const, timeout: 3000 } }),
      env: { ARC_BACKEND_URL: `http://127.0.0.1:${backendPort}` } },
  ],
});
'''

RUNNER_SOURCE = '''// One server pair per application, reused by later E2E invocations.
// Ports stay stable so a reused Vite proxy keeps pointing at the backend. Any
// startup failure falls back to Playwright-managed servers on fresh ports.
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:net";

const root = fileURLToPath(new URL("../../", import.meta.url));
const statePath = join(root, ".arc", "e2e-servers.json");

function readState() {
  try { return JSON.parse(readFileSync(statePath, "utf8")); } catch { return null; }
}
function writeState(state) {
  mkdirSync(join(root, ".arc"), { recursive: true });
  writeFileSync(statePath, JSON.stringify(state, null, 2) + "\\n");
}
function backendFingerprint() {
  const hash = createHash("sha256");
  const visit = directory => {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) { visit(path); continue; }
      const stat = statSync(path);
      hash.update(path + ":" + stat.size + ":" + stat.mtimeMs + "\\n");
    }
  };
  visit(join(root, "backend/src"));
  const manifest = join(root, "backend/package.json");
  const stat = statSync(manifest);
  hash.update(manifest + ":" + stat.size + ":" + stat.mtimeMs + "\\n");
  return hash.digest("hex");
}
async function healthy(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(1000) });
    return response.ok;
  } catch { return false; }
}
async function waitFor(url, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await healthy(url)) return true;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return false;
}
async function waitUntilDown(url, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (!(await healthy(url))) return true;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  return false;
}
async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  return port;
}
function startDetached(argv, cwd, env) {
  const child = spawn(process.execPath, argv, { cwd, detached: true, stdio: "ignore", env: { ...process.env, ...env } });
  child.unref();
  return child.pid;
}
function stop(pid) {
  if (!pid) return;
  try { process.kill(pid); } catch { /* already gone */ }
}
const temporary = () => mkdtempSync(join(process.env.ARC_E2E_TEMP_ROOT ?? tmpdir(), "arc-e2e-"));

const backendUrl = port => `http://127.0.0.1:${port}/api/health`;
const frontendUrl = port => `http://127.0.0.1:${port}/`;

async function prepare() {
  const cached = readState();
  const fingerprint = backendFingerprint();
  const backendPort = cached?.backend_port ?? await freePort();
  let frontendPort = cached?.frontend_port ?? await freePort();
  while (frontendPort === backendPort) frontendPort = await freePort();
  const pids = { ...(cached?.pids ?? {}) };

  const reuse_backend = Boolean(cached && cached.hash === fingerprint && cached.database
    && existsSync(cached.database) && cached.backend_port === backendPort
    && await healthy(backendUrl(backendPort)));
  const reuse_frontend = Boolean(cached && cached.frontend_port === frontendPort
    && await healthy(frontendUrl(frontendPort)));

  let directory = cached?.directory;
  let database = cached?.database;
  if (!reuse_backend) {
    stop(pids.backend);
    pids.backend = undefined;
    if (await healthy(backendUrl(backendPort))) await waitUntilDown(backendUrl(backendPort), 5000);
    if (!directory) directory = temporary();
    if (!database || !existsSync(database)) database = join(directory, "app.db");
    pids.backend = startDetached(["--import", "tsx", "backend/src/server.ts"], root,
      { PORT: String(backendPort), DATABASE_URL: database });
    if (!await waitFor(backendUrl(backendPort), 120000)) throw new Error("backend server did not start");
  }
  if (!reuse_frontend) {
    stop(pids.frontend);
    pids.frontend = undefined;
    if (await healthy(frontendUrl(frontendPort))) await waitUntilDown(frontendUrl(frontendPort), 5000);
    pids.frontend = startDetached(["node_modules/vite/bin/vite.js", "--config", "vite.e2e.config.ts",
      "--host", "127.0.0.1", "--port", String(frontendPort), "--strictPort"], join(root, "frontend"),
      { ARC_BACKEND_URL: `http://127.0.0.1:${backendPort}` });
    if (!await waitFor(frontendUrl(frontendPort), 180000)) throw new Error("vite dev server did not start");
  }
  const state = { backend_port: backendPort, frontend_port: frontendPort, database, directory,
    hash: fingerprint, pids, reuse_backend: true, reuse_frontend: true };
  writeState(state);
  return state;
}

async function freshState() {
  const directory = temporary();
  const backend = await freePort();
  let frontend = await freePort();
  while (frontend === backend) frontend = await freePort();
  return { backend_port: backend, frontend_port: frontend, database: join(directory, "app.db"),
    directory, reuse_backend: false, reuse_frontend: false };
}

function playwright(state) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ["node_modules/@playwright/test/cli.js", "test",
      "--config", "frontend/playwright.e2e.config.ts", ...process.argv.slice(2)], {
      cwd: root, stdio: "inherit", env: { ...process.env,
        ARC_E2E_BACKEND_PORT: String(state.backend_port),
        ARC_E2E_FRONTEND_PORT: String(state.frontend_port),
        ARC_E2E_DB_FILE: state.database,
        ARC_E2E_REUSE_BACKEND: state.reuse_backend ? "1" : "0",
        ARC_E2E_REUSE_FRONTEND: state.reuse_frontend ? "1" : "0" },
    });
    const forward = signal => {
      if (process.platform === "win32" && child.pid)
        spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
      else child.kill(signal);
    };
    process.on("SIGINT", forward); process.on("SIGTERM", forward);
    child.once("error", reject);
    child.once("close", code => {
      process.off("SIGINT", forward); process.off("SIGTERM", forward);
      resolve(code ?? 1);
    });
  });
}

let state;
try {
  state = await prepare();
} catch (error) {
  console.error("[e2e] server reuse unavailable, falling back to per-run servers:",
    error && error.message ? error.message : error);
  rmSync(join(root, ".arc", "e2e-servers.json"), { force: true });
  state = await freshState();
}
process.exitCode = await playwright(state);
'''

FIXTURE_SOURCE = '''// Compiler-owned Given/observation fixture. When actions go through the browser.
import { test as base, expect } from "@playwright/test";
import type Database from "better-sqlite3";
import { basename, dirname } from "node:path";
import { createDatabaseClient } from "../../../../backend/src/db/client.js";
import { initializeDatabase } from "../../../../backend/src/db/initialize.js";
export { fixturePasswordHash } from "../../../../backend/tests/support/context.js";
export const test = base.extend<{ database: Database.Database; applicationErrors: void }>({
  database: [async ({}, use) => {
    const path = process.env.ARC_E2E_DB_FILE;
    if (!path || basename(path) !== "app.db" || !basename(dirname(path)).startsWith("arc-e2e-"))
      throw new Error("E2E fixtures require the runner-owned temporary database");
    const connection = createDatabaseClient(path);
    try {
      initializeDatabase(connection);
      connection.pragma("foreign_keys = OFF");
      connection.transaction(() => {
        const tables = connection.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").all() as { name: string }[];
        for (const table of tables) connection.exec(`DELETE FROM "${table.name.replaceAll('"', '""')}"`);
      })();
      connection.pragma("foreign_keys = ON");
      initializeDatabase(connection);
      await use(connection);
    } finally { connection.close(); }
  }, { auto: true }],
  applicationErrors: [async ({ page, database }, use) => {
    void database;
    const errors: string[] = [];
    page.on("pageerror", error => errors.push("E2E_RUNTIME_ERROR: " + error.message));
    page.on("requestfailed", request => {
      if (new URL(request.url()).pathname.startsWith("/api/")) errors.push("E2E_NETWORK_ERROR: " + request.url());
    });
    await use();
    if (errors.length) throw new Error(errors.join("\\n"));
  }, { auto: true }],
});
export { expect };
'''


def prepare_e2e(output, backend):
    """Write E2E configuration, real-server launchers, isolated database fixtures, and the npm test command."""
    sources = {CONFIG: CONFIG_SOURCE, RUNNER: RUNNER_SOURCE,
        VITE_CONFIG: 'import { defineConfig, mergeConfig } from "vite";\nimport base from "./vite.config";\nexport default defineConfig(mergeConfig(base, defineConfig({ server: { proxy: { "/api": process.env.ARC_BACKEND_URL! } } })));\n',
        FIXTURE: FIXTURE_SOURCE}
    for relative, source in sources.items():
        save_text(output / relative, source)
    path = output / "package.json"
    package = json.loads(path.read_text(encoding="utf-8-sig"))
    package.setdefault("scripts", {})["test:e2e"] = "node frontend/scripts/test-e2e.mjs"
    save_text(path, json.dumps(package, indent=2) + "\n")


def stop_e2e_servers(output) -> None:
    """Stop the reused server pair and drop its temporary database.

    Called when the E2E stage ends so a compilation does not leave detached
    processes behind. Missing or unreadable state is ignored.
    """
    path = Path(output) / STATE
    if not path.is_file():
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return
    if isinstance(state, dict):
        for pid in (state.get("pids") or {}).values():
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (OSError, TypeError, ValueError):
                continue
        directory = state.get("directory")
        if isinstance(directory, str) and directory:
            shutil.rmtree(directory, ignore_errors=True)
    path.unlink(missing_ok=True)
