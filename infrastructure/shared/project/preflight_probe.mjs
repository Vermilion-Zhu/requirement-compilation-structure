// Requirement-driven semantic probe. The compiler writes its contract as JSON and this file
// checks the built application in a real browser. It runs from the application root so the
// app's own @playwright/test (and its Chromium) is used.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const appRoot = process.env.APP_ROOT;
if (!appRoot) throw new Error("APP_ROOT is not set");
const requireFromApp = createRequire(appRoot + "/package.json");
const { chromium } = requireFromApp("@playwright/test");

const [base, contractPath] = process.argv.slice(2);
const contract = JSON.parse(readFileSync(contractPath, "utf8"));
const timeout = contract.timeout ?? 15000;
const failures = [];
const warnings = [];
const skipped = [];

const browser = await chromium.launch();
const page = await browser.newPage();

async function visit(route) {
  return page.goto(base + route, { waitUntil: "domcontentloaded", timeout });
}

async function visible(locator, wait = timeout) {
  try {
    await locator.first().waitFor({ state: "visible", timeout: wait });
    return true;
  } catch {
    return false;
  }
}

// 1) Every static designed route must render its page root (redirects are reported as skipped).
for (const spec of contract.pages ?? []) {
  try {
    const response = await visit(spec.route);
    const status = response ? response.status() : 0;
    if (status >= 400) {
      failures.push(`route ${spec.route}: HTTP ${status}`);
      continue;
    }
    const reached = new URL(page.url()).pathname;
    if (reached !== spec.route) {
      skipped.push(`route ${spec.route}: redirected to ${reached} (auth-gated?)`);
      continue;
    }
    if (spec.root && !(await visible(page.locator(`[data-testid="${spec.root}"]`), Math.min(timeout, 10000)))) {
      failures.push(`route ${spec.route}: page root ${spec.root} is not visible`);
    }
  } catch (error) {
    failures.push(`route ${spec.route}: ${String(error.message ?? error).split("\n")[0]}`);
  }
}

// 2) Entry route, named landmarks and navigation-entry roles.
try {
  await visit("/");
  const entry = contract.entry ?? {};
  if (entry.expected) {
    const regions = entry.regions ?? [];
    if (await page.getByRole("region").count() === 0) {
      failures.push("entry /: requirements describe a homepage but it has no region content");
    } else if (regions.length) {
      let found = false;
      for (const name of regions) {
        if (await page.getByRole("region", { name, exact: true }).count() > 0) { found = true; break; }
      }
      if (!found) warnings.push(`entry /: none of the named regions (${regions.join(", ")}) appears; the page has region content`);
    }
  }
  for (const landmark of contract.landmarks ?? []) {
    const locator = landmark.name
      ? page.getByRole(landmark.role, { name: landmark.name, exact: true })
      : page.getByRole(landmark.role);
    if (await locator.count() === 0) {
      failures.push(`landmark: ${landmark.role}${landmark.name ? ` "${landmark.name}"` : ""} is missing on /`);
    }
  }
  for (const follow of contract.follow ?? []) {
    const action = follow.role ?? "button";
    const nav = page.getByRole("navigation", { name: follow.nav, exact: true });
    if (await nav.count() === 0) {
      failures.push(`landmark: navigation "${follow.nav}" is missing on /`);
      const link = page.getByRole("navigation").getByRole("link", { name: follow.item, exact: true });
      if (await link.count() > 0) {
        failures.push(`navigation entry "${follow.item}" is a link, expected ${action}`);
      }
      continue;
    }
    if (await nav.getByRole(action, { name: follow.item, exact: true }).count() === 0) {
      failures.push(`navigation "${follow.nav}": "${follow.item}" is not a ${action}`);
    }
  }
} catch (error) {
  failures.push(`entry /: ${String(error.message ?? error).split("\n")[0]}`);
}

// 3) Requirement-stated controls that only appear on other pages are advisory.
const quoted = contract.quoted ?? [];
const found = new Set();
if (quoted.length) {
  const routes = new Set(["/", ...(contract.pages ?? []).map(spec => spec.route)]);
  for (const route of routes) {
    try { await visit(route); } catch { continue; }
    for (const item of quoted) {
      const key = item.role + ":" + item.name;
      if (found.has(key)) continue;
      if (await page.getByRole(item.role, { name: item.name, exact: true }).count() > 0) found.add(key);
    }
  }
  for (const item of quoted) {
    if (!found.has(item.role + ":" + item.name)) {
      warnings.push(`requirement control "${item.name}" (role=${item.role}) is not visible on any static route`);
    }
  }
}

const unique = values => [...new Set(values)];
console.log(JSON.stringify({ failures: unique(failures), warnings: unique(warnings), skipped: unique(skipped) }));
await browser.close();
