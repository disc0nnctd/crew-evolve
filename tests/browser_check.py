"""Real Chromium checks; optional development dependency: playwright.

Run: python -m tests.browser_check
Writes screenshots under artifacts/ (not committed).
"""

import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

from crew_evolve.app import App
from crew_evolve.server import Server
from crew_evolve.store import Store


def main():
    with tempfile.TemporaryDirectory() as directory:
        server = Server(('127.0.0.1', 0), App(Store(Path(directory) / 'workspace.sqlite')))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        artifacts = Path('artifacts')
        artifacts.mkdir(exist_ok=True)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_address[1]}')
                expect(page.get_by_text('Your roster starts here.')).to_be_visible()
                page.get_by_role('button', name='Explore example data').click()
                expect(page.locator('#stats')).to_contain_text('6')
                page.get_by_role('button', name='Find cover').first.click()
                expect(page.locator('#answer')).to_contain_text('1 crew member passes')
                expect(page.locator('#answer')).to_contain_text('Rest after D-099 is 3 hours')
                page.screenshot(path=str(artifacts / 'operations-desktop.png'))
                page.get_by_role('button', name='Assign to this position').click()
                expect(page.locator('#answer')).to_contain_text('Asha Rao is assigned')
                page.locator('#roster tr').filter(has_text='D-100').filter(has_text='captain').get_by_role('button', name='Release').click()
                expect(page.locator('#answer')).to_contain_text('Position released')

                page.get_by_role('button', name='Learning').click()
                page.get_by_label('When I say').fill('Find someone for D-100 as captain')
                page.get_by_role('button', name='Test and learn correction').click()
                expect(page.locator('#history')).to_contain_text('Workflow correction')
                page.get_by_role('button', name='Operations', exact=False).click()
                page.get_by_label('Ask about your operation').fill('Find someone for D-101 as captain')
                page.get_by_role('button', name='Ask assistant').click()
                expect(page.locator('#answer')).to_contain_text('learned workflow')
                expect(page.locator('#answer')).to_contain_text('2 crew members pass')

                page.get_by_role('button', name='Learning').click()
                page.get_by_label('Minimum rest (h)').fill('12')
                page.get_by_label('Why change it?').fill('Test a more conservative example policy')
                page.get_by_role('button', name='Compare proposal').click()
                expect(page.locator('#history')).to_contain_text('candidate checks')
                page.get_by_role('button', name='Activate reviewed policy').click()
                expect(page.locator('#notice')).to_contain_text('Reviewed policy activated')

                page.get_by_role('button', name='Crew data').click()
                page.get_by_label('Data file').set_input_files('examples/unfamiliar-crew.csv')
                page.get_by_role('button', name='Inspect file').click()
                expect(page.locator('#import-review')).to_be_visible()
                mappings = {'Badge':'crew_id','Person':'name','Home station':'base','Position':'role','Fleet types':'aircraft','On call':'available'}
                for label, field in mappings.items():
                    page.get_by_label(label, exact=True).select_option(field)
                page.get_by_role('button', name='Accept mapping and replace crew').click()
                expect(page.locator('#notice')).to_contain_text('Table imported')
                page.get_by_role('button', name='Inspect file').click()
                expect(page.get_by_label('Badge', exact=True)).to_have_value('crew_id')
                expect(page.get_by_label('Person', exact=True)).to_have_value('name')

                page.get_by_role('button', name='Performance').click()
                page.get_by_role('button', name='Benchmark algorithms').click()
                expect(page.locator('#benchmark-status')).to_contain_text('Benchmark complete', timeout=120000)
                expect(page.locator('#benchmark-results')).to_contain_text('Passed')
                page.screenshot(path=str(artifacts / 'performance-desktop.png'), full_page=True)
                page.set_viewport_size({'width':375,'height':812})
                for label in ('Operations','Crew data','Learning','Performance'):
                    page.get_by_role('button', name=label).click()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Mobile overflow on {label}'
                page.screenshot(path=str(artifacts / 'performance-mobile.png'), full_page=True)
                assert not errors, errors
                browser.close()
                print('PASS: real-browser import, learned mapping, workflow transfer, coverage, assignment, release, reviewed policy, benchmark, and mobile layouts.')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()
