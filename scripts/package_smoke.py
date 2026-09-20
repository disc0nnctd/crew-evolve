#!/usr/bin/env python3
"""Build distributions, install the wheel in a fresh venv, and exercise HTTP."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import venv
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_MARKERS = (
    "artifacts/", "research/", "models/", "workspaces/", "private/",
    "private_data/", "operator_data/", ".sqlite", ".db",
)
BROWSER_HEADERS = "Badge,Person,Home station,Position,Fleet types,cannot_work\n"
BROWSER_FIRST = BROWSER_HEADERS + "C-10,Sam Taylor,DEL,captain,A320,true\n"
BROWSER_LATER = BROWSER_HEADERS + "C-11,Alex Chen,DEL,captain,A320,false\n"


def run(command: list[str], cwd: Path, *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, check=False, text=True,
                            capture_output=capture)
    if result.returncode:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        result.check_returncode()
    return result


def copied_source(destination: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git", ".crew-evolve", "__pycache__", "*.pyc", "build", "dist",
        "*.egg-info", "artifacts", "research", "models", "workspaces",
        "private", "private_data", "operator_data",
    )
    shutil.copytree(ROOT, destination, ignore=ignored)


def archive_names(wheel: Path, source_archive: Path) -> tuple[list[str], list[str]]:
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    with tarfile.open(source_archive) as archive:
        source_names = archive.getnames()
    return wheel_names, source_names


def assert_assets(names: list[str], wheel: bool) -> None:
    prefix = "crew_evolve/_assets/" if wheel else "/"
    expected = (
        f"{prefix}web/index.html" if wheel else "/web/index.html",
        f"{prefix}examples/crew.csv" if wheel else "/examples/crew.csv",
    )
    for item in expected:
        if wheel:
            if item not in names:
                raise AssertionError(f"{item} is absent from the wheel")
        elif not any(name.endswith(item) for name in names):
            raise AssertionError(f"{item} is absent from the source archive")
    bad = [name for name in names if any(marker in name for marker in FORBIDDEN_MARKERS)]
    if bad:
        raise AssertionError(f"private or research files entered a distribution: {bad}")


def wait_for_server(process: subprocess.Popen[str]) -> str:
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read()
            raise RuntimeError(f"server exited before startup: {output}")
        ready = selector.select(max(0.05, deadline - time.monotonic()))
        if not ready:
            continue
        line = process.stdout.readline()
        match = re.search(r"(http://127\.0\.0\.1:\d+)", line)
        if match:
            return match.group(1)
    process.terminate()
    raise TimeoutError("server did not announce a listening address")


def request(base: str, path: str, *, body: dict | None = None, token: str | None = None) -> dict | bytes:
    headers = {}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["X-Workspace-Token"] = token or ""
        payload = json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as response:
        data = response.read()
        return json.loads(data) if response.headers.get_content_type() == "application/json" else data


def browser_workflow(base: str, label: str) -> None:
    """Exercise the installed UI without importing Playwright by default."""
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "--browser requires the host Playwright package and a Chromium install; "
            "install requirements-dev.txt and run `python -m playwright install chromium`."
        ) from exc

    def inspect(page, content: str, scope: str) -> None:
        page.get_by_label("Source contract", exact=False).fill(scope)
        page.get_by_label("Data file", exact=True).set_input_files({
            "name": "crew-export.csv",
            "mimeType": "text/csv",
            "buffer": content.encode(),
        })
        page.get_by_role("button", name="Inspect file").click()
        expect(page.locator("#import-review")).to_be_visible()

    def map_columns(page) -> None:
        mappings = {
            "Badge": "crew_id",
            "Person": "name",
            "Home station": "base",
            "Position": "role",
            "Fleet types": "aircraft",
            "cannot_work": "available",
        }
        for source, field in mappings.items():
            page.get_by_label(source, exact=True).select_option(field)

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            raise RuntimeError(
                "--browser could not launch Chromium; run `python -m playwright install chromium`."
            ) from exc
        page = browser.new_page(viewport={"width": 1280, "height": 950})
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            page.goto(base, wait_until="networkidle")
            expect(page).to_have_title("Crew Evolve · Operations workspace")
            page.get_by_role("button", name="Crew data").click()

            inspect(page, BROWSER_FIRST, "staff-export-v1")
            map_columns(page)
            page.get_by_label("cannot_work transform", exact=True).select_option("boolean")
            page.get_by_label("Invert boolean meaning", exact=False).check()
            page.get_by_role("button", name="Test preview").click()
            expect(page.locator("#transform-status")).to_contain_text("Preview passed")
            page.get_by_role("button", name="Accept mapping and replace crew").click()
            expect(page.locator("#notice")).to_contain_text("Table imported")

            inspect(page, BROWSER_LATER, "staff-export-v1")
            expect(page.locator("#contract-status")).to_contain_text("Reused reviewed contract")
            expect(page.get_by_label("cannot_work transform", exact=True)).to_have_value("boolean")
            expect(page.get_by_label("Invert boolean meaning", exact=False)).to_be_checked()
            page.get_by_role("button", name="Test preview").click()
            expect(page.locator("#transform-status")).to_contain_text("Preview passed")
            if page_errors:
                raise AssertionError(f"{label} browser page errors: {page_errors}")
        finally:
            browser.close()


def installed_http_smoke(temporary_root: Path, artifact: Path, label: str, *, needs_build_tools: bool = False,
                         browser: bool = False) -> None:
    venv_dir = temporary_root / f"venv-{label}"
    # An sdist needs the host's local setuptools and wheel to build without an
    # index. The wheel install uses a clean environment with no system packages.
    venv.EnvBuilder(with_pip=True, system_site_packages=needs_build_tools, clear=True).create(venv_dir)
    venv_python = venv_dir / "bin" / "python"
    if os.name == "nt":
        venv_python = venv_dir / "Scripts" / "python.exe"
    install = [str(venv_python), "-m", "pip", "install", "--no-index", "--no-deps"]
    if artifact.name.endswith(".tar.gz"):
        install.append("--no-build-isolation")
    install.append(str(artifact))
    run(install, temporary_root)

    workspace = temporary_root / f"workspace-{label}"
    server = subprocess.Popen(
        [str(venv_python), "-m", "crew_evolve.server", "--port", "0", "--data-dir", str(workspace)],
        cwd=temporary_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = wait_for_server(server)
        page = request(base, "/")
        if not isinstance(page, bytes) or b"Crew Evolve" not in page:
            raise AssertionError(f"{label} install did not return the packaged web page")
        if browser:
            browser_workflow(base, label)
        state = request(base, "/api/state")
        assert isinstance(state, dict)
        token = state["token"]
        demo = request(base, "/api/demo", body={}, token=token)
        if not isinstance(demo, dict) or "revision" not in demo:
            raise AssertionError(f"unexpected {label} demo response: {demo!r}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="also use host Playwright/Chromium to exercise each installed UI",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="crew-evolve-package-") as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / "source"
        copied_source(source)
        dist = source / "dist"
        dist.mkdir()
        run([sys.executable, "setup.py", "sdist", "--dist-dir", str(dist)], source)
        run([sys.executable, "setup.py", "bdist_wheel", "--dist-dir", str(dist)], source)
        wheels = list(dist.glob("*.whl"))
        sdists = list(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise AssertionError(f"expected one wheel and sdist, found {wheels} and {sdists}")
        wheel_names, source_names = archive_names(wheels[0], sdists[0])
        assert_assets(wheel_names, wheel=True)
        assert_assets(source_names, wheel=False)

        installed_http_smoke(temporary_root, wheels[0], "wheel", browser=args.browser)
        installed_http_smoke(temporary_root, sdists[0], "sdist", needs_build_tools=True, browser=args.browser)
        print(f"package smoke passed: {wheels[0].name}, {sdists[0].name}")


if __name__ == "__main__":
    main()
