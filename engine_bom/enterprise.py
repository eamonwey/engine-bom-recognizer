"""Enterprise field mapping, validated before import and applied without dropping source data."""
from .export import CSV_HEADERS, EXPORT_COLUMNS


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError('企业配置必须为对象')
    fields = profile.get('export_fields', {})
    if not isinstance(fields, dict) or any(k not in CSV_HEADERS or not isinstance(v, str) or not v.strip() for k,v in fields.items()):
        raise ValueError('export_fields 必须为 BOM 字段名到企业列名的映射')
    if len(set(fields.values())) != len(fields):
        raise ValueError('企业列名不能重复')
    rules = profile.get('required_annotations', [])
    if not isinstance(rules, list) or any(not isinstance(r, dict) or not all(isinstance(r.get(k),str) and r[k].strip() for k in ('id','requirement','source','applies_when')) for r in rules):
        raise ValueError('每条标注规则必须包含 id、requirement、source、applies_when')
    if len({r['id'] for r in rules}) != len(rules):
        raise ValueError('标注规则id不能重复')
    for rule in rules:
        terms = rule.get('match_terms', [])
        if not isinstance(terms,list) or any(not isinstance(v,str) or not v.strip() for v in terms):
            raise ValueError('match_terms必须为非空字符串组成的数组')
    from .engineering_checks import validate_engineering_config
    validate_engineering_config(profile.get('inspection_rules', {}), strict=True)
    dictionary = profile.get('parameter_dictionary', [])
    if not isinstance(dictionary, list) or any(not isinstance(v,str) or not v.strip() for v in dictionary):
        raise ValueError('parameter_dictionary 必须为字符串数组')
    return profile


def mapped_components(components, profile):
    validate_profile(profile)
    fields = profile.get('export_fields') or {k: CSV_HEADERS[k] for k in EXPORT_COLUMNS}
    return { 'schema_version':'1.0', 'profile_version':profile.get('version'),
             'field_mapping':fields,
             'rows':[{label: component.get(field) for field,label in fields.items()} for component in components] }
