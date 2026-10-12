"""Report repeat-run disagreements, without treating old predictions as truth."""
import json
from pathlib import Path


def snapshot(result):
    components=(result.get('bom') or {}).get('components') or []
    # Stable printed identity; row order and generated node IDs are not identity.
    def identity(index):
        if type(index) is not int or not 0<=index<len(components):return None
        c=components[index]
        return (str(c.get('item_no') or ''),str(c.get('part_number') or ''),str(c.get('name_zh') or c.get('name_en') or ''))
    bom=sorted((identity(i),str(c.get('quantity')),str(c.get('material') or '')) for i,c in enumerate(components))
    tree=(result.get('bom') or {}).get('assembly') or {}
    indexed={n.get('id'):n for n in tree.get('nodes',[]) if isinstance(n,dict) and isinstance(n.get('id'),str)}
    edges=[]
    for n in indexed.values():
        parent=indexed.get(n.get('parent_id')) if isinstance(n.get('parent_id'),str) else None
        edges.append((identity(n.get('component_index')),identity(parent.get('component_index')) if parent else None,str(n.get('quantity_per_parent'))))
    # Compare serialized multisets, never insert/overwrite a previous relation.
    return {'bom':json.dumps(bom,ensure_ascii=False,sort_keys=True),
            'assembly':json.dumps(sorted(edges,key=lambda e:json.dumps(e,ensure_ascii=False)),ensure_ascii=False),
            'dimension_count':len(result.get('dimensions') or []),
            'finding_types':sorted(i.get('err_id','') for i in result.get('issues',[]) if isinstance(i,dict))}


def compare_runs(result,history_dir,exclude_job=None,limit=5):
    digest=result.get('source_sha256')
    report={'status':'no_reference','references':[],'warning':'历史预测不是标准答案；重复运行一致也不能证明正确。'}
    if not isinstance(digest,str) or len(digest)!=64:return report
    paths=sorted(Path(history_dir).glob('*.json'),key=lambda p:p.name,reverse=True)
    current=snapshot(result)
    for path in paths:
        if path.stem==exclude_job:continue
        try:
            previous=json.loads(path.read_text(encoding='utf-8'))
            old=previous.get('result')
            if not isinstance(old,dict) or old.get('source_sha256')!=digest:continue
            before=snapshot(old)
        except (OSError,ValueError,TypeError,AttributeError):continue
        fields=[field for field in current if current[field]!=before[field]]
        report['references'].append({'job_id':path.stem,'different_fields':fields,
            'model':(old.get('model_info') or {}).get('model'),'human_reviewed':(old.get('bom') or {}).get('status')=='reviewed'})
        if len(report['references'])>=limit:break
    if report['references']:
        report['status']='disagreement' if any(r['different_fields'] for r in report['references']) else 'consistent_summary'
    return report
