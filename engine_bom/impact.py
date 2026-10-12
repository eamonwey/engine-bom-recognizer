"""Local, explicit dependency graph and traceable change impact retrieval."""
import json
import re
from collections import deque


def validate_index(data):
    if not isinstance(data, dict) or not isinstance(data.get('objects'), list):
        raise ValueError('关联索引必须包含 objects 数组')
    indexed = {}
    for obj in data['objects']:
        if not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or not obj['id']:
            raise ValueError('关联对象缺少 ID')
        if obj['id'] in indexed:
            raise ValueError('关联对象 ID 重复')
        if obj.get('kind') not in ('document', 'bom', 'process', 'inspection', 'product'):
            raise ValueError('关联对象 kind 必须为 document/bom/process/inspection/product')
        if not isinstance(obj.get('keywords', []), list) or not all(isinstance(k, str) and k.strip() for k in obj.get('keywords', [])):
            raise ValueError('keywords 必须是非空字符串数组')
        if not isinstance(obj.get('identifiers', []), list) or not all(isinstance(k, str) and k.strip() for k in obj.get('identifiers', [])):
            raise ValueError('identifiers 必须是非空字符串数组')
        indexed[obj['id']] = obj
    for obj in indexed.values():
        deps = obj.get('depends_on', [])
        if not isinstance(deps, list) or any(not isinstance(d, str) or d not in indexed for d in deps):
            raise ValueError('depends_on 引用不存在的对象')
    return data


def load_index(path):
    with open(path, encoding='utf-8') as handle:
        return validate_index(json.load(handle))


def analyze_impact(items, index, max_depth=8):
    validate_index(index)
    objects = {o['id']: o for o in index['objects']}
    if not objects:
        return {'status': 'not_configured', 'objects': [], 'coverage': '尚未导入企业关联索引，不能判定无影响'}
    reverse = {key: [] for key in objects}
    for obj in objects.values():
        for dep in obj.get('depends_on', []):
            reverse[dep].append(obj['id'])
    findings = {}
    for change_index, item in enumerate(items):
        text = (str(item.get('before') or '') + '\n' + str(item.get('after') or '')).casefold()
        for obj in objects.values():
            terms = list(obj.get('keywords', [])) + list(obj.get('identifiers', []))
            hits = []
            for term in terms:
                if not isinstance(term, str) or not term.strip():
                    continue
                escaped = re.escape(term.casefold())
                pattern = r'(?<![a-z0-9])' + escaped + r'(?![a-z0-9])' if re.fullmatch(r'[\x00-\x7f]+', term) else escaped
                if re.search(pattern, text):
                    hits.append(term)
            if not hits:
                continue
            queue = deque([(obj['id'], [obj['id']])])
            visited = set()
            while queue:
                key, path = queue.popleft()
                if key in visited:
                    continue
                visited.add(key)
                target = objects[key]
                finding = findings.setdefault(key, {'id': key, 'name': target.get('name', key),
                    'kind': target['kind'], 'source': target.get('source', ''), 'reasons': [],
                    'severity': '高' if target.get('critical') else '中', 'status': 'needs_review'})
                finding['reasons'].append({'change_index': change_index, 'matched_terms': hits,
                    'dependency_path': path, 'relation': 'direct' if len(path) == 1 else 'dependent'})
                if len(path) <= max_depth:
                    queue.extend((child, path + [child]) for child in reverse[key] if child not in visited)
    return {'schema_version': '1.0', 'status': 'needs_review',
            'objects': list(findings.values()), 'indexed_objects': len(objects),
            'coverage': '仅覆盖已导入的关键词与依赖关系；结果及影响程度需工程师确认',
            'max_dependency_depth': max_depth}
