"""Browser proof for the source-scoped import contract release flow.

Run with ``python3 -m tests.browser_release`` when Playwright and Chromium are
available.  The scenario deliberately changes the polarity after a contract
has been reviewed so the old evidence rejects the candidate before accept.
"""

import tempfile
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from crew_evolve.app import App
from crew_evolve.server import Server
from crew_evolve.store import Store


HEADERS = "Badge,Person,Home station,Position,Fleet types,cannot_work\n"
FIRST = HEADERS + "C-10,Sam Taylor,DEL,captain,A320,true\nC-11,Alex Chen,DEL,first_officer,A320,false\n"
LATER = HEADERS + "C-12,Jordan Lee,DEL,captain,A320,false\nC-13,Robin Shah,DEL,first_officer,A320,true\n"


def inspect(page, content, contract):
    page.get_by_label("Source contract", exact=False).fill(contract)
    page.get_by_label("Data file", exact=True).set_input_files({
        "name": "crew-export.csv",
        "mimeType": "text/csv",
        "buffer": content.encode(),
    })
    page.get_by_role("button", name="Inspect file").click()
    expect(page.locator("#import-review")).to_be_visible()


def map_columns(page):
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


def main():
    with tempfile.TemporaryDirectory() as directory:
        server = Server(("127.0.0.1", 0), App(Store(Path(directory) / "workspace.sqlite")))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 950})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_address[1]}")
                page.get_by_role("button", name="Crew data").click()

                # First review: cannot_work is explicit negative availability,
                # so the operator must visibly opt into inversion.
                inspect(page, FIRST, "staff-export-v1")
                map_columns(page)
                page.get_by_label("cannot_work transform", exact=True).select_option("boolean")
                page.get_by_label("Invert boolean meaning", exact=False).check()
                page.get_by_role("button", name="Test preview").click()
                expect(page.locator("#transform-status")).to_contain_text("Preview passed")
                expect(page.locator("#normalized-sample")).to_contain_text("available")
                page.get_by_label("Person", exact=True).select_option("")
                expect(page.locator("#accept-import")).to_be_disabled()
                page.get_by_label("Person", exact=True).select_option("name")
                page.get_by_role("button", name="Test preview").click()
                expect(page.locator("#transform-status")).to_contain_text("Preview passed")
                page.get_by_role("button", name="Accept mapping and replace crew").click()
                expect(page.locator("#notice")).to_contain_text("Table imported")

                # Same named source and exact schema reuse the reviewed
                # transform, and the UI labels that scope and version.
                inspect(page, LATER, "staff-export-v1")
                expect(page.locator("#contract-status")).to_contain_text("Reused reviewed contract")
                expect(page.locator("#contract-status")).to_contain_text("staff-export-v1")
                expect(page.get_by_label("cannot_work transform", exact=True)).to_have_value("boolean")
                expect(page.get_by_label("Invert boolean meaning", exact=False)).to_be_checked()
                page.get_by_role("button", name="Test preview").click()
                expect(page.locator("#transform-status")).to_contain_text("Preview passed")
                page.get_by_label("Source contract", exact=False).fill("staff-export-v2")
                expect(page.locator("#contract-status")).to_contain_text("Fresh review required")
                expect(page.get_by_label("cannot_work transform", exact=True)).to_have_value("identity")
                expect(page.locator("#accept-import")).to_be_disabled()
                page.get_by_label("Source contract", exact=False).fill("staff-export-v1")
                page.get_by_label("cannot_work transform", exact=True).select_option("boolean")
                page.get_by_label("Invert boolean meaning", exact=False).check()
                page.get_by_role("button", name="Test preview").click()
                expect(page.locator("#transform-status")).to_contain_text("Preview passed")
                page.get_by_role("button", name="Accept mapping and replace crew").click()
                expect(page.locator("#notice")).to_contain_text("Table imported")

                # A different name receives no silent semantic transfer.
                inspect(page, LATER, "unknown-source-v1")
                expect(page.locator("#contract-status")).to_contain_text("New contract scope")
                expect(page.locator("#contract-status")).to_contain_text("unknown-source-v1")

                # Revisit the known source, remove inversion, and prove the
                # saved example catches the polarity regression.
                inspect(page, FIRST, "staff-export-v1")
                expect(page.locator("#contract-status")).to_contain_text("Reused reviewed contract")
                page.get_by_label("Invert boolean meaning", exact=False).uncheck()
                page.get_by_role("button", name="Test preview").click()
                expect(page.locator("#transform-status")).to_contain_text("Preview rejected")
                expect(page.locator("#accept-import")).to_be_disabled()

                # The history view names the scope, preserves replay fields,
                # and rolls back future reuse while retaining imported data.
                page.get_by_role("button", name="Learning").click()
                expect(page.locator("#history")).to_contain_text("staff-export-v1")
                expect(page.locator("#history")).to_contain_text("regressions")
                page.get_by_role("button", name="Roll back learning").first.click()
                expect(page.locator("#notice")).to_contain_text("Imported records and operating policies are unchanged")

                page.set_viewport_size({"width": 375, "height": 812})
                for label in ("Operations", "Crew data", "Learning", "Performance"):
                    page.get_by_role("button", name=label).click()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Mobile overflow on {label}"
                assert not errors, errors
                browser.close()
                print("PASS: source-scoped inversion, reuse, unknown-source review, regression rejection, rollback, and mobile layout.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
