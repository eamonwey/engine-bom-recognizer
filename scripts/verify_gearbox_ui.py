"""Real browser regression for warnings, isolated candidates and located pairs."""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'data/acceptance/gearbox_fix_20261011'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8793)
    args=parser.parse_args()
    errors=[];checks={}
    fixture={'bom':{'components':[{'name_zh':'箱体'},{'name_zh':'透盖'},{'name_zh':'油封'}],
        'assembly':{'nodes':[],'unverified_nodes':[{'id':'bad','component_index':2,'evidence':'嵌入透盖',
            'verification_reason':'原候选父件与证据矛盾'}],'unresolved_component_indices':[0,1,2],
            'warning':'提取校验未通过，候选保留'}},'issues':[],
        'inspection':{'visual_status':'needs_review','stages':{'primary_visual':'provider_failed',
            'engineering_facts':'partial','dimension_links':'insufficient_evidence','focus_sweep':'validated'},
            'dimension_links':{'status':'insufficient_evidence','rejected_observations':[{'observation':{'value':'<bad>'},'reasons':['定位不合法']}]}},
        'run_consistency':{'status':'disagreement','warning':'历史预测不是标准答案',
            'references':[{'job_id':'test-reference','different_fields':['assembly']}]}}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        try:
            page=browser.new_page(viewport={'width':1366,'height':1000})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:'+str(args.port)+'/',wait_until='domcontentloaded')
            page.wait_for_load_state('networkidle')
            assert page.locator('#assembly-table').count()==1
            page.evaluate('(r)=>renderBomResult(r)',fixture)
            page.locator('#assembly-pending').evaluate('(el)=>el.open=true')
            page.locator('#inspection-coverage').evaluate('(el)=>{el.open=true;el.querySelectorAll("details").forEach(d=>d.open=true)}')
            coverage=page.locator('#inspection-coverage').inner_text()
            checks['failed_stage_visible']='模型调用失败' in coverage
            checks['partial_facts_visible']='部分事实可用' in coverage
            checks['no_evidence_not_reported_as_pass']='不能认定无问题' in coverage
            checks['same_file_disagreement_visible']='安装父子关系或每父用量不同' in coverage
            checks['raw_candidate_reason_visible']='原候选父件与证据矛盾' in page.locator('#assembly-pending').inner_text()
            checks['untrusted_text_is_escaped']=page.locator('#inspection-coverage bad').count()==0 and '<bad>' in coverage
            issue={'err_id':'ERR-01','message':'配合名义值不一致：62 / 60','origin':'dimension_link_rule',
                'linked_dimensions':[{'value':'Φ62J7','view':'A-A','feature':'孔座','source_page':1,'bbox':[.2,.5,.3,.6]},
                    {'value':'Φ60H9/h9','view':'A-A','feature':'盖口','source_page':1,'bbox':[.2,.7,.3,.8]}], 'evidence':'两处原文与对应关系独立复核'}
            fixture['issues']=[issue]
            fixture['inspection']['dimension_links']={'status':'provider_failed','issues':[issue],
                'micro_text':{'status':'validated','warning':'未确认公差字母',
                    'observations':[{'raw_text':'Φ62√7 <img>','source_page':1,'bbox':[.2,.5,.3,.6],'fit_unreadable':True}]},
                'local_text':{'status':'read','warning':'文字位置不是配合关系证据',
                    'observations':[{'raw_text':'60H9/h9','source_page':1,'bbox':[.2,.7,.3,.8]}]}}
            page.evaluate('(r)=>renderBomResult(r)',fixture)
            page.locator('#inspection-coverage').evaluate('(el)=>{el.open=true;el.querySelectorAll("details").forEach(d=>d.open=true)}')
            coverage=page.locator('#inspection-coverage').inner_text()
            checks['both_readings_and_positions_visible']='Φ62J7' in coverage and 'Φ60H9/h9' in coverage and '[0.2,0.7,0.3,0.8]' in coverage
            checks['local_text_available_after_cloud_failure']='本地尺寸文字定位' in coverage and '原文 60H9/h9' in coverage and '文字位置不是配合关系证据' in coverage
            checks['micro_reread_keeps_unresolved_fit_and_escapes_text']='局部文字回读（视觉模型）' in coverage and '公差代号未确认，未自动补全' in coverage and page.locator('#inspection-coverage img').count()==0
            checks['finding_origin_visible']='尺寸对应复核＋名义值规则' in page.locator('#bom-issues').inner_text()
            checks['no_browser_exceptions']=not errors
            OUTPUT.mkdir(parents=True,exist_ok=True)
            page.locator('#inspection-coverage').screenshot(path=str(OUTPUT/'ui_inspection_coverage.png'))
            page.locator('#assembly-pending').evaluate('(el)=>el.open=true')
            page.locator('#bom-assembly-panel').screenshot(path=str(OUTPUT/'ui_candidate_isolation.png'))
        finally:browser.close()
    report={'checks':checks,'browser_errors':errors,'note':'Rendered controlled regression fixtures, not real model accuracy evidence.'}
    (OUTPUT/'browser_regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))
    assert all(checks.values())


if __name__=='__main__':main()
