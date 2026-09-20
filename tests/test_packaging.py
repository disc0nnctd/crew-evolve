import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from crew_evolve.resources import asset_dir


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_checkout_assets_are_available(self):
        self.assertTrue((asset_dir("web") / "index.html").is_file())
        self.assertTrue((asset_dir("examples") / "crew.csv").is_file())

    def test_unknown_asset_collection_is_rejected(self):
        with self.assertRaises(ValueError):
            asset_dir("private")

    def test_wheel_contains_copied_runtime_assets(self):
        with tempfile.TemporaryDirectory(prefix="crew-evolve-package-test-") as temporary:
            root = Path(temporary) / "source"
            shutil.copytree(
                ROOT,
                root,
                ignore=shutil.ignore_patterns(
                    ".git", ".crew-evolve", "__pycache__", "*.pyc", "build", "dist",
                    "*.egg-info", "artifacts", "research", "models", "workspaces",
                ),
            )
            dist = root / "dist"
            result = subprocess.run(
                [sys.executable, "setup.py", "bdist_wheel", "--dist-dir", str(dist)],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            wheels = list(dist.glob("*.whl"))
            self.assertEqual(len(wheels), 1, result.stdout + result.stderr)
            with zipfile.ZipFile(wheels[0]) as archive:
                names = archive.namelist()
                unpacked = Path(temporary) / "unpacked"
                archive.extractall(unpacked)
            self.assertIn("crew_evolve/_assets/web/index.html", names)
            self.assertIn("crew_evolve/_assets/examples/crew.csv", names)
            self.assertFalse(any(".sqlite" in name or "/models/" in name for name in names))

            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(unpacked)
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from crew_evolve.resources import asset_dir; "
                    "print(asset_dir('web')); print(asset_dir('examples'))",
                ],
                cwd=temporary,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            paths = probe.stdout.splitlines()
            self.assertEqual(paths, [
                str(unpacked / "crew_evolve" / "_assets" / "web"),
                str(unpacked / "crew_evolve" / "_assets" / "examples"),
            ])

    def test_sdist_contains_source_assets_but_excludes_local_data(self):
        with tempfile.TemporaryDirectory(prefix="crew-evolve-sdist-test-") as temporary:
            root = Path(temporary) / "source"
            shutil.copytree(
                ROOT,
                root,
                ignore=shutil.ignore_patterns(
                    ".git", ".crew-evolve", "__pycache__", "*.pyc", "build", "dist",
                    "*.egg-info", "artifacts", "research", "models", "workspaces",
                ),
            )
            for directory in ("artifacts", "research", "models", "workspaces", "private_data"):
                private = root / directory
                private.mkdir()
                (private / "operator.sqlite").write_text("private")
            dist = root / "dist"
            result = subprocess.run(
                [sys.executable, "setup.py", "sdist", "--dist-dir", str(dist)],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            archives = list(dist.glob("*.tar.gz"))
            self.assertEqual(len(archives), 1, result.stdout + result.stderr)
            with tarfile.open(archives[0]) as archive:
                names = archive.getnames()
            self.assertTrue(any(name.endswith("/web/index.html") for name in names))
            self.assertTrue(any(name.endswith("/examples/crew.csv") for name in names))
            self.assertFalse(any("operator.sqlite" in name for name in names))
            self.assertFalse(any(f"/{directory}/" in name for directory in (
                "artifacts", "research", "models", "workspaces", "private_data"
            ) for name in names))
