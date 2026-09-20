"""Build the package and copy the web/demo assets into it.

The source tree keeps ``web/`` and ``examples/`` at the repository root so
they remain convenient to edit.  A built distribution receives regular copied
files under ``crew_evolve/_assets``; no symlink is used.
"""

from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


ROOT = Path(__file__).resolve().parent


class build_py(_build_py):
    """Copy runtime assets after setuptools has copied Python modules."""

    def run(self):
        super().run()
        package_assets = Path(self.build_lib) / "crew_evolve" / "_assets"
        if package_assets.exists():
            shutil.rmtree(package_assets)
        for asset_name in ("web", "examples"):
            source = ROOT / asset_name
            if not source.is_dir():
                raise RuntimeError(f"Required package asset directory is missing: {source}")
            shutil.copytree(source, package_assets / asset_name)


setup(cmdclass={"build_py": build_py})
