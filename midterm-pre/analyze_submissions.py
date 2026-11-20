"""Parse the saved ArcBench history pages and map submissions to submitted ZIPs.

The saved pages only contain the submission list (name, time, total score); the per-task
details drawer is empty in the HTML and the details API requires the login session.  This
script therefore records what is available and leaves runtime/token/task fields absent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"

# History names are not always the ZIP stem (renames, truncation, leaderboard labels).
ZIP_BY_SUBMISSION = {
    "Lite 07d Scenario Coverage 20261120 dzs.zip": "Lite 07d Scenario Coverage 20261120 dzs.zip",
    "Lite 07b Input Hints and Obligations 20261120 dzs": "Lite 07b Input Hints and Obligations 20261120 dzs.zip",
    "Lite 07a Input Hints 20261120 dzs": "Lite 07a Input Hints 20261120 dzs.zip",
    "Lite 05c Log Labels 20261119 dzs": "Lite 05c Log Labels 20261119 dzs.zip",
    "Lite History Search 20261119 dzs": "Lite History Search 20261119 dzs.zip",
    "Lite Workflow Groups 20261118 dzs": "Lite Workflow Groups 20261118 dzs.zip",
    "Lite 05b Log Preview 20261116 dzs": "Lite 05b Log Preview 20261116 dzs.zip",
    "Lite Log Preview 20261116 dzs": "Lite 05b Log Preview 20261116 dzs.zip",
    "Lite Bounded 20261115 dzs": "Lite Bounded Runtime 20261115 dzs.zip",
    "Light 20261115 dzs": "Light 20261115 dzs.zip",
    "Entry Route and Probes 20261113 zmr": "entry_route.zip",
    "Breadcrumb-fixed 20261111 zmr": "breadcrumb.zip",
    "IR amended 20261109 zmr": "ir_amended.zip",
    "Full-hooked 20261107 dzs": "compiler-hooks.zip",
    "GYP No.1": "gyp.no1.zip",
    "UI Naming 20261107": "compiler-ui-naming-20261107.zip",
    "Semantics Enhanced": "semantics.zip",
    "E2E Re-fixed": "compiler_e2e_refix.zip",
    "D1 Implementation": "compiler_d1.zip",
}

# Entries with no matching ZIP in output/ (kept with a blank version).
UNKNOWN = {
    "Baseline Test",
    "Nowicthelight",
    "Fix E2E Reuse",
    "Full-hooked and E2E Enhanced",
    "First Deployable Agent",
    "zmr20245036@sjtu.edu.cn",
}


def parse_history(filename: str, competition: str) -> list[dict]:
    text = (OUTPUT / filename).read_text(encoding="utf-8", errors="replace")
    rows = []
    for chunk in text.split('<li class="competition-history-item')[1:]:
        chunk = chunk.split("</li>", 1)[0]
        name_match = re.search(r"<h3[^>]*>(.*?)</h3>", chunk, re.S)
        date_match = re.search(r'<time datetime="([^"]*)"', chunk)
        score_match = re.search(r"<strong>([^<]*)</strong>", chunk)
        if not (name_match and date_match and score_match):
            continue
        rows.append({
            "competition": competition,
            "name": re.sub(r"<[^>]+>", "", name_match.group(1)).strip(),
            "date": date_match.group(1),
            "score": float(score_match.group(1)),
        })
    return rows


def release_versions() -> dict[str, str]:
    versions = {}
    for path in OUTPUT.glob("*.zip"):
        try:
            import zipfile
            with zipfile.ZipFile(path) as archive:
                manifest = next((name for name in archive.namelist() if name.endswith("agent-release.json")), None)
                if manifest:
                    data = json.loads(archive.read(manifest))
                    versions[path.name] = str(data.get("version") or "")
        except Exception:
            continue
    return versions


def build_rows() -> list[dict]:
    versions = release_versions()
    rows = []
    for competition, filename in (("web", "ArcBench_web_scores.html"), ("lite", "ArcBench_lite_scores.html")):
        for row in parse_history(filename, competition):
            zip_name = ZIP_BY_SUBMISSION.get(row["name"], "")
            if not zip_name and row["name"] not in UNKNOWN:
                # Try an exact stem match before leaving the version blank.
                for candidate in OUTPUT.glob("*.zip"):
                    if candidate.stem == row["name"].removesuffix(".zip"):
                        zip_name = candidate.name
                        break
            row["zip"] = zip_name
            row["version"] = Path(zip_name).stem if zip_name else ""
            row["release_version"] = versions.get(zip_name, "")
            row["excluded"] = row["score"] == 0.0
            rows.append(row)
    rows.sort(key=lambda item: item["date"])
    return rows


if __name__ == "__main__":
    print(json.dumps(build_rows(), ensure_ascii=False, indent=2))
