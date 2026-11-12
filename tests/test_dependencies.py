"""M1: template versions are pinned and install failures carry their npm output.

A floating tailwind range resolved to a version whose optional binary was missing on the
platform registry, and the old message ("see the npm output above") hid that cause from the
repair agent for twelve rounds. These tests keep both regressions out.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from infrastructure.shared.project import dependencies
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.stages.database.implementation import ensure_database_dependencies


TEMPLATES = Path(__file__).resolve().parents[1] / "infrastructure/shared/project/templates"
EXACT_VERSION = r"^\d+\.\d+\.\d+$"
PROBES = ("tsx", "typescript", "better-sqlite3", "express")


class FakeProcess:
    def __init__(self, lines, returncode):
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode


class FakeLaunch:
    def __init__(self, process):
        self.process = process

    def __enter__(self):
        return self.process

    def __exit__(self, *exception):
        return False


class PinnedVersions(unittest.TestCase):
    def test_every_template_dependency_is_an_exact_version(self):
        for relative in ("package.json", "backend/package.json", "frontend/package.json"):
            document = json.loads((TEMPLATES / relative).read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies"):
                for name, version in (document.get(section) or {}).items():
                    with self.subTest(package=name):
                        self.assertRegex(version, EXACT_VERSION)

    def test_tailwind_is_pinned_to_the_known_good_version(self):
        frontend = json.loads((TEMPLATES / "frontend/package.json").read_text(encoding="utf-8"))
        self.assertEqual(frontend["devDependencies"]["tailwindcss"], "4.3.4")
        self.assertEqual(frontend["devDependencies"]["@tailwindcss/vite"], "4.3.4")


class InstallDiagnostics(unittest.TestCase):
    def install(self, lines, returncode):
        with TemporaryDirectory() as temporary, redirect_stdout(StringIO()):
            output = Path(temporary)
            (output / "package.json").write_text("{}", encoding="utf-8")
            process = FakeProcess(lines, returncode)
            with patch.object(dependencies, "start_process", return_value=FakeLaunch(process)):
                install_dependencies(output)

    def test_a_failure_reports_the_npm_tail(self):
        with self.assertRaises(RuntimeError) as caught:
            self.install(["npm error code ETARGET\n",
                "npm error notarget No matching version found for @tailwindcss/oxide@4.3.5.\n"], 1)
        message = str(caught.exception)
        self.assertIn("npm install failed with exit code 1", message)
        self.assertIn("ETARGET", message)
        self.assertIn("No matching version found", message)
        self.assertNotIn("see the npm output above", message)

    def test_only_the_last_twenty_lines_are_kept(self):
        lines = [f"line-{index}\n" for index in range(30)]
        with self.assertRaises(RuntimeError) as caught:
            self.install(lines, 1)
        message = str(caught.exception)
        self.assertNotIn("line-0", message)
        self.assertIn("line-29", message)

    def test_success_does_not_raise(self):
        self.install(["added 205 packages in 5s\n"], 0)


class DatabaseInstallGate(unittest.TestCase):
    def workspace(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        (output / "package.json").write_text('{"name": "app"}', encoding="utf-8")
        (output / "backend").mkdir()
        (output / "backend/package.json").write_text('{"name": "backend"}', encoding="utf-8")
        return output

    def test_a_failed_manifest_is_not_reinstalled(self):
        output, state = self.workspace(), {}
        with patch("infrastructure.stages.database.implementation.install_dependencies",
                side_effect=RuntimeError("npm install failed with exit code 1:\nETARGET")) as install:
            with self.assertRaises(RuntimeError):
                ensure_database_dependencies(output, state)
            with self.assertRaises(RuntimeError):
                ensure_database_dependencies(output, state)
        self.assertEqual(install.call_count, 1)

    def test_a_changed_manifest_is_attempted_again(self):
        output, state = self.workspace(), {}
        with patch("infrastructure.stages.database.implementation.install_dependencies",
                side_effect=RuntimeError("npm install failed with exit code 1:\nETARGET")) as install:
            with self.assertRaises(RuntimeError):
                ensure_database_dependencies(output, state)
            (output / "package.json").write_text('{"name": "app", "changed": true}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                ensure_database_dependencies(output, state)
        self.assertEqual(install.call_count, 2)

    def test_a_successful_manifest_is_not_reinstalled(self):
        output, state = self.workspace(), {}
        def install(_output):
            for name in PROBES:
                (output / "node_modules" / name).mkdir(parents=True, exist_ok=True)
        with patch("infrastructure.stages.database.implementation.install_dependencies",
                side_effect=install) as mocked:
            ensure_database_dependencies(output, state)
            ensure_database_dependencies(output, state)
        self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
