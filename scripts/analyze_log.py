"""Summarize one ARC-Bench agent log (``compiler.log``) into reusable metrics.

Usage:
    python scripts/analyze_log.py docs/compiler.log
    python scripts/analyze_log.py docs/compiler.log --json metrics.json
    python scripts/analyze_log.py docs/compiler.log --top 15

The parser is intentionally tolerant: it reads the console panels, the check
summary lines, the model-usage rows and the read-denial feedback. Every section
degrades to an empty result when a log does not contain it, so older or partial
logs stay analyzable.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


STAGE_START = re.compile(r"\[START\] Stage (\d\d) \| ([^│]+?)\s*│")
STAGE_DONE = re.compile(r"\[(DONE|FAILED)\] Stage (\d\d) \| ([^│]+?)\s*│")
DURATION = re.compile(r"Completed in ([0-9.]+)s")
CHECK = re.compile(r"\[CHECK\] (.+?) \| ([0-9.]+) s \| exit (\d+)")
MODEL_MARKER = re.compile(r"\[MODEL OUTPUT\]")
MODEL_CALL = re.compile(r"\[MODEL CALL\]|^--- \[MODEL INPUT\]")
EDIT_ROUND = re.compile(r"Edit round (\d+)/(\d+)")
INPUT_TOKENS = re.compile(r"Input\s+.{0,14}?([\d,]+)")
OUTPUT_TOKENS = re.compile(r"Output\s+.{0,14}?([\d,]+)")
CACHED_TOKENS = re.compile(r"Cached input\s+.{0,14}?([\d,]+)")
READ_BATCH = re.compile(r"\| Read files(?: \(full content\))? ---")
READ_DENIED = "This task cannot read this file"
MODEL_PANEL_SECONDS = re.compile(r"\| ([0-9.]+)s\s*\u2502")
APPLIED_ROUND = re.compile(r"Apply file edits in round (\d+)")
REJECTED_ROUND = re.compile(r"Reject edit round \d+")
INSTALL = re.compile(r"Installing dependencies in")
PACKAGES = re.compile(r"added (\d+) packages in (\d+)s")
FINAL_SMOKE = re.compile(r"Frontend functional smoke (\w+): (\{.*\})")
TDD_RESULT = re.compile(r"TDD (\w+): (\{.*\})")


def _number(value: str) -> int:
    return int(value.replace(",", ""))


def _kind(command: str) -> str:
    if "test-api.mjs" in command:
        return "backend http tests"
    if "test-e2e.mjs" in command:
        return "e2e (playwright+servers)"
    if "playwright/test/cli.js test" in command:
        return "ui existence tests"
    if "install chromium" in command:
        return "chromium install"
    if "run build" in command:
        return "npm build"
    if re.search(r"\btsc\b", command):
        return "tsc typecheck"
    if "db:init" in command or "setup.ts" in command:
        return "db init"
    return "other"


def analyze_text(text: str, top: int = 10) -> dict:
    """Parse one log into stage, check, model, repair and input sections."""
    lines = text.splitlines()
    stages: dict[str, dict] = {}
    checks = []
    model_seconds = 0.0
    model_calls = 0
    rounds = []
    repairs = 0
    current = None
    read_batches = []
    read_denied = 0
    pending_model = 0
    installs = []
    packages = []
    git = 0
    images = 0
    warnings = defaultdict(int)
    final = {}
    stage_seconds = defaultdict(float)
    stage_models = defaultdict(float)
    current_stage = None

    for index, line in enumerate(lines):
        start = STAGE_START.search(line)
        if start:
            current_stage = start.group(1)
            stages.setdefault(current_stage, {"name": start.group(2).strip(), "status": None, "seconds": None})
            continue
        done = STAGE_DONE.search(line)
        if done:
            status, number, name = done.groups()
            stages.setdefault(number, {"name": name.strip(), "status": None, "seconds": None})
            stages[number]["status"] = status
            stages[number]["name"] = name.strip()
            continue
        duration = DURATION.search(line)
        if duration and current_stage:
            stages[current_stage]["seconds"] = float(duration.group(1))
            stage_seconds[current_stage] = float(duration.group(1))
            current_stage = None
            continue
        check = CHECK.search(line)
        if check:
            command, seconds, code = check.group(1), float(check.group(2)), int(check.group(3))
            checks.append({"command": command, "seconds": seconds, "exit": code, "kind": _kind(command)})
            continue
        if MODEL_MARKER.search(line):
            pending_model = 3
        if pending_model:
            elapsed = MODEL_PANEL_SECONDS.search(line)
            if elapsed:
                seconds = float(elapsed.group(1))
                model_seconds += seconds
                if current_stage:
                    stage_models[current_stage] += seconds
                pending_model = 0
            else:
                pending_model -= 1
        if MODEL_CALL.search(line):
            model_calls += 1
            continue
        if READ_DENIED in line and line.strip() == READ_DENIED:
            read_denied += 1
            continue
        applied = APPLIED_ROUND.search(line)
        if applied:
            rounds.append((int(applied.group(1)), 0))
        elif REJECTED_ROUND.search(line):
            repairs += 1
        if READ_BATCH.search(line):
            following = lines[index + 1] if index + 1 < len(lines) else ""
            paths = re.findall(r"'([^']+)'", following) or re.findall(r'"([^"]+)"', following)
            read_batches.append(paths)
            continue
        if INSTALL.search(line):
            installs.append(line.strip()[:160])
            continue
        package_match = PACKAGES.search(line)
        if package_match:
            packages.append((int(package_match.group(1)), int(package_match.group(2))))
            continue
        if line.strip().startswith("[GIT]"):
            git += 1
            continue
        if line.startswith("Analyzing image"):
            images += 1
            continue
        for marker in ("[INPUT WARNING]", "[GIT WARNING]", "[RUNTIME]", "[BASELINE]", "[CHECK] failed"):
            if marker in line:
                warnings[marker] += 1
        smoke = FINAL_SMOKE.search(line)
        if smoke:
            final["smoke"] = {"status": smoke.group(1), "summary": smoke.group(2)}
        tdd = TDD_RESULT.search(line)
        if tdd:
            final["tdd"] = {"status": tdd.group(1), "summary": tdd.group(2)}

    kinds: dict[str, dict] = {}
    for check in checks:
        entry = kinds.setdefault(check["kind"], {"count": 0, "seconds": 0.0, "exits": Counter()})
        entry["count"] += 1
        entry["seconds"] += check["seconds"]
        entry["exits"][check["exit"]] += 1
    for entry in kinds.values():
        entry["seconds"] = round(entry["seconds"], 1)
        entry["exits"] = dict(entry["exits"])

    requested = Counter(path for batch in read_batches for path in batch)
    return {
        "stages": stages,
        "total_seconds": round(sum(stage_seconds.values()), 1),
        "failed_stages": [number for number, stage in stages.items() if stage["status"] == "FAILED"],
        "checks": {
            "count": len(checks),
            "seconds": round(sum(check["seconds"] for check in checks), 1),
            "kinds": kinds,
            "slowest": sorted(checks, key=lambda check: -check["seconds"])[:top],
        },
        "model": {
            "calls": model_calls,
            "seconds": round(model_seconds, 1),
            "per_stage": {stage: round(value, 1) for stage, value in sorted(stage_models.items())},
            "input_tokens": sum(_number(m.group(1)) for line in lines if (m := INPUT_TOKENS.search(line))),
            "output_tokens": sum(_number(m.group(1)) for line in lines if (m := OUTPUT_TOKENS.search(line))),
            "cached_tokens": sum(_number(m.group(1)) for line in lines if (m := CACHED_TOKENS.search(line))),
        },
        "edits": {
            "applied_rounds": len(rounds),
            "max_round": max((number for number, _ in rounds), default=0),
            "applied_after_first_round": sum(1 for number, _ in rounds if number > 1),
            "rejected_rounds": repairs,
        },
        "reads": {
            "batches": len(read_batches),
            "denied": read_denied,
            "requested": requested.most_common(top),
        },
        "dependencies": {
            "install_calls": len(installs),
            "packages": packages,
        },
        "git_checkpoints": git,
        "analyzed_images": images,
        "warnings": dict(warnings),
        "final": final,
    }


def render(report: dict) -> str:
    """Format the parsed report for a terminal."""
    out = []
    stages = report["stages"]
    failed = report["failed_stages"]
    out.append(f"stages: {len(stages)} total, {len(failed)} failed, {report['total_seconds']:.0f}s total")
    for number in sorted(stages):
        stage = stages[number]
        seconds = stage["seconds"]
        out.append(f"  {number} {stage['name'][:52]:54} {stage['status'] or '?':8} "
            + (f"{seconds:7.1f}s" if seconds is not None else "       "))
    checks = report["checks"]
    out.append("")
    out.append(f"checks: {checks['count']} calls, {checks['seconds']:.0f}s")
    for kind, entry in sorted(checks["kinds"].items(), key=lambda item: -item[1]["seconds"]):
        out.append(f"  {kind:28} n={entry['count']:3} {entry['seconds']:8.1f}s exits={entry['exits']}")
    if checks["slowest"]:
        out.append("  slowest:")
        for check in checks["slowest"]:
            out.append(f"    {check['seconds']:7.1f}s exit={check['exit']} {check['command'][:110]}")
    model = report["model"]
    out.append("")
    out.append(f"model: {model['calls']} calls, {model['seconds']:.0f}s, "
        f"input={model['input_tokens']}, cached={model['cached_tokens']}, output={model['output_tokens']}")
    if model["per_stage"]:
        out.append("  per stage: " + ", ".join(f"{stage}:{seconds:.0f}s" for stage, seconds in model["per_stage"].items()))
    edits = report["edits"]
    out.append("")
    out.append(f"edit rounds: {edits['applied_rounds']} applied (max round {edits['max_round']}, "
        f"after first: {edits['applied_after_first_round']}), rejected: {edits['rejected_rounds']}")
    reads = report["reads"]
    out.append("")
    out.append(f"file reads: {reads['batches']} batches, {reads['denied']} denied")
    for path, count in reads["requested"]:
        out.append(f"  {count:4}  {path}")
    dependencies = report["dependencies"]
    out.append("")
    out.append(f"dependency installs: {dependencies['install_calls']} calls, packages: {dependencies['packages']}")
    out.append(f"git checkpoints: {report['git_checkpoints']}, analyzed images: {report['analyzed_images']}")
    if report["warnings"]:
        out.append("warnings: " + json.dumps(report["warnings"], ensure_ascii=False))
    if report["final"]:
        out.append("final: " + json.dumps(report["final"], ensure_ascii=False))
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=Path, help="Path to compiler.log (or any captured agent log)")
    parser.add_argument("--json", type=Path, help="Also write the parsed metrics as JSON")
    parser.add_argument("--top", type=int, default=10, help="Entries shown per ranking (default: 10)")
    args = parser.parse_args()
    if not args.log.is_file():
        parser.exit(1, f"Log not found: {args.log}\n")
    if args.top < 1:
        parser.exit(1, "--top must be positive\n")
    text = args.log.read_text(encoding="utf-8", errors="replace")
    report = analyze_text(text, top=args.top)
    print(render(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nmetrics written: {args.json}")


if __name__ == "__main__":
    main()
