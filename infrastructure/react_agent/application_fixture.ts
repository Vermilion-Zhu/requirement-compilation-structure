import { test as base } from "@playwright/test";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

async function stop(server: ChildProcess): Promise<void> {
  if (!server.pid || server.exitCode !== null || server.signalCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(server.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
  } else {
    try { process.kill(-server.pid, "SIGTERM"); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "ESRCH") throw error; }
  }
  await Promise.race([new Promise<void>(done => server.once("exit", () => done())), delay(1500)]);
  if (server.exitCode === null && server.signalCode === null) {
    server.kill("SIGKILL");
    await new Promise<void>(done => server.once("exit", () => done()));
  }
}

export const test = base.extend<{ applicationURL: string }>({
  applicationURL: async ({ baseURL }, use, testInfo) => {
    const root = process.env.ARC_TEST_APPLICATION_ROOT;
    if (!root) {
      if (!baseURL) throw new Error("A baseURL or application root is required");
      await use(baseURL);
      return;
    }
    const temporaryRoot = resolve(tmpdir());
    const directory = mkdtempSync(join(temporaryRoot, "arc-plan-"));
    const server = spawn(process.execPath, [join(resolve(root), "backend/dist/server.js")], {
      cwd: root,
      env: { ...process.env, PORT: "0", HOST: "127.0.0.1", DATABASE_URL: join(directory, "app.db"),
        OPENAI_API_KEY: "", VISUAL_API_KEY: "", DEEPSEEK_API_KEY: "" },
      detached: process.platform !== "win32", windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    });
    let output = "";
    let launchError: Error | undefined;
    const record = (chunk: Buffer) => { output = (output + chunk.toString("utf8")).slice(-24000); };
    server.stdout?.on("data", record);
    server.stderr?.on("data", record);
    server.on("error", error => { launchError = error; });
    try {
      const deadline = Date.now() + 10000;
      let address: string | undefined;
      while (Date.now() < deadline && server.exitCode === null && !launchError) {
        const match = output.match(/Application listening at http:\/\/127\.0\.0\.1:(\d+)/);
        if (match) { address = `http://127.0.0.1:${match[1]}`; break; }
        await delay(25);
      }
      if (!address) throw new Error(`Application did not start: ${launchError?.message ?? output}`);
      await use(address);
    } finally {
      await stop(server);
      const log = testInfo.outputPath("application.log");
      mkdirSync(dirname(log), { recursive: true });
      writeFileSync(log, output, "utf8");
      if (dirname(resolve(directory)) !== temporaryRoot || !basename(directory).startsWith("arc-plan-")) {
        throw new Error("Unexpected private test directory");
      }
      rmSync(directory, { recursive: true, force: true });
    }
  },
});
