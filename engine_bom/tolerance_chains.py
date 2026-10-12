"""One-dimensional, evidence-linked worst-case tolerance stacks.

No statistical distributions, implicit general tolerances or pixel measurements.
Independent VLM facts feed a unique endpoint graph; fallback model paths must
pass the same validation. Intervals use the ORIGINAL dimension strings.
"""
from decimal import Decimal, localcontext

from .engineering_checks import parse_size


def _label(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('缺少非空端点、视图或证据文本')
    return value.strip()


def _index(value, dimensions):
    if type(value) is not int or not 0 <= value < len(dimensions):
        raise ValueError('尺寸引用必须为从0起始的有效整数下标')
    return value


def _limits(dimension, closing=False):
    if not isinstance(dimension, dict):
        raise ValueError('引用的尺寸必须为对象')
    value = dimension.get('value')
    if not isinstance(value, str) or len(value) > 160:
        raise ValueError('尺寸必须提供可追溯的原文字符串（不超过160字符）')
    parsed = parse_size(value, dimension.get('unit') or '', allow_signed_limits=closing)
    if parsed['kind'] != 'linear' or parsed['band']:
        raise ValueError('本阶段只处理明确极限的线性长度，不处理直径、半径、角度或公差带代号')
    if not parsed['unit_known']:
        raise ValueError('公差尺寸链单位必须明确，不能猜为mm')
    if not parsed['explicit_limits'] or parsed['lower'] is None or parsed['upper'] is None:
        raise ValueError('未注公差不是零公差；缺少明确上下偏差或极限尺寸')
    return parsed


def calculate_chain(chain, dimensions, pages):
    """Validate a directed simple path and calculate its closing interval."""
    from .dimension_chains import _linear_interval
    if not isinstance(chain, dict):
        raise ValueError('公差链必须为对象')
    page = chain.get('source_page')
    if type(page) is not int or not 1 <= page <= pages:
        raise ValueError('公差链来源页无效')
    view, evidence = _label(chain.get('view')), _label(chain.get('evidence'))
    start, end = _label(chain.get('start')), _label(chain.get('end'))
    if start == end:
        raise ValueError('封闭环尺寸的两个界面不能相同')
    terms = chain.get('terms')
    if not isinstance(terms, list) or not 2 <= len(terms) <= 100:
        raise ValueError('公差尺寸链须有2至100个组成环')
    closing_index = _index(chain.get('closing_index'), dimensions)
    closing = dimensions[closing_index]
    if not isinstance(closing, dict) or closing.get('dimension_role') != 'closing_requirement':
        raise ValueError('封闭环必须来自明确的装配功能要求，不能把任意零件公差当作装配要求')
    role_evidence = _label(closing.get('role_evidence'))
    from .titleblock import dimension_role_error
    role_error=dimension_role_error(closing)
    if role_error:raise ValueError(role_error)
    refs = [closing_index]
    for term in terms:
        if not isinstance(term, dict) or type(term.get('coefficient')) is not int or term['coefficient'] not in (-1, 1):
            raise ValueError('组成环系数只允许整数+1或-1')
        refs.append(_index(term.get('dimension_index'), dimensions))
    if len(set(refs)) != len(refs):
        raise ValueError('禁止重复使用组成尺寸或把封闭环加入组成环')
    dims = [dimensions[i] for i in refs]
    if any(not isinstance(d,dict) or d.get('dimension_role') != 'component' for d in dims[1:]):
        raise ValueError('组成环必须明确为组成长度，不能把其他功能要求或未知角色加入计算')
    scopes = {d.get('assembly_scope') or d.get('part_id') for d in dims if isinstance(d,dict)}
    scopes.discard(None)
    scopes.discard('')
    if any(not isinstance(scope,str) for scope in scopes) or len(scopes)>1:
        raise ValueError('公差链不得混合不同装配或独立零件分区')
    for d in dims:
        if not isinstance(d, dict) or d.get('view') != view or type(d.get('source_page')) is not int or d['source_page'] != page:
            raise ValueError('公差链各尺寸必须有相同的原始页码和视图，禁止跨页/跨视图拼接')
        geometry = d.get('linear_geometry')
        if not isinstance(geometry, dict) or not isinstance(geometry.get('evidence'), str) or not geometry['evidence'].strip():
            raise ValueError('公差链缺少独立尺寸端点的原文证据')
    intervals = [_linear_interval(d) for d in dims]
    axis, left, right = intervals[0]
    if any(g[0] != axis for g in intervals):
        raise ValueError('公差链不得混合水平与竖直方向')
    # A sign is determined by traversal in image coordinates, not by a desired
    # arithmetic answer. A component traversed backwards is a decreasing link.
    span = max(g[2] for g in intervals) - min(g[1] for g in intervals)
    epsilon = min(.003, span * .01)
    cursor, position = start, left
    positions = {start: left, end: right}
    visited = {start}
    for term, (_, lo, hi) in zip(terms, intervals[1:]):
        a, b = _label(term.get('start')), _label(term.get('end'))
        if a != cursor or b in visited:
            raise ValueError('组成环必须按连续、无回路的行走路径排列：当前应从%s出发；减环start/end须写反向行走端点，不能照录原尺寸顺序' % cursor)
        p, q = (lo, hi) if term['coefficient'] == 1 else (hi, lo)
        if abs(p - position) > epsilon:
            raise ValueError('增减环符号或相接端点与独立几何证据不符')
        if b in positions and abs(q - positions[b]) > epsilon:
            raise ValueError('同名界面的投影位置不一致')
        # Distinct physical interfaces must not be disguised as different labels
        # at the same coordinate, nor may the path revisit the closing endpoint.
        if any(name != b and abs(q - pos) <= epsilon for name, pos in positions.items()):
            raise ValueError('不同端点标签不能指代同一投影位置')
        if b == end and term is not terms[-1]:
            raise ValueError('路径到达封闭环终点后仍有额外组成环')
        positions[b], cursor, position = q, b, q
        visited.add(b)
    if cursor != end or abs(position - right) > epsilon:
        raise ValueError('组成环路径未连接封闭环的两个实际端点')
    # High precision prevents cancellation of long lengths with tiny tolerances.
    with localcontext() as context:
        context.prec = 60
        requirement = _limits(closing, closing=True)
        sizes = [_limits(d) for d in dims[1:]]
        minimum = maximum = Decimal(0)
        nominal = Decimal(0) if all(s['nominal'] is not None for s in sizes) else None
        records, expression = [], []
        for term, dim, size in zip(terms, dims[1:], sizes):
            sign = term['coefficient']
            low, high = (size['lower'], size['upper']) if sign == 1 else (-size['upper'], -size['lower'])
            minimum += low
            maximum += high
            if nominal is not None:
                nominal += sign * size['nominal']
            expression.append(('%sD%d' % ('+' if sign == 1 else '-', term['dimension_index'])))
            records.append({'dimension_index':term['dimension_index'], 'coefficient':sign,
                'role':'增环' if sign == 1 else '减环', 'original_value':dim['value'],
                'label':str(dim.get('tag') or '尺寸项%d' % (term['dimension_index']+1)),
                'source_page':page, 'view':view, 'linear_geometry':dim['linear_geometry'],
                'nominal_mm':str(size['nominal']) if size['nominal'] is not None else None,
                'lower_mm':str(size['lower']), 'upper_mm':str(size['upper']),
                'contribution_min_mm':str(low), 'contribution_max_mm':str(high)})
        allowed_low, allowed_high = requirement['lower'], requirement['upper']
        contained = minimum >= allowed_low and maximum <= allowed_high
        disjoint = maximum < allowed_low or minimum > allowed_high
        result = {'method':'worst_case_1d', 'unit':'mm', 'formula':'D%d = %s' % (closing_index, ' '.join(expression)),
            'display_formula':str(closing.get('tag') or '封闭环') + ' = ' + ' '.join(
                ('+' if t['coefficient'] == 1 else '-') + t['label'] for t in records),
            'nominal_mm':str(nominal) if nominal is not None else None,
            'minimum_mm':str(minimum), 'maximum_mm':str(maximum), 'tolerance_width_mm':str(maximum-minimum),
            'allowed_min_mm':str(allowed_low), 'allowed_max_mm':str(allowed_high),
            'lower_margin_mm':str(minimum-allowed_low), 'upper_margin_mm':str(allowed_high-maximum),
            'lower_excess_mm':str(max(Decimal(0), allowed_low-minimum)),
            'upper_excess_mm':str(max(Decimal(0), maximum-allowed_high)),
            'conformance':'within_limits' if contained else 'outside_limits' if disjoint else 'may_exceed_limits',
            'at_boundary':contained and (minimum == allowed_low or maximum == allowed_high),
            'terms':records, 'requirement_value':closing['value'], 'requirement_evidence':role_evidence,
            'source_page':page, 'view':view, 'evidence':evidence, 'closing_index':closing_index,
            'start':start, 'end':end, 'status':'calculated', 'needs_review':True,
            'assumptions':['一维刚性线性关系；无选择装配、相关性或额外约束时的极限组合',
                           '原文尺寸、单位、功能要求及端点对应关系尚需工程师复核'],
            'compliance':'not_certified'}
        return result


def validate_tolerance_chains(chains, dimensions, pages):
    """Atomic contract: invalid proposals yield no computed defect candidates."""
    if not isinstance(chains, list) or len(chains) > 100:
        return [], [], ['tolerance_chains 必须为不超过100条的数组']
    calculations, issues, errors, seen = [], [], [], set()
    for n, chain in enumerate(chains):
        try:
            result = calculate_chain(chain, dimensions, pages)
            identity = (result['closing_index'], tuple(sorted((t['dimension_index'],t['coefficient']) for t in result['terms'])))
            if identity in seen:
                raise ValueError('重复的公差尺寸链')
            seen.add(identity)
            calculations.append(result)
            if result['conformance'] != 'within_limits':
                outside = result['conformance'] == 'outside_limits'
                message = ('公差尺寸链全范围不满足要求' if outside else '公差累积存在可能超差的极限组合')
                message += '：封闭环范围 [%s, %s] mm，允许 [%s, %s] mm' % (
                    result['minimum_mm'], result['maximum_mm'], result['allowed_min_mm'], result['allowed_max_mm'])
                issues.append({'err_id':'ERR-01','type':'公差尺寸链累积超差','check_kind':'dimension_chain',
                    'rule_id':'tolerance-chain-worst-case','severity':'高','message':message,
                    'source_page':result['source_page'], 'location':result['view'],
                    'bbox':dimensions[result['closing_index']].get('bbox'),
                    'evidence':result['evidence'] + '；功能要求：' + result['requirement_evidence'] + '；组成环：' +
                               '；'.join(t['original_value'] for t in result['terms']),
                    'origin':'vlm_geometry+rule','status':'needs_review', 'chain':chain, 'calculation':result,
                    'suggestion':'核实尺寸链对应关系、设计要求及组成环公差分配；极限组合不代表每件实物都超差，不自动改值。'})
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            errors.append('tolerance_chain %d: %s' % (n,exc))
    if errors:
        return [], [], errors
    return calculations, issues, []


def discover_tolerance_chains(dimensions, pages):
    """Resolve unique paths from already-extracted endpoints, without value fitting.

    Requires an explicit shared assembly scope (or shared part/view scope). The
    graph uses only page, direction and endpoint projections, NEVER dimensions'
    nominal values. Multiple valid paths are ambiguous, not a chance to choose
    whichever produces a desired answer. Missing tolerance remains unknown.
    """
    from .dimension_chains import _linear_interval
    closings=[(i,d) for i,d in enumerate(dimensions) if isinstance(d,dict) and d.get('dimension_role')=='closing_requirement']
    if not closings:
        return {'resolution':'needs_model','tolerance_status':'uncertain','tolerance_evidence':'没有可追溯的封闭环功能要求，不能据此认为无问题。',
                'tolerance_chains':[],'issues':[],'unresolved_chains':[]}
    calculations,issues,unresolved=[],[],[]
    insufficient_scope=False
    for closing_index, closing in closings:
        try:
            scope=closing.get('assembly_scope') or closing.get('part_id')
            if not isinstance(scope,str) or not scope.strip():
                insufficient_scope=True
                raise ValueError('缺少明确装配分区，无法唯一关联组成尺寸')
            axis,left,right=_linear_interval(closing)
            entries=[]
            for index,d in enumerate(dimensions):
                if index==closing_index or not isinstance(d,dict) or d.get('dimension_role')!='component':
                    continue
                if (d.get('source_page'),d.get('view'),d.get('assembly_scope') or d.get('part_id')) != (closing.get('source_page'),closing.get('view'),scope):
                    continue
                try:
                    direction,lo,hi=_linear_interval(d)
                    # This filter recognizes length syntax, not tolerance limits.
                    # A missing tolerance must still be part of the graph.
                    parsed=parse_size(d.get('value'),d.get('unit') or '')
                except (ValueError,TypeError,AttributeError):
                    continue
                if direction==axis and parsed['kind']=='linear' and not parsed['band']:
                    entries.append((index,lo,hi))
            if len(entries)>1000:
                raise ValueError('同分区候选超过1000个，需缩小范围后复核')
            coords=sorted([left,right]+[v for _,lo,hi in entries for v in (lo,hi)])
            epsilon=min(.003,(coords[-1]-coords[0])*.01)
            clusters=[]
            for coordinate in coords:
                if not clusters or coordinate-clusters[-1][0]>epsilon:
                    clusters.append([coordinate])
                else:
                    clusters[-1].append(coordinate)
            def node(position):
                # Exact membership in a complete-link cluster; no transitive
                # snapping that could bridge an actual missing segment.
                return next(n for n,cluster in enumerate(clusters) if position in cluster)
            start,end=node(left),node(right)
            graph={i:[] for i in range(len(clusters))}
            for index,lo,hi in entries:
                a,b=node(lo),node(hi)
                if a!=b:
                    graph[a].append((b,index,1))
                    graph[b].append((a,index,-1))
            paths=[]
            # Iterative DFS, bounded independently of Python recursion limits.
            pending=[(start,[],{start})]
            expansions=0
            while pending and len(paths)<2:
                cursor,path,visited=pending.pop()
                expansions+=1
                if expansions>5000:
                    raise ValueError('端点图存在过多候选路径，需人工确定装配关系')
                if cursor==end:
                    if path:paths.append(path)
                    continue
                if len(path)>=100:continue
                for neighbor,index,sign in graph[cursor]:
                    if neighbor not in visited:
                        pending.append((neighbor,path+[{'dimension_index':index,'coefficient':sign,
                            'start':'E%d'%cursor,'end':'E%d'%neighbor}],visited|{neighbor}))
            if not paths:
                raise ValueError('同分区尺寸端点没有连接封闭环两界面的连续组成路径')
            if len(paths)>1:
                raise ValueError('同分区有多个端点路径，不能依据数值挑选尺寸链')
            if len(paths[0])<2:
                raise ValueError('只有一个组成尺寸，未形成至少两个组成环的公差累积链')
            chain={'closing_index':closing_index,'start':'E%d'%start,'end':'E%d'%end,
                'source_page':closing.get('source_page'),'view':closing.get('view'), 'terms':paths[0],
                'evidence':'同一装配分区 %s 的独立尺寸端点投影构成唯一连续路径；功能要求：%s'%(scope,closing.get('role_evidence') or '')}
            computed,found,errors=validate_tolerance_chains([chain],dimensions,pages)
            if errors:raise ValueError('；'.join(errors))
            for c in computed:c['path_source']='deterministic_endpoint_graph'
            calculations.extend(computed)
            issues.extend(found)
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            unresolved.append({'closing_index':closing_index,'source_page':closing.get('source_page'),
                'view':closing.get('view'),'status':'uncertain','reason':str(exc),'requirement_value':closing.get('value')})
    status='uncertain' if unresolved else 'checked'
    evidence='程序按独立提取的端点及装配分区解析：已计算%d条，待核实%d条；不代表全图完整审查。'%(len(calculations),len(unresolved))
    return {'resolution':'needs_model' if insufficient_scope and not calculations else 'resolved',
            'tolerance_status':status,'tolerance_evidence':evidence,'tolerance_chains':calculations,
            'issues':issues,'unresolved_chains':unresolved}
