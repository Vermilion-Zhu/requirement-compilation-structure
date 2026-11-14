"""Experimental typed browser-test plans compiled by a fixed Playwright backend."""

from hashlib import sha256
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

from infrastructure.react_agent.requirements import compile_requirements, resolve_source
from infrastructure.react_agent.provenance import fingerprint
from infrastructure.utils.files import save_json, save_text


ACTIONS = {"click", "hover", "fill", "press", "select_option", "check", "uncheck", "expect", "goto", "reload"}
ASSERTIONS = {"visible", "hidden", "count", "text", "contains_text", "not_contains_text", "value", "attribute", "accessible_name"}
VARIABLE = re.compile(r"\$\{([\w.]+)\}")

PLAN_INSTRUCTIONS = """Compile original website requirements into executable browser-test plans.
Return {"cases":[{"requirement_id":"...","source":"requirements.yaml#/...",
"title":"...","variables":{"title":{"value":"example","unique":true}},"steps":[...]}]}.
Cover every implementation_id with real assertions. Each case must independently prepare
its own records through the UI. Use variables for isolated identities and reference them
as ${title} in strings. Literal content variables can omit unique. Keep actions grounded
in original Given/When/Then outcomes. Cover identity, rejection and reload when required.
Start each case with goto using the original entry path.

Steps have op and relevant fields. goto uses url (same-origin path), reload has no target.
Other steps use target. A target is {role,name}, {text}, or {declaration:"UI-id"}.
Targets can have within with another target. Role/name matching is exact. Prefer compiled
UI declarations, which enforce their declared ownership and default accessible names.
Declaration targets omit name. If a declaration already supplies container, omit within
and let the backend apply that ownership. Use within for originally unspecified ownership.
Declaration templates such as {title} use the case variable named title.
If an explicit original clause overrides a declaration's default accessible name,
provide name_resolutions={"UI-id":{"name":"...","source":"requirements.yaml#/...",
"evidence":"exact original naming clause"}}. An explicitly unnamed element uses name="".
Actions are click, hover, fill (value), press (value), select_option (value), check, uncheck.
Assertions use op=expect, check=visible|hidden|count|text|contains_text|not_contains_text|value|attribute|accessible_name.
Text/value/name assertions use value. Count uses a nonnegative integer value.
Attribute assertions additionally use key, such as aria-pressed, with a string value.

Produce structured plans only. JavaScript, mock state and implementation-specific routes
are outside this test language. Use semantic UI actions and original evidence. Named
landmarks use accessible names; their names alone do not require separate visible text.
"""


def resolve_names(raw: dict, contracts: dict, resolutions: dict) -> dict:
    """Ground explicit name overrides before the fixed test backend applies defaults."""
    declarations = {item["id"]: deepcopy(item) for item in contracts["ui_declarations"]}
    owners = {item["id"]: item["source"] for item in contracts["contracts"]}
    if not isinstance(resolutions, dict):
        raise ValueError("Name resolutions must be a mapping")
    for uid, resolution in resolutions.items():
        if uid not in declarations or not isinstance(resolution, dict):
            raise ValueError("A name resolution needs a known UI declaration")
        source, evidence, name = (resolution.get(key) for key in ("source", "evidence", "name"))
        value = resolve_source(raw, source)
        if not isinstance(value, str) or not isinstance(evidence, str) or not evidence or evidence not in value:
            raise ValueError("A name resolution needs exact original evidence")
        owner = max((pointer for pointer in owners.values() if source == pointer or source.startswith(pointer + "/")), key=len)
        declaration_owner = owners[declarations[uid]["requirement_id"]]
        if declaration_owner != owner and not declaration_owner.startswith(owner + "/"):
            raise ValueError("Name evidence must belong to the requirement or its ancestors")
        if not isinstance(name, str):
            raise ValueError("An accessible name must be a string")
        literal = name.replace("${", "{")
        if name and (literal not in evidence or not re.search(r"accessible name|aria-label|aria-labelledby", evidence, re.I)):
            raise ValueError("Name evidence must explicitly identify the accessible name")
        if not name and not re.search(r"unnamed|no accessible name|without an accessible name", evidence, re.I):
            raise ValueError("An empty name needs explicit unnamed-element evidence")
        declarations[uid].update(resolved_accessible_name=literal, name_resolution=deepcopy(resolution))
    return declarations


