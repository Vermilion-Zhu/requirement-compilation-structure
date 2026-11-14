import { expect, type Locator, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

type Target = { role?: string; name?: string; text?: string; declaration?: string; within?: Target };
type Step = { op: string; target?: Target; value?: string | number; key?: string; url?: string; check?: string };
type Declaration = { id: string; role: string; label: string; container?: string;
  default_accessible_name?: string; resolved_accessible_name?: string };
export type CasePlan = { requirement_id: string; title: string; source: string;
  variables?: Record<string, { value: string; unique?: boolean }>; steps: Step[]; ui_checks?: string[] };

function interpolate(value: string, variables: Record<string, string>): string {
  return value.replace(/\$\{([\w.]+)\}/g, (_match, key) => {
    if (!(key in variables)) throw new Error(`Undefined case variable ${key}`);
    return variables[key];
  });
}

function declaredName(value: string, variables: Record<string, string>): string {
  return value.replace(/\{([\w.]+)\}/g, (_match, key) => {
    if (!(key in variables)) throw new Error(`Undefined declaration variable ${key}`);
    return variables[key];
  });
}

function locate(scope: Page | Locator, target: Target, variables: Record<string, string>,
  declarations: Record<string, Declaration>): Locator {
  const declaration = target.declaration ? declarations[target.declaration] : undefined;
  let parent = scope;
  if (target.within) parent = locate(scope, target.within, variables, declarations);
  else if (declaration?.container) parent = locate(scope, { declaration: declaration.container }, variables, declarations);
  if (target.text) return parent.getByText(interpolate(target.text, variables), { exact: true });
  const role = declaration?.role ?? target.role;
  if (!role) throw new Error("A target needs a declared role or text");
  const name = target.name !== undefined ? interpolate(target.name, variables) : declaration
    ? declaredName(declaration.resolved_accessible_name ?? declaration.default_accessible_name ?? declaration.label, variables) : undefined;
  return parent.getByRole(role as Parameters<Page["getByRole"]>[0], { name, exact: true });
}

export async function execute(page: Page, plan: CasePlan, declarations: Record<string, Declaration>, applicationURL?: string): Promise<void> {
  const variables = Object.fromEntries(Object.entries(plan.variables ?? {}).map(([key, item]) =>
    [key, item.unique ? `${item.value} [${randomUUID()}]` : item.value]));
  for (const step of plan.steps) {
    if (step.op === "goto") {
      const path = interpolate(step.url!, variables);
      await page.goto(applicationURL ? new URL(path, applicationURL).href : path);
      continue;
    }
    if (step.op === "reload") {
      await page.reload();
      continue;
    }
    const target = step.target!;
    const locator = locate(page, target, variables, declarations);
    const value = typeof step.value === "string" ? interpolate(step.value, variables) : step.value;
    switch (step.op) {
      case "click": await locator.click(); break;
      case "hover": await locator.hover(); break;
      case "fill": await locator.fill(value as string); break;
      case "press": await locator.press(value as string); break;
      case "select_option": await locator.selectOption(value as string); break;
      case "check": await locator.check(); break;
      case "uncheck": await locator.uncheck(); break;
      case "expect": {
        const declaration = target.declaration ? declarations[target.declaration] : undefined;
        const expectedName = declaration?.resolved_accessible_name ?? declaration?.default_accessible_name;
        if (step.check === "visible" && expectedName !== undefined) {
          await expect(locator).toHaveAccessibleName(declaredName(expectedName, variables));
        }
        if (step.check === "visible" && declaration && ["status", "alert"].includes(declaration.role)) {
          await expect(locator).toContainText(declaredName(declaration.label, variables));
        }
        switch (step.check) {
          case "visible": await expect(locator).toBeVisible(); break;
          case "hidden": await expect(locator).toBeHidden(); break;
          case "count": await expect(locator).toHaveCount(value as number); break;
          case "text": await expect(locator).toHaveText(value as string); break;
          case "contains_text": await expect(locator).toContainText(value as string); break;
          case "not_contains_text": await expect(locator).not.toContainText(value as string); break;
          case "value": await expect(locator).toHaveValue(value as string); break;
          case "attribute": await expect(locator).toHaveAttribute(interpolate(step.key!, variables), value as string); break;
          case "accessible_name": await expect(locator).toHaveAccessibleName(value as string); break;
          default: throw new Error(`Unknown assertion ${step.check}`);
        }
        break;
      }
      default: throw new Error(`Unknown operation ${step.op}`);
    }
  }
}
