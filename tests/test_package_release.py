"""Release identity must describe the bytes that will actually be submitted."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts.package import package_directory


class PackageReleaseTests(unittest.TestCase):
    def test_engine_and_hashes_match_packaged_files_and_ignored_credentials_stay_out(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "main.py").write_text("print('agent')\n", encoding="utf-8")
            (root / ".env").write_text("PRIVATE_KEY=local-only\n", encoding="utf-8")
            (root / "agent-release.json").write_text("stale metadata", encoding="utf-8")
            output = root / "release.zip"
            def git(arguments, **kwargs):
                return SimpleNamespace(stdout="abc123\n" if arguments[1] == "rev-parse" else " M main.py\n")
            with patch("scripts.package.ignored_names", return_value={".env"}), patch(
                    "scripts.package.subprocess.run", side_effect=git):
                package_directory(root, output, engine="react")
            with ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {"main.py", "agent-release.json"})
                manifest = json.loads(archive.read("agent-release.json"))
                self.assertEqual(manifest["engine"], "react")
                self.assertEqual(manifest["source_commit"], "abc123")
                self.assertEqual(manifest["dirty_paths"], [" M main.py"])
                self.assertEqual(manifest["files"], {"main.py": sha256(archive.read("main.py")).hexdigest()})


if __name__ == "__main__":
    unittest.main()