def validate_plan(raw: dict, contracts: dict, plan: dict) -> list[dict]:
    if not isinstance(plan, dict):
        raise ValueError("A browser-test plan must be an object")
    cases = deepcopy(plan.get("cases"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("A test plan needs cases")
    known = set(contracts["implementation_ids"])
    owners = {item["id"]: item["source"] for item in contracts["contracts"]}
    declarations = resolve_names(raw, contracts, plan.get("name_resolutions", {}))
    seen = set()

    def target(value, variables, used):
        if not isinstance(value, dict):
            raise ValueError("A UI action needs a target")
        selectors = sum(key in value for key in ("role", "text", "declaration"))
        if selectors != 1:
            raise ValueError("A target needs exactly one role, text or declaration selector")
        if "declaration" in value:
            uid = value["declaration"]
            if uid not in declarations:
                raise ValueError("Unknown UI declaration")
            declaration = declarations[uid]
            if "name" in value or ("within" in value and declaration.get("container")):
                raise ValueError("Declared names and ownership come from the compiled contract: " + json.dumps(value))
            used.add(uid)
            names = re.findall(r"\{([\w.]+)\}", declaration["label"] + " " + declaration.get("resolved_accessible_name", ""))
            if any(name not in variables for name in names):
                raise ValueError("A declaration template needs its case variables")
        for field in ("role", "name", "text"):
            if field in value and (not isinstance(value[field], str) or not value[field]):
                raise ValueError("Target fields must be nonempty strings")
        if "role" in value and VARIABLE.search(value["role"]):
            raise ValueError("Roles must be declared statically")
        if "within" in value:
            target(value["within"], variables, used)

    for case in cases:
        if not isinstance(case, dict) or case.get("requirement_id") not in known or not isinstance(case.get("title"), str) or not case["title"]:
            raise ValueError("Each case needs a known requirement and title")
        identity = (case["requirement_id"], case["title"])
        if identity in seen:
            raise ValueError("Case titles must be unique within a requirement")
        seen.add(identity)
        source = case.get("source", "")
        owner = owners[case["requirement_id"]]
        if not isinstance(source, str) or not (source == owner or source.startswith(owner + "/")):
            raise ValueError("A case must cite its original requirement")
        resolve_source(raw, source)
        variables = case.get("variables", {})
        if not isinstance(variables, dict) or any(not isinstance(item, dict) or not isinstance(item.get("value"), str)
                or ("unique" in item and not isinstance(item["unique"], bool)) for item in variables.values()):
            raise ValueError("Case variables need string values and optional boolean uniqueness")
        if any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name) for name in variables):
            raise ValueError("Case variable names must be identifiers")
        steps = case.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("Each case needs steps")
        if not isinstance(steps[0], dict) or steps[0].get("op") != "goto":
            raise ValueError("Each fresh browser case must start with navigation")
        used = set()
        assertions = 0
        for step in steps:
            if not isinstance(step, dict) or step.get("op") not in ACTIONS:
                raise ValueError("Unknown browser-test operation")
            if step["op"] == "goto":
                url = step.get("url")
                if not isinstance(url, str) or not url.startswith("/") or url.startswith("//") or "\\" in url:
                    raise ValueError("Test navigation must use a same-origin path")
            elif step["op"] != "reload":
                target(step.get("target"), variables, used)
            if step["op"] in {"fill", "press", "select_option"} and not isinstance(step.get("value"), str):
                raise ValueError("This action needs a string value")
            if step["op"] == "expect":
                assertions += 1
                check = step.get("check")
                if check not in ASSERTIONS:
                    raise ValueError("Unknown browser assertion")
                value = step.get("value")
                if check == "count" and (type(value) is not int or value < 0):
                    raise ValueError("Count assertions need nonnegative integers")
                if check not in {"visible", "hidden", "count"} and not isinstance(value, str):
                    raise ValueError("This assertion needs a string value")
                if check == "attribute" and (not isinstance(step.get("key"), str) or not step["key"]):
                    raise ValueError("Attribute assertions need a key")
            missing = set(VARIABLE.findall(json.dumps(step, ensure_ascii=False))) - variables.keys()
            if missing:
                raise ValueError("Undefined case variables: " + ", ".join(sorted(missing)))
        if not assertions:
            raise ValueError("Each case needs an executable assertion")
        case["ui_checks"] = sorted(used)
    missing = known - {case["requirement_id"] for case in cases}
    if missing:
        raise ValueError("Missing requirement cases: " + ", ".join(sorted(missing)))
    return cases


