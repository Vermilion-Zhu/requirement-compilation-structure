"""ARC-Bench injects an application baseline; the compiler must take it over explicitly.

The runner installs the task's own ``backend/`` and ``frontend/`` (package names
``backend`` and ``frontend``) into ``--output-dir`` before the agent starts. Mixing
that tree with this compiler's TypeScript workspace makes ``npm run build`` fail, so
the scaffold must move the conflicting entries aside, keep them as evidence, and
then install its own workspace.
"""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from infrastructure.shared.project.initialize import (
    BACKUP_ROOT,
    HANDLING_REPORT,
    classify_output_dir,
    initialize_project,
    take_over_foreign_baseline,
)


def injected_baseline(root: Path) -> None:
    """Create the application ARC-Bench injects before the agent runs."""
    (root / "backend" / "src").mkdir(parents=True)
    (root / "backend" / "package.json").write_text(json.dumps(
        {"name": "backend", "main": "src/index.js", "scripts": {"start": "node src/index.js"}}))
    (root / "backend" / "src" / "index.js").write_text("console.log('injected baseline')\n")
    (root / "backend" / "src" / "app.js").write_text("export const app = null;\n")
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "frontend" / "package.json").write_text(json.dumps(
        {"name": "frontend", "scripts": {"build": "vite build"}}))
    (root / "frontend" / "vite.config.js").write_text("export default {};\n")
    (root / "frontend" / "src" / "main.tsx").write_text("export {};\n")
    (root / "frontend" / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (root / "template.yaml").write_text("id: web-react-express\n")


class BaselineTakeover(unittest.TestCase):
    def test_injected_baseline_is_moved_aside_and_replaced_by_the_workspace(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            injected_baseline(root)
            self.assertEqual(classify_output_dir(root), "foreign")

            created = initialize_project(root, port=33000)

            self.assertIn("deploy.sh", created)
            self.assertEqual(json.loads((root / "package.json").read_text())["name"], "arc-application")
            self.assertEqual(json.loads((root / "backend" / "package.json").read_text())["name"], "@arc/backend")
            self.assertEqual(json.loads((root / "frontend" / "package.json").read_text())["name"], "@arc/frontend")
            self.assertFalse((root / "backend" / "src" / "index.js").exists())
            self.assertFalse((root / "frontend" / "vite.config.js").exists())

            report = json.loads((root / HANDLING_REPORT).read_text())
            self.assertEqual(report["action"], "taken_over")
            self.assertEqual({item["path"] for item in report["moved"]}, {"backend", "frontend"})
            backup = root / report["backup"]
            self.assertTrue(backup.is_relative_to(root / BACKUP_ROOT))
            self.assertEqual(json.loads((backup / "backend" / "package.json").read_text())["name"], "backend")
            self.assertTrue((backup / "frontend" / "vite.config.js").is_file())
            self.assertTrue((backup / "frontend" / "package-lock.json").is_file())
            # Unrelated runner files are not touched.
            self.assertTrue((root / "template.yaml").is_file())

            # The rendered application honours the runner's HOST and PORT.
            server = (root / "backend" / "src" / "server.ts").read_text()
            self.assertIn('process.env.PORT ?? "33000"', server)
            self.assertIn("process.env.HOST", server)
            self.assertIn('"0.0.0.0"', server)
            deploy = (root / "deploy.sh").read_text()
            self.assertIn('export HOST="${HOST:-0.0.0.0}"', deploy)
            self.assertIn('export PORT="${PORT:-3000}"', deploy)

    def test_rerun_reuses_the_existing_workspace_and_keeps_edits(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_project(root)
            page = root / "frontend" / "src" / "App.tsx"
            page.write_text("// implemented by an earlier pass\n")
            created = initialize_project(root)
            self.assertEqual(created, [])
            self.assertEqual(page.read_text(), "// implemented by an earlier pass\n")
            self.assertEqual(classify_output_dir(root), "scaffold")
            self.assertFalse((root / HANDLING_REPORT).exists())

    def test_empty_output_directory_is_initialized_without_a_report(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(classify_output_dir(root), "empty")
            created = initialize_project(root)
            self.assertIn("package.json", created)
            self.assertFalse((root / HANDLING_REPORT).exists())
            self.assertFalse((root / BACKUP_ROOT).exists())

    def test_keep_baseline_flag_leaves_the_injected_application_untouched(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            injected_baseline(root)
            with patch.dict(os.environ, {"ARC_KEEP_BASELINE": "1"}):
                created = initialize_project(root)
            self.assertEqual(created, [])
            self.assertFalse((root / "deploy.sh").exists())
            self.assertEqual(json.loads((root / "backend" / "package.json").read_text())["name"], "backend")
            report = json.loads((root / HANDLING_REPORT).read_text())
            self.assertEqual(report["action"], "kept_by_request")
            self.assertIn("ARC_KEEP_BASELINE", report["reason"])

    def test_takeover_is_reported_for_inspection(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            injected_baseline(root)
            report = take_over_foreign_baseline(root)
            self.assertEqual(report["action"], "taken_over")
            shapes = {item["path"]: item["kind"] for item in report["moved"]}
            self.assertEqual(shapes, {"backend": "directory", "frontend": "directory"})
            self.assertTrue(all(item["bytes"] > 0 for item in report["moved"]))


if __name__ == "__main__":
    unittest.main()
