"""Parse the manually pasted ArcBench submission details into structured rows."""

from __future__ import annotations

import json
import re
from pathlib import Path

import analyze_submissions

DATE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{2}:\d{2}$")
TASKS = [
    "12306 railway travel",
    "BookStack knowledge base",
    "Ctrip travel services",
    "Keep personal note management",
    "PrestaShop B2C storefront",
    "Stack Overflow developer knowledge sharing",
]
FIELDS = ("Score", "Tests", "Features", "Runtime", "Tokens", "Cost")


def percent(value: str) -> float | None:
    value = value.strip().rstrip("%")
    try:
        return float(value)
    except ValueError:
        return None


def runtime_seconds(value: str) -> int | None:
    value = value.strip()
    if not value or value == "--":
        return None
    hours = re.search(r"(\d+)\s*h", value)
    minutes = re.search(r"(\d+)\s*m", value)
    seconds = re.search(r"(\d+)\s*s", value)
    if not (hours or minutes or seconds):
        return None
    return (int(hours.group(1)) * 3600 if hours else 0) + (int(minutes.group(1)) * 60 if minutes else 0) + (
        int(seconds.group(1)) if seconds else 0)


def token_count(value: str) -> int | None:
    value = value.strip().replace(",", "")
    if not value or value == "--":
        return None
    match = re.fullmatch(r"([\d.]+)\s*([KMB]?)", value, re.I)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).upper()
    factor = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[unit]
    return int(round(number * factor))


def field_value(lines: list[str], label: str, start: int, end: int) -> str | None:
    for index in range(start, end):
        if lines[index] == label and index + 1 < end:
            return lines[index + 1]
    return None


def parse_block(name: str, date: str, lines: list[str]) -> dict:
    end = len(lines)
    results_at = next((i for i, line in enumerate(lines) if line == "Task results"), end)
    score = field_value(lines, "Score", 0, results_at)
    rate = field_value(lines, "Test pass rate", 0, results_at)
    counts = None
    if rate is not None:
        index = lines.index(rate)
        if index + 1 < results_at:
            counts = lines[index + 1]
    passed = total = None
    if counts and "/" in counts:
        left, right = counts.split("/", 1)
        passed, total = token_count(left), token_count(right)
    tasks = []
    for task in TASKS:
        try:
            task_at = lines.index(task, results_at)
        except ValueError:
            continue
        segment_end = min([lines.index(other, task_at + 1) for other in TASKS if other in lines[task_at + 1:]] or [end])
        segment = lines[task_at + 1:segment_end]
        run = "Open run" in segment
        values = {}
        for index, line in enumerate(segment):
            if line in FIELDS and index + 1 < len(segment):
                values.setdefault(line, segment[index + 1])
        tasks.append({
            "task": task,
            "run": run,
            "score": float(values.get("Score") or 0),
            "tests_pct": percent(values.get("Tests") or "0%"),
            "features_pct": percent(values.get("Features") or "0%"),
            "runtime_s": runtime_seconds(values.get("Runtime") or "--"),
            "tokens": token_count(values.get("Tokens") or "--"),
            "cost_cny": float((values.get("Cost") or "0").replace("CNY", "").strip() or 0),
        })
    return {
        "name": name,
        "date": date,
        "score": float(score or 0),
        "test_rate_pct": percent(rate or "0%"),
        "tests_passed": passed,
        "tests_total": total,
        "model_cost_cny": float((field_value(lines, "Model cost", 0, results_at) or "0").replace("CNY", "").strip() or 0),
        "runtime_s": runtime_seconds(field_value(lines, "Total runtime", 0, results_at) or "--"),
        "tokens": token_count(field_value(lines, "Tokens", 0, results_at) or "--"),
        "archive": field_value(lines, "Archive", 0, results_at) or "",
        "tasks": tasks,
    }


def parse_file(filename: str, competition: str) -> list[dict]:
    text = (Path("output") / filename).read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines()]
    headers = []
    for index, line in enumerate(lines):
        if DATE.fullmatch(line) and index > 0:
            headers.append((index - 1, index))
    rows = []
    for position, (name_at, date_at) in enumerate(headers):
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        block = lines[name_at + 1:end]
        if not block or not DATE.fullmatch(block[0]):
            block = [lines[date_at]] + lines[date_at + 1:end]
        row = parse_block(lines[name_at], lines[date_at], block)
        row["competition"] = competition
        rows.append(row)
    return rows


def build_details() -> list[dict]:
    history = {(row["competition"], row["name"], row["date"][:19].replace("T", " ")): row
        for row in analyze_submissions.build_rows()}
    details = parse_file("web_score_details.txt", "web") + parse_file("lite_score_detail.txt", "lite")
    seen = set()
    unique = []
    for row in details:
        key = (row["competition"], row["name"], row["date"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    for row in unique:
        match = None
        for key, item in history.items():
            if key[0] == row["competition"] and key[1] == row["name"]:
                match = item
                break
        row["version"] = match["version"] if match else ""
        row["release_version"] = match["release_version"] if match else ""
        row["zip"] = match["zip"] if match else ""
        row["archive"] = row["archive"]
        row["excluded"] = row["score"] == 0.0
    return unique


if __name__ == "__main__":
    details = build_details()
    print(json.dumps(details, ensure_ascii=False, indent=2))