def compile_plan(requirements: Path, output: Path, plan: dict) -> dict:
    """Produce code and its evidence manifest from the same validated case objects."""
    raw, contracts = compile_requirements(requirements)
    cases = validate_plan(raw, contracts, plan)
    output = output.resolve()
    if output.exists() or output.is_relative_to(requirements.resolve()) or requirements.resolve().is_relative_to(output):
        raise ValueError("Use a new test-plan output separate from the original input")
    declarations = resolve_names(raw, contracts, plan.get("name_resolutions", {}))
    runtime = Path(__file__).with_name("plan_runtime.ts").read_text(encoding="utf-8")
    source = 'import { test } from "./application-fixture";\nimport { execute, type CasePlan } from "./plan-runtime";\n'
    source += "const cases: CasePlan[] = " + json.dumps(cases, ensure_ascii=False, indent=2) + ";\n"
    source += "const declarations = " + json.dumps(declarations, ensure_ascii=False, indent=2) + ";\n"
    source += '''for (const plan of cases) {
  test(plan.requirement_id + " / " + plan.title, async ({ applicationURL, page }) => {
    await execute(page, plan, declarations, applicationURL);
  });
}
'''
    files = {"acceptance.spec.ts": source, "plan-runtime.ts": runtime,
             "application-fixture.ts": Path(__file__).with_name("application_fixture.ts").read_text(encoding="utf-8")}
    report = {"status": "COMPILED_PLAN", "source_sha256": contracts["source_sha256"],
              "compiler": fingerprint(PLAN_INSTRUCTIONS),
              "requirement_sha256": contracts["requirement_sha256"],
              "cases": [{"requirement_id": case["requirement_id"], "source": case["source"],
                         "file": "acceptance.spec.ts", "title": case["requirement_id"] + " / " + case["title"],
                         "ui_checks": case["ui_checks"]} for case in cases],
              "uncovered_requirements": [], "files": {}}
    used = {uid for case in cases for uid in case["ui_checks"]}
    report["unchecked_ui_declarations"] = [item for item in contracts["ui_declarations"] if item["id"] not in used]
    output.mkdir(parents=True)
    for name, content in files.items():
        save_text(output / name, content)
        report["files"][name] = sha256(content.encode("utf-8")).hexdigest()
    save_json(output / "test-plan.json", plan)
    save_json(output / "acceptance-manifest.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", type=Path)
    parser.add_argument("-o", "--output-dir", required=True, type=Path)
    parser.add_argument("--plan", type=Path, help="Compile a local JSON plan without a model request")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    usage = None
    if args.plan:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    else:
        from infrastructure.react_agent.runner import ConversationModel
        _, contracts = compile_requirements(args.requirements)
        plan, usage = ConversationModel().generate(
            [{"role": "user", "content": json.dumps(contracts, ensure_ascii=False)}],
            args.timeout, instructions=PLAN_INSTRUCTIONS)
    report = compile_plan(args.requirements, args.output_dir, plan)
    if usage:
        report["usage"] = usage
        save_json(args.output_dir / "acceptance-manifest.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
