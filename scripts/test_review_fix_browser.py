"""Headless UI regression against an isolated local HTTP server and synthetic BOM."""
import json
import io
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine_bom import webapp
from playwright.sync_api import sync_playwright, expect


def main():
    with tempfile.TemporaryDirectory() as directory:
        result = {'document_id': 'sample', 'bom': {'components': [{'part_number': 'A', 'quantity': 1}, {'part_number': 'B', 'quantity': 2}],
                  'assembly': {'nodes': [{'id': 'n', 'parent_id': None, 'level': 1,
                    'component_index': 0, 'source_page': 1, 'evidence': 'A original label'}]}},
                  'model_info': {'provider': 'mock'}}
        job = {'id': 'j', 'kind': 'bom', 'status': 'done', 'dir': directory, 'result': result}
        with patch.object(webapp, 'DATA_DIR', directory), patch.object(webapp, 'REVIEWLOG_PATH', str(Path(directory, 'log.json'))), patch.object(webapp, '_jobs', {'j': job}):
            server = webapp._WebServer(('127.0.0.1', 0), webapp.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel='msedge', headless=True)
                    page = browser.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto('http://127.0.0.1:%d/#bom' % server.server_address[1])
                    page.wait_for_load_state('networkidle')
                    assert page.locator('#bom-save').count() == 1
                    page.evaluate('(result) => {bomJobId="j"; renderBomResult(result);}', result)
                    quantity = page.locator('#bom-table [data-c="quantity"]').first
                    quantity.fill('1.5')
                    with page.expect_response('**/api/bom/save') as response:
                        page.locator('#bom-save').click()
                    assert response.value.status == 400
                    assert job['result']['bom']['components'][0]['quantity'] == 1
                    quantity.fill('abc')
                    with page.expect_response('**/api/bom/save') as response:
                        page.locator('#bom-save').click()
                    assert response.value.status == 400
                    quantity.fill('2')
                    with page.expect_response('**/api/bom/save') as response:
                        page.locator('#bom-save').click()
                    assert response.value.status == 200
                    expect(page.locator('#assembly-editor')).to_have_value('{\n  "nodes": []\n}')
                    assert page.evaluate('bomRevision') == 1
                    assert 'A original label' not in page.locator('#assembly-table').inner_text()
                    assert json.loads(Path(directory, 'log.json').read_text(encoding='utf-8'))[0]['after'][0]['quantity'] == 2
                    page.locator('#bom-assembly-panel details').filter(has=page.locator('#assembly-editor')).locator('summary').click()
                    page.locator('#assembly-reviewer').fill('UI test reviewer')
                    tree = {'nodes': [
                        {'id': 'r', 'parent_id': None, 'component_index': 0, 'source_page': 1, 'evidence': 'A base'},
                        {'id': 'b', 'parent_id': 'r', 'component_index': 1, 'source_page': 1,
                         'evidence': 'B attachment', 'quantity_per_parent': 2}]}
                    page.locator('#assembly-editor').fill(json.dumps(tree))
                    with page.expect_response('**/api/assembly/save') as response:
                        page.locator('#assembly-save').click()
                    assert response.value.status == 200
                    assert response.value.json()['assembly']['quantity_status'] == 'conflict'
                    expect(page.locator('#assembly-status')).to_contain_text('ERR-08')
                    expect(page.locator('#bom-validation-issues')).to_contain_text('ERR-08')
                    tree['nodes'][1]['quantity_per_parent'] = 1
                    page.locator('#assembly-editor').fill(json.dumps(tree))
                    with page.expect_response('**/api/assembly/save') as response:
                        page.locator('#assembly-save').click()
                    assert response.value.json()['assembly']['quantity_status'] == 'consistent'
                    expect(page.locator('#assembly-status')).not_to_contain_text('ERR-08')
                    expect(page.locator('#bom-validation-issues')).to_be_hidden()
                    page.evaluate('''() => renderAssembly({nodes:[
                        {id:'r',component_index:0,parent_id:null,level:1,source_page:1,evidence:'A'},
                        {id:'b',component_index:1,parent_id:'r',level:2,source_page:1,evidence:'B',quantity_per_parent:1}],
                        relation_semantics:'bom_contains',unresolved_relations:[
                        {parent:'c0',child:'c1',source_page:1,evidence:'候选原文',verification_reason:'证据不足'}]})''')
                    expect(page.locator('#assembly-table')).to_contain_text('安装父件')
                    expect(page.locator('#assembly-status')).to_contain_text('此历史结果仅有总成明细')
                    expect(page.locator('#assembly-pending summary')).to_contain_text('1')
                    page.locator('#assembly-pending summary').click()
                    expect(page.locator('#assembly-pending')).to_contain_text('证据不足')
                    context = {'part_number': 'TOP', 'name_zh': '标题总成', 'quantity': 1,
                               'source_page': 1, 'evidence': '标题 TOP 每套1'}
                    tree = {'context_components': [context], 'nodes': [
                        {'id': 'top', 'component_index': 2, 'parent_id': None, 'source_page': 1, 'evidence': '标题 TOP'},
                        {'id': 'a', 'component_index': 0, 'parent_id': 'top', 'source_page': 1, 'evidence': 'A 2', 'quantity_per_parent': 2},
                        {'id': 'b', 'component_index': 1, 'parent_id': 'top', 'source_page': 1, 'evidence': 'B 2', 'quantity_per_parent': 2}]}
                    job['result']['bom']['assembly'].update(relation_semantics='bom_contains',
                        relation_candidates=[{'component_id': 'd0', 'context_component': context}],
                        unresolved_relations=[{'parent': 'd0', 'child': 'c0'}])
                    page.locator('#assembly-editor').fill(json.dumps(tree))
                    with page.expect_response('**/api/assembly/save') as response:
                        page.locator('#assembly-save').click()
                    saved = response.value.json()['assembly']
                    assert saved['status'] == 'reviewed', saved
                    assert saved['component_refs']['d0'] == 2
                    assert saved['quantity_status'] == 'consistent'
                    expect(page.locator('#assembly-status')).to_contain_text('此历史结果仅有总成明细')
                    expect(page.locator('#assembly-table')).not_to_contain_text('TOP')
                    assert 'TOP' in page.locator('#assembly-editor').input_value()
                    assert 'context_components' in page.locator('#assembly-editor').input_value()
                    # New inspection evidence must be visible, safe to render and
                    # distinct from an engineering compliance approval.
                    from engine_bom.engineering_checks import run_engineering_checks
                    from engine_bom.hybrid_inspection import ground_coverage
                    engineering = run_engineering_checks({},
                        [{'value':'20±-0.1','unit':'mm','source_page':1}], [],
                        {'scale':'1:0'}, {'title_source_page':1},
                        [{'source_page':1,'kind':'raster_or_cad_render'}])
                    ui_result = dict(result, issues=engineering['issues'],
                        inspection={'engineering':engineering,
                            'checklist':ground_coverage({},engineering['issues'],{'issues':[]},engineering),
                            'visual_status':'validated'})
                    engineering['checks'][0]['evidence'] = '<script>window.inspectionInjected=true</script>'
                    page.evaluate('(data) => renderBomResult(data)', ui_result)
                    expect(page.locator('#bom-issues')).to_contain_text('ERR-03')
                    expect(page.locator('#bom-issues')).to_contain_text('ERR-10')
                    page.locator('#inspection-coverage > summary').click()
                    expect(page.locator('#inspection-coverage')).to_contain_text('非实时标准库')
                    expect(page.locator('#inspection-coverage')).to_contain_text('已计算')
                    page.locator('#inspection-coverage details > summary').click()
                    expect(page.locator('#inspection-coverage')).to_contain_text('<script>window.inspectionInjected=true</script>')
                    assert page.evaluate('window.inspectionInjected') is None
                    # Render real computed closing intervals, including a normal
                    # chain. A clean issue list must not hide its calculation.
                    from engine_bom.tolerance_chains import validate_tolerance_chains
                    from tests.test_tolerance_chains import gap_fixture
                    for requirement, label in [('10±0.1','部分极限组合可能超差'),('10±0.2','恰好达到允许边界')]:
                        dims,chain,_=gap_fixture(requirement)
                        calculations,issues,validation=validate_tolerance_chains([chain],dims,1)
                        assert not validation
                        calculations[0]['requirement_evidence']='<script>window.toleranceInjected=true</script>'
                        data=dict(ui_result,dimensions=dims,issues=issues,
                            inspection=dict(ui_result['inspection'],dimension_chains={
                                'status':'checked','tolerance_status':'checked','tolerance_evidence':'主视图S=L-B',
                                'tolerance_chains':calculations}))
                        page.evaluate('(data)=>renderBomResult(data)',data)
                        expect(page.locator('#tolerance-chain-evidence')).to_contain_text(label)
                        page.locator('#tolerance-chain-evidence details > summary').click()
                        expect(page.locator('#tolerance-chain-evidence')).to_contain_text('9.8')
                        expect(page.locator('#tolerance-chain-evidence')).to_contain_text('10.2')
                        expect(page.locator('#tolerance-chain-evidence')).to_contain_text('减环')
                        expect(page.locator('#tolerance-chain-evidence')).to_contain_text('<script>window.toleranceInjected=true</script>')
                        assert page.evaluate('window.toleranceInjected') is None
                    # A clipped contour is refined on the original page. Canvas
                    # CSS scaling must not change normalized drag coordinates.
                    from tests.test_layout_completeness import clipped_view
                    from engine_bom.region_geometry import refine_region
                    image=clipped_view();buffer=io.BytesIO();image.save(buffer,format='PNG')
                    page.route('**/api/pages/j?*',lambda route:route.fulfill(body=buffer.getvalue(),content_type='image/png'))
                    region=refine_region(image,{'kind':'view','source_page':1,
                        'bbox':[.2,.1,.72,.75],'evidence':'零件7 B-B'})
                    region['bbox_warning'] += '<script>window.regionInjected=true</script>'
                    data=dict(ui_result,layout={'regions':[region]},inspection=dict(ui_result['inspection'],
                        dimension_extraction={'status':'needs_review','warnings':['原文证据指向另一个尺寸']}))
                    page.evaluate('(data)=>{ insJobId="j"; renderBomResult(data); }',data)
                    expect(page.locator('#dimension-extraction-warning')).to_contain_text('没有可信尺寸输入')
                    page.locator('.region-locate').click()
                    page.wait_for_function("() => insDragMode === 'view' && insPreviewImage !== null")
                    assert page.evaluate('insRegionBox') == region['bbox']
                    assert page.evaluate('insSelectedBox') is None
                    assert page.evaluate('insPreviewPage') == 1
                    assert page.evaluate('window.regionInjected') is None
                    page.evaluate("document.querySelector('#ins-preview').style.width='250px'")
                    canvas=page.locator('#ins-preview');canvas.scroll_into_view_if_needed()
                    box=canvas.bounding_box()
                    page.mouse.move(box['x']+box['width']*.1,box['y']+box['height']*.2)
                    page.mouse.down()
                    page.mouse.move(box['x']+box['width']*.8,box['y']+box['height']*.9,steps=4)
                    page.mouse.up()
                    actual=page.evaluate('insRegionBox')
                    assert all(abs(a-b)<.01 for a,b in zip(actual,[.1,.2,.8,.9])),actual
                    assert page.evaluate('insSelectedBox') is None
                    submitted=[]
                    page.on('request',lambda req:submitted.append(req.url) if '/api/jobs/correct' in req.url else None)
                    page.locator('#ins-correct').click()
                    expect(page.locator('#ins-box-status')).to_contain_text('蓝框查看模式')
                    assert not submitted
                    page.locator('#ins-mode-text').click()
                    canvas.scroll_into_view_if_needed();box=canvas.bounding_box()
                    page.mouse.move(box['x']+box['width']*.2,box['y']+box['height']*.3)
                    page.mouse.down()
                    page.mouse.move(box['x']+box['width']*.4,box['y']+box['height']*.5,steps=4)
                    page.mouse.up()
                    assert page.evaluate('insRegionBox') is None
                    actual=page.evaluate('insSelectedBox')
                    assert all(abs(a-b)<.01 for a,b in zip(actual,[.2,.3,.4,.5])),actual
                    page.locator('.region-locate').click()
                    page.wait_for_function("() => insDragMode === 'view' && insPreviewImage !== null")
                    assert page.evaluate('insSelectedBox') is None
                    artifact=Path(__file__).resolve().parents[1]/'data'/'acceptance'/'tolerance_chains_20261011'/'layout_browser.png'
                    canvas.screenshot(path=str(artifact))
                    assert not errors, errors
                    browser.close()
                    print('PASS: BOM/review regressions; tolerance evidence; clipped view refinement; CSS-scaled blue/red selection; blue box cannot submit correction; extraction failure and XSS handled; no JS errors')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    main()
