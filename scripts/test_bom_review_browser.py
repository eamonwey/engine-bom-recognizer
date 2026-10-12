"""Offline browser checks for BOM editing and authenticated snapshot review."""
import copy
import hashlib
import json
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine_bom import webapp
from engine_bom.review_workflow import ReviewStore
from engine_bom.schema import BomComponent, validate_components
from playwright.sync_api import sync_playwright, expect


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        components = [BomComponent(item_no=1, part_number='A', name_zh='轴', quantity=0),
                      BomComponent(item_no=2, part_number='B', name_zh='齿轮', quantity=2)]
        findings = validate_components(components)
        result = {'document_id': 'sample', 'bom': {'components': [c.to_dict() for c in components],
                  'validation_issues': findings, 'assembly': {'nodes': []}}, 'model_info': {'provider': 'mock'}}
        job = {'id': 'j', 'kind': 'bom', 'status': 'done', 'dir': directory, 'result': result}
        token = 'browser-reviewer'
        (root / 'review_users.json').write_text(json.dumps([
            {'id': 'r', 'role': 'reviewer', 'token_sha256': hashlib.sha256(token.encode()).hexdigest()}]), encoding='utf-8')
        ReviewStore(str(root / 'reviews.sqlite')).transition('snapshot', 'submit', {'id': 'e', 'role': 'editor'}, payload={'weight': 2.0})
        with patch.object(webapp, 'DATA_DIR', directory), patch.object(webapp, 'REVIEWLOG_PATH', str(root / 'log.json')), patch.object(webapp, '_jobs', {'j': job}):
            server = webapp._WebServer(('127.0.0.1', 0), webapp.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel='msedge', headless=True)
                    try:
                        page = browser.new_page()
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto('http://127.0.0.1:%d/#bom' % server.server_address[1])
                        page.wait_for_load_state('networkidle')
                        assert page.locator('#bom-table').count() == 1
                        empty = copy.deepcopy(result)
                        empty['bom']['components'] = []
                        page.evaluate('(result) => {bomJobId="j"; renderBomResult(result);}', empty)
                        page.evaluate('(result) => renderBomResult(result)', result)
                        assert page.locator('#bom-table th').count() > 2
                        expect(page.locator('#bom-table [data-c="weight"]')).to_have_count(2)

                        # Searching must not remove a row while its name is edited.
                        search = page.locator('#bom-search')
                        search.fill('轴')
                        name = page.locator('#bom-table [data-c="name_zh"]').first
                        name.fill('凸轮')
                        expect(name).to_be_visible()
                        search.click()
                        expect(name).to_be_hidden()
                        search.fill('')
                        expect(name).to_be_visible()

                        # Force the flagged first column to be editable to exercise
                        # the conditional badge case; symbols remain outside values.
                        page.evaluate('BOM_COLS=["part_number","quantity","name_zh"]; renderBomTable();')
                        part = page.locator('#bom-table [data-c="part_number"]').first
                        part.fill('A2')
                        assert page.evaluate('bomComponents[0].part_number') == 'A2'
                        assert '⚠' not in part.inner_text()
                        page.locator('#bom-table [data-c="quantity"]').first.fill('2')
                        with page.expect_response('**/api/bom/save') as response:
                            page.locator('#bom-save').click()
                        assert response.value.status == 200
                        expect(page.locator('#bom-table .review-flag')).to_have_count(0)
                        assert job['result']['bom']['components'][0]['needs_review'] is False

                        # The visible review workflow supplies the identity token
                        # and survives 2.0 -> 2 through JSON.stringify/parse.
                        page.locator('#nav [data-view="review"]').click()
                        page.locator('#workflow-id').fill('snapshot')
                        page.locator('#workflow-token').fill(token)
                        with page.expect_response('**/api/reviews/snapshot') as loaded:
                            page.locator('#workflow-load').click()
                        assert loaded.value.status == 200
                        with page.expect_response('**/api/reviews/transition') as reviewed:
                            page.locator('[data-review-action="review"]').click()
                        assert reviewed.value.status == 200
                        assert reviewed.value.json()['state'] == 'reviewed'
                        assert not errors, errors
                        print('PASS: empty/nonempty columns, stable search editing, badge isolation, refreshed flags, authenticated numeric snapshot review; no JS errors')
                    finally:
                        browser.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()
