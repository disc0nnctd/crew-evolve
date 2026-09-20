"""Record the offline source-contract demonstration with real Chromium.

The recorder uses a temporary SQLite workspace and Playwright's video output.
It never opens the current user's workspace or needs a provider key.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

# Make ``python3 scripts/record_demo.py`` work from any current directory
# without installing the package first.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crew_evolve.app import App
from crew_evolve.server import Server
from crew_evolve.store import Store


HEADERS = "Badge,Person,Home station,Position,Fleet types,cannot_work\n"
FIRST = HEADERS + (
    "C-10,Sam Taylor,DEL,captain,A320,true\n"
    "C-11,Alex Chen,DEL,first_officer,A320,false\n"
)
LATER = HEADERS + (
    "C-12,Jordan Lee,DEL,captain,A320,false\n"
    "C-13,Robin Shah,DEL,first_officer,A320,true\n"
)
CONTRACT = "staff-export-v1"


def pause(page, milliseconds: int = 2200) -> None:
    """Hold a main state long enough to read it without making a slow demo."""
    page.wait_for_timeout(min(milliseconds, 4000))


def slow_control(page) -> None:
    """Separate successive control changes in the recording."""
    page.wait_for_timeout(150)


def inspect(page, content: str, contract: str) -> None:
    page.get_by_label("Source contract", exact=False).fill(contract)
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
    for label, field in mappings.items():
        page.get_by_label(label, exact=True).select_option(field)
        slow_control(page)


def screenshot(page, output_dir: Path, number: int, name: str) -> None:
    page.screenshot(path=str(output_dir / f"demo-{number:02d}-{name}.png"), full_page=True)


def record(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    video_source: Path | None = None
    with tempfile.TemporaryDirectory(prefix="crew-evolve-demo-") as workspace:
        server = Server(("127.0.0.1", 0), App(Store(Path(workspace) / "workspace.sqlite")))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        browser = None
        context = None
        video = None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    record_video_dir=str(output_dir),
                    record_video_size={"width": 1280, "height": 900},
                )
                page = context.new_page()
                video = page.video
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                expect(page.get_by_text("Your roster starts here.")).to_be_visible()
                screenshot(page, output_dir, 1, "start")
                pause(page)

                page.get_by_role("button", name="Crew data").click()
                slow_control(page)
                pause(page, 1800)
                inspect(page, FIRST, CONTRACT)
                map_columns(page)
                page.get_by_label("cannot_work transform", exact=True).select_option("boolean")
                slow_control(page)
                page.get_by_label("Invert boolean meaning", exact=False).check()
                slow_control(page)
                screenshot(page, output_dir, 2, "explicit-inversion")
                pause(page)

                page.get_by_role("button", name="Test preview").click()
                expect(page.locator("#transform-status")).to_contain_text("Preview passed")
                screenshot(page, output_dir, 3, "tested-normalized")
                pause(page)
                page.get_by_role("button", name="Accept mapping and replace crew").click()
                expect(page.locator("#notice")).to_contain_text("Table imported")
                pause(page, 2000)

                inspect(page, LATER, CONTRACT)
                expect(page.locator("#contract-status")).to_contain_text("Reused reviewed contract")
                screenshot(page, output_dir, 4, "reused-contract")
                pause(page)
                page.get_by_role("button", name="Test preview").click()
                expect(page.locator("#transform-status")).to_contain_text("Preview passed")
                page.get_by_role("button", name="Accept mapping and replace crew").click()
                expect(page.locator("#notice")).to_contain_text("Table imported")
                pause(page, 2000)

                inspect(page, FIRST, CONTRACT)
                page.get_by_label("Invert boolean meaning", exact=False).uncheck()
                slow_control(page)
                page.get_by_role("button", name="Test preview").click()
                expect(page.locator("#transform-status")).to_contain_text("Preview rejected")
                expect(page.locator("#accept-import")).to_be_disabled()
                screenshot(page, output_dir, 5, "regression-rejected")
                pause(page)

                page.get_by_role("button", name="Learning").click()
                expect(page.locator("#history")).to_contain_text(CONTRACT)
                pause(page, 1800)
                page.get_by_role("button", name="Roll back learning").first.click()
                expect(page.locator("#notice")).to_contain_text("Imported records and operating policies are unchanged")
                screenshot(page, output_dir, 6, "rollback")
                pause(page)
                if errors:
                    raise RuntimeError("Browser errors during recording: " + "; ".join(errors))
                # Closing the context finalizes the WebM file before its path
                # is copied to the stable public artifact name.
                context.close()
                context = None
                video_path = video.path() if video else None
                if video_path:
                    video_source = Path(video_path)
                browser.close()
                browser = None
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
            server.shutdown()
            server.server_close()
            thread.join()

    if video_source is None or not video_source.exists():
        raise RuntimeError("Playwright did not produce a video file.")
    target = output_dir / "demo.webm"
    shutil.move(str(video_source), str(target))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    target = record(args.output_dir)
    print(f"Recorded {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
