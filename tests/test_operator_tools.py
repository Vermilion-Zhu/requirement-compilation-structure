"""Operator tooling: the log analyzer and the reused E2E server pair."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_log import analyze_text, render  # noqa: E402  (scripts/ is not a package)

from infrastructure.stages.frontend.triggers.e2e_runtime import (  # noqa: E402
    CONFIG, FIXTURE, RUNNER, STATE, VITE_CONFIG, prepare_e2e, stop_e2e_servers)


SAMPLE = """\
┌──────────────────────────────────────────────────────┐
│ [START] Stage 02 | Design database schema            │
└──────────────────────────────────────────────────────┘
[CHECK] node node_modules/typescript/bin/tsc --noEmit | 2.10 s | exit 2
[CHECK] node frontend/scripts/test-e2e.mjs a.spec.ts | 91.50 s | exit 1
[CHECK] node frontend/scripts/test-e2e.mjs b.spec.ts | 8.40 s | exit 0
│ [MODEL CALL] Stage 02 | Design | 1.20s                │
│ [MODEL OUTPUT] Stage 02 | Design database schema      │
│ schema | 12.50s                                       │
│ Input  │ 1,318 │ Cached input │ 1,280 │ Output │ 2,476 │
[GIT] aaa [Stage 02 | x] req: Apply file edits in round 2 (PROPOSED)
[GIT] bbb [Stage 02 | x] req: Apply file edits in round 1 (PROPOSED)
[GIT] ccc [Stage 08 | y] api: Reject edit round 3 (REJECTED)
│ Completed in 17.2s                                   │
┌──────────────────────────────────────────────────────┐
│ [DONE] Stage 02 | Design database schema             │
└──────────────────────────────────────────────────────┘
Installing dependencies in /workspace/template: npm install --include=dev
added 200 packages in 42s
Analyzing image: homepage.png
--- Stage 12 | Task | Read files (full content) ---
['backend/src/db/initialize.ts', 'frontend/src/App.tsx']
This task cannot read this file
Frontend functional smoke GREEN: {'requirements': 2, 'failed': 0}
TDD GREEN: {'tests': 23, 'pass': 23, 'fail': 0}
"""


class LogAnalysis(unittest.TestCase):
    def test_metrics_are_extracted_from_panels_and_check_lines(self):
        report = analyze_text(SAMPLE, top=5)
        stage = report["stages"]["02"]
        self.assertEqual((stage["status"], stage["seconds"]), ("DONE", 17.2))
        self.assertEqual(report["total_seconds"], 17.2)
        self.assertEqual(report["failed_stages"], [])

        checks = report["checks"]
        self.assertEqual(checks["count"], 3)
        self.assertEqual(checks["kinds"]["e2e (playwright+servers)"]["count"], 2)
        self.assertEqual(checks["kinds"]["tsc typecheck"]["exits"], {2: 1})
        self.assertEqual(checks["slowest"][0]["seconds"], 91.5)

        model = report["model"]
        self.assertEqual(model["calls"], 1)
        self.assertAlmostEqual(model["seconds"], 12.5, places=1)
        self.assertEqual((model["input_tokens"], model["cached_tokens"], model["output_tokens"]),
            (1318, 1280, 2476))
        self.assertEqual(model["per_stage"], {"02": 12.5})

        edits = report["edits"]
        self.assertEqual((edits["applied_rounds"], edits["max_round"]), (2, 2))
        self.assertEqual(edits["rejected_rounds"], 1)

        reads = report["reads"]
        self.assertEqual((reads["batches"], reads["denied"]), (1, 1))
        self.assertEqual(reads["requested"][0][0], "backend/src/db/initialize.ts")

        self.assertEqual(report["dependencies"]["install_calls"], 1)
        self.assertEqual(report["dependencies"]["packages"], [(200, 42)])
        self.assertEqual(report["git_checkpoints"], 3)
        self.assertEqual(report["analyzed_images"], 1)
        self.assertEqual(report["final"]["smoke"]["status"], "GREEN")
        self.assertEqual(report["final"]["tdd"]["status"], "GREEN")

    def test_render_is_readable_and_empty_logs_do_not_raise(self):
        text = render(analyze_text(SAMPLE))
        for marker in ("stages: 1 total", "checks:", "model:", "file reads:", "dependency installs:"):
            self.assertIn(marker, text)
        empty = analyze_text("")
        self.assertEqual(empty["stages"], {})
        self.assertEqual(empty["checks"]["count"], 0)
        self.assertIn("stages: 0 total", render(empty))


class ReusedE2EServers(unittest.TestCase):
    def test_prepare_writes_reuse_config_and_fallback_runner(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "package.json").write_text('{"name": "arc-application"}', encoding="utf-8")
            prepare_e2e(output, {})
            for relative in (CONFIG, RUNNER, VITE_CONFIG, FIXTURE):
                self.assertTrue((output / relative).is_file(), relative)
            config = (output / CONFIG).read_text(encoding="utf-8")
            self.assertEqual(config.count("reuseExistingServer: reuse"), 2)
            runner = (output / RUNNER).read_text(encoding="utf-8")
            for marker in ("ARC_E2E_REUSE_BACKEND", "ARC_E2E_REUSE_FRONTEND",
                    "falling back to per-run servers", "backendFingerprint",
                    "child.exitCode !== null", "cached.disabled", "binary not found at",
                    "[e2e] reusing servers", "[e2e] per-run servers"):
                self.assertIn(marker, runner)
            # The detached Vite start must resolve the hoisted binary exactly like the
            # Playwright command does; using "node_modules/..." from frontend/ (the cwd)
            # failed for every spec in the first reused-server run.
            self.assertIn("../node_modules/vite/bin/vite.js", runner)
            self.assertIn("../node_modules/vite/bin/vite.js", config)
            self.assertEqual(config.count("../node_modules/vite/bin/vite.js"), 1)
            self.assertEqual(runner.count("node_modules/vite/bin/vite.js"), 2)
            package = json.loads((output / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(package["scripts"]["test:e2e"], "node frontend/scripts/test-e2e.mjs")

    def test_stop_is_quiet_without_state(self):
        with TemporaryDirectory() as temporary:
            stop_e2e_servers(temporary)
            self.assertFalse((Path(temporary) / STATE).exists())

    def test_stop_removes_invalid_state(self):
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / STATE
            state.parent.mkdir(parents=True)
            state.write_text("{not json", encoding="utf-8")
            stop_e2e_servers(temporary)
            self.assertFalse(state.exists())

    def test_stop_kills_pids_and_removes_the_temporary_database(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "arc-e2e-abc123"
            database.mkdir()
            state = root / STATE
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"directory": str(database), "pids": {"backend": 111, "frontend": 222}}),
                encoding="utf-8")
            with patch("infrastructure.stages.frontend.triggers.e2e_runtime.os.kill") as kill:
                stop_e2e_servers(root)
            self.assertEqual(sorted(call.args[0] for call in kill.call_args_list), [111, 222])
            self.assertFalse(database.exists())
            self.assertFalse(state.exists())

    def test_stop_ignores_unusable_pids(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / STATE
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({"directory": "", "pids": {"backend": "not-a-pid"}}), encoding="utf-8")
            with patch("infrastructure.stages.frontend.triggers.e2e_runtime.os.kill",
                    side_effect=OSError("gone")):
                stop_e2e_servers(root)
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
