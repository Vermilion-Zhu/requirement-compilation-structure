"""Compile original requirement contracts into an independent browser acceptance suite."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic

from infrastructure.react_agent.requirements import compile_requirements, resolve_source
from infrastructure.react_agent.provenance import fingerprint
from infrastructure.react_agent.runner import ConversationModel
from infrastructure.utils.files import save_json


TEST_INSTRUCTIONS = """Compile the supplied website requirement contracts into Playwright tests.
You receive original evidence and website defaults. Derive expected behavior from those
contracts. All implementation_ids need coverage. Each scenario needs its relevant Given,
When, Then observations. Preserve original names, roles, states, identity and persistence.
Report ambiguity in warnings. Apply defaults only to unspecified properties.
ui_declarations contains source-linked role annotations. Where a declaration supplies
default_accessible_name, assert that exact computed accessible name in addition to
role and visible text, unless an explicit original clause overrides it. A hasText filter
does not verify accessible name. List declaration IDs exercised by each case in ui_checks.
Declarations with container must be tested within that parent element, including actions
contained by feedback. Preserve these relationships as well as individual element names.

Return {"files":{"REQ-id.spec.ts":"source", "helpers.ts":"source"},
"cases":[{"requirement_id":"...","source":"requirements.yaml#/...",
"file":"REQ-id.spec.ts","title":"exact test title","ui_checks":["UI-1"]}],"warnings":[]}.
Use ordinary @playwright/test test and expect. Tests receive a running app via baseURL.
Drive real UI actions with role/name locators and web-first assertions. Assert accessible
names, role, visible text and ARIA state separately when specified. Scope record actions
to the record's named region. Test distinct identities, duplicate prevention, negative
outcomes and reload persistence where required. Use unique record values per case.
Prepare test-owned records through UI helpers. Cases must run independently of test order.
Do not assume database tables, API routes, CSS structure or application source paths.
Do not mock the application, inject its business state, skip tests or weaken assertions.
Use browser fixtures and helper functions to avoid repeated setup code. Keep the suite
small enough to run during implementation. Generate all files in this single response.
"""


def generate_tests(requirements: Path, output: Path, *, model=None, timeout=180, validation_feedback=None) -> dict:
    """Create a new suite and an evidence manifest with one model request."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    raw, contracts = compile_requirements(requirements)
    output = output.resolve()
    input_root = requirements.resolve()
    if output.is_relative_to(input_root) or input_root.is_relative_to(output):
        raise ValueError("Acceptance output must be separate from requirement materials")
    if output.exists():
        raise ValueError("Use a new acceptance directory to retain the frozen suite")
    started = monotonic()
    model = model or ConversationModel()
    payload = {"requirement_contracts": contracts}
    if validation_feedback:
        payload["test_quality_feedback"] = validation_feedback
    result, usage = model.generate([{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                                   timeout, instructions=TEST_INSTRUCTIONS)
    files = result.get("files")
    cases = result.get("cases")
    if not isinstance(files, dict) or not files or not isinstance(cases, list) or not cases:
        raise ValueError("The acceptance compiler must return files and case evidence")
    # Validate the whole proposal before creating files.
    paths = set()
    for name, source in files.items():
        path = output / name
        if not path.resolve().is_relative_to(output) or Path(name).is_absolute() or not name.endswith(".ts"):
            raise ValueError(f"Invalid acceptance source path: {name}")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"Empty acceptance source: {name}")
        identity = str(path.resolve()).casefold()
        if identity in paths:
            raise ValueError("Acceptance source paths must be distinct across platforms")
        paths.add(identity)
    known = set(contracts["implementation_ids"])
    known_ui = {item["id"] for item in contracts["ui_declarations"]}
    sources = {record["id"]: record["source"] for record in contracts["contracts"]}
    for case in cases:
        if (not isinstance(case, dict) or case.get("requirement_id") not in known
                or case.get("file") not in files or not case.get("title")):
            raise ValueError("Every case needs a known requirement, source file and test title")
        evidence = case.get("source", "")
        origin = sources[case["requirement_id"]]
        if not isinstance(evidence, str) or not (evidence == origin or evidence.startswith(origin + "/")):
            raise ValueError("Case evidence must point to its original requirement")
        resolve_source(raw, evidence)
        checks = case.get("ui_checks", [])
        if not isinstance(checks, list) or any(not isinstance(uid, str) or uid not in known_ui for uid in checks):
            raise ValueError("UI checks must reference compiled declaration IDs")
    covered = {case["requirement_id"] for case in cases}
    checked_ui = {uid for case in cases for uid in case.get("ui_checks", [])}
    report = {"status": "GENERATED", "source_sha256": contracts["source_sha256"],
              "compiler": fingerprint(TEST_INSTRUCTIONS),
              "requirement_sha256": contracts["requirement_sha256"],
              "cases": cases, "uncovered_requirements": sorted(known-covered),
              "unchecked_ui_declarations": [item for item in contracts["ui_declarations"] if item["id"] not in checked_ui],
              "warnings": result.get("warnings", []), "usage": usage,
              "elapsed_seconds": monotonic()-started, "files": {}}
    output.mkdir(parents=True)
    for name, source in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8", newline="\n")
        report["files"][name] = sha256(source.encode("utf-8")).hexdigest()
    save_json(output / "acceptance-manifest.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", type=Path)
    parser.add_argument("-o", "--output-dir", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--playwright-cli", type=Path)
    args = parser.parse_args()
    report = generate_tests(args.requirements, args.output_dir, timeout=args.timeout)
    if args.playwright_cli:
        from infrastructure.react_agent.verification import BrowserSuite
        validation = BrowserSuite(args.output_dir, args.playwright_cli).collect(
            args.output_dir.parent / (args.output_dir.name + "-validation"))
        report["collection"] = validation
        report["status"] = "COLLECTED" if validation["passed"] else "INVALID_SUITE"
        save_json(args.output_dir / "acceptance-manifest.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["status"] == "INVALID_SUITE" else 0)


if __name__ == "__main__":
    main()
