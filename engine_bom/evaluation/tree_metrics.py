# -*- coding: utf-8 -*-
"""装配树（父子关系）评测指标。

比较口径与 data/acceptance/assembly_hierarchy_20260926 的统一判定一致：
  * 节点 ID 不参与比较；关系边以（父件键, 子件键）多元重集表示，键默认取件号
    （无件号时退回名称），STEP 结构树等来源可直接传产品名；
  * 关系边 P/R/F1 是主要指标；用量准确率分母包含全部已标注用量，未知或漏边计错；
  * 根节点单独比较多重集，不参与父子边 F1，但参与最终验收判定；
  * 未通过视觉证据校验的 unverified_nodes 不计入已确认关系，单独报告；
  * unresolved_component_indices 是应建关系但未建的 BOM 行，计入关系召回缺口。
"""
from collections import Counter
from typing import Any, Dict, List, Optional


def _default_key(comp: Dict[str, Any]) -> str:
    return str(comp.get("part_number") or comp.get("name_zh")
               or comp.get("name_en") or "?")


def tree_edges(nodes: List[Dict[str, Any]], components: List[Dict[str, Any]],
               key_of=None) -> Dict[str, Any]:
    """validate_tree 结构的 nodes → 边实例。

    返回 {"relations": Counter[(父键, 子键)], "qtys": {(父键, 子键): [用量,...]},
          "root_keys": [顶层键,...], "node_count": int}
    """
    key_of = key_of or _default_key
    keys = {}
    for idx, comp in enumerate(components):
        keys[idx] = key_of(comp)
    relations: Counter = Counter()
    qtys: Dict[Any, List] = {}
    root_keys = []
    for node in nodes:
        child = keys.get(node.get("component_index"), "?")
        parent_ref = node.get("parent_id")
        if parent_ref is None:
            root_keys.append(child)
            continue
        parent = keys.get(node.get("parent_component_index"), None)
        if parent is None and isinstance(parent_ref, str):
            # parent_component_index 缺失时按 id 反查
            for other in nodes:
                if other.get("id") == parent_ref:
                    parent = keys.get(other.get("component_index"), None)
                    break
        relations[(parent, child)] += 1
        qtys.setdefault((parent, child), []).append(node.get("quantity_per_parent"))
    return {"relations": relations, "qtys": qtys,
            "root_keys": root_keys, "node_count": len(nodes)}


def nested_to_edges(tree: Dict[str, Any]) -> Dict[str, Any]:
    """{name, qty, children:[...]} 嵌套树（step_tree.py / Fusion360 风格）→ 边实例。

    qty 语义为"每一个父件所需的子件数量"，与 quantity_per_parent 一致。
    """
    relations: Counter = Counter()
    qtys: Dict[Any, List] = {}
    root_keys = []

    def walk(node, parent_key, is_root):
        name = str(node.get("name") or "?")
        if is_root:
            root_keys.append(name)
        for child in node.get("children") or []:
            cname = str(child.get("name") or "?")
            qty = child.get("qty") if child.get("qty") is not None else 1
            relations[(name, cname)] += 1  # 根的子边与 tree_edges 口径一致: 父=根键
            qtys.setdefault((name, cname), []).append(qty)
            walk(child, name, False)

    if isinstance(tree, list):
        for sub in tree:
            walk(sub, None, True)
    else:
        walk(tree, None, True)
    return {"relations": relations, "qtys": qtys,
            "root_keys": root_keys, "node_count": sum(relations.values()) + len(root_keys)}


def compare_edges(gt: Dict[str, Any], pred: Dict[str, Any]) -> Dict[str, Any]:
    """关系边 P/R/F1 + 全部标注边用量准确率（未知、漏边均计入分母）。"""
    gt_rel, pred_rel = gt["relations"], pred["relations"]
    n_gt = sum(gt_rel.values())
    n_pred = sum(pred_rel.values())
    common = gt_rel & pred_rel
    n_hit = sum(common.values())
    precision = n_hit / n_pred if n_pred else 0.0
    recall = n_hit / n_gt if n_gt else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    qty_total = qty_ok = 0
    qty_mistakes = []
    for rel in gt_rel:
        gts = Counter(q for q in gt['qtys'].get(rel, []) if q is not None)
        preds = Counter(q for q in pred['qtys'].get(rel, []) if q is not None)
        correct = min(sum((gts & preds).values()), common[rel])
        total = sum(gts.values())
        qty_total += total
        qty_ok += correct
        if correct < total:
            qty_mistakes.append('%s → %s: %d/%d 项用量正确（未知或漏边计错）；预测=%s 标注=%s'
                                % (rel[0], rel[1], correct, total,
                                   pred['qtys'].get(rel, []), gt['qtys'].get(rel, [])))
    return {
        "n_gt": n_gt, "n_pred": n_pred, "n_hit": n_hit,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "qty_total": qty_total, "qty_correct": qty_ok,
        "qty_accuracy": round(qty_ok / qty_total, 4) if qty_total else None,
        "qty_mistakes": qty_mistakes,
        "missing": ["%s → %s ×%d" % (p, c, n) for (p, c), n in (gt_rel - pred_rel).items()],
        "extra": ["%s → %s ×%d" % (p, c, n) for (p, c), n in (pred_rel - gt_rel).items()],
        "gt_roots": sorted(map(str, gt["root_keys"])),
        "pred_roots": sorted(map(str, pred["root_keys"])),
    }


def evaluate_assembly_case(pred_tree: Dict[str, Any], pred_components: List[Dict[str, Any]],
                           expected: Dict[str, Any], key_of=None) -> Dict[str, Any]:
    """单用例评测：系统装配树输出 vs 验收包 expected.json。"""
    gt_tree = expected.get("assembly") or {}
    gt_comp = expected.get("components") or []
    edges = compare_edges(
        tree_edges(gt_tree.get("nodes") or [], gt_comp + gt_tree.get('context_components', []), key_of),
        tree_edges(pred_tree.get("nodes") or [], pred_components + pred_tree.get('context_components', []), key_of))

    unresolved = sorted(pred_tree.get("unresolved_component_indices") or [])
    n_unverified = len(pred_tree.get("unverified_nodes") or [])
    pred_nodes = pred_tree.get("nodes") or []
    n_roots = sum(1 for n in pred_nodes if n.get("parent_id") is None)
    node_total = edges["n_pred"] + n_roots + n_unverified

    exp_pn = Counter(str(c.get("part_number") or "") for c in gt_comp)
    got_pn = Counter(str(c.get("part_number") or "") for c in pred_components)
    bom_missing = list((exp_pn - got_pn).elements())
    bom_extra = list((got_pn - exp_pn).elements())

    findings_hit = None
    expected_findings = expected.get("expected_findings") or []
    if expected_findings:
        text = " ".join(pred_tree.get("_validation_issues") or [])
        findings_hit = [f for f in expected_findings
                        if str(f.get("err_id")) in text
                        and str(f.get("part_number")) in text]

    result = {
        "case_id": expected.get("case_id"),
        "relations": edges,
        "expected_node_count": expected.get("expected_node_count"),
        "node_count_confirmed": edges["n_pred"] + n_roots,
        "node_count_unverified": n_unverified,
        "node_count_total": node_total,
        "expected_max_depth": expected.get("max_depth"),
        "max_depth": pred_tree.get("max_depth"),
        "unresolved_component_indices": unresolved,
        "bom_rows_expected": len(gt_comp),
        "bom_rows_predicted": len(pred_components),
        "bom_missing": bom_missing,
        "bom_extra": bom_extra,
        "expected_findings": expected_findings,
        "findings_hit": findings_hit,
        "inference_status": pred_tree.get("inference_status"),
    }
    result['acceptance_issues'] = acceptance_issues(result)
    result['acceptance_status'] = 'failed' if result['acceptance_issues'] else 'passed'
    return result


def acceptance_issues(r):
    """One decision shared by machine-readable scores and the human report."""
    issues = []
    e = r.get('relations') or {}
    if r.get('pipeline_error'):
        issues.append('流水线失败: %s' % r['pipeline_error'])
    if not e:
        issues.append('缺少关系评测结果')
    for key, label in [('missing', '漏掉的父子关系'), ('extra', '多出的父子关系'),
                       ('qty_mistakes', '用量错误')]:
        if e.get(key):
            issues.append(label + ': ' + '; '.join(e[key]))
    if e and e.get('gt_roots') != e.get('pred_roots'):
        issues.append('根节点不一致: 预测=%s，标注=%s' % (e.get('pred_roots'), e.get('gt_roots')))
    for actual, expected, label in [('node_count_confirmed', 'expected_node_count', '节点数'),
                                    ('max_depth', 'expected_max_depth', '最大深度')]:
        if r.get(expected) is not None and r.get(actual) != r[expected]:
            issues.append('%s不一致: 预测=%s，标注=%s' % (label, r.get(actual), r[expected]))
    for key, label in [('unresolved_component_indices', '未建立关系的 BOM 行'),
                       ('node_count_unverified', '待核实节点'), ('bom_missing', 'BOM 缺行'),
                       ('bom_extra', 'BOM 多行')]:
        if r.get(key):
            issues.append('%s: %s' % (label, r[key]))
    missing_findings = [f for f in r.get('expected_findings', []) if f not in (r.get('findings_hit') or [])]
    if missing_findings:
        issues.append('预期图纸问题未检出: %s' % missing_findings)
    if r.get('inference_status') not in (None, 'validated'):
        issues.append('装配推理状态: %s' % r['inference_status'])
    return issues


def render_hierarchy_report(results: List[Dict[str, Any]], meta: Optional[Dict] = None) -> str:
    lines = ["# 装配父子关系验收报告", ""]
    lines += ['用量准确率以全部已标注用量为分母，未知用量和漏掉的关系计错。根节点、节点数、深度与待核实项单独参与验收。', '']
    if meta:
        for k, v in meta.items():
            lines.append("- %s: %s" % (k, v))
        lines.append("")
    lines.append("| 用例 | 关系P | 关系R | 关系F1 | 用量准确率 | 节点(确认/待核/期望) | 深度(实际/期望) | 未建关系行 | BOM行(实际/期望) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        e = r.get("relations") or {}
        if not e:
            lines.append("| %s | - | - | - | - | - | - | - | - |" % r.get("case_id"))
            continue
        lines.append("| %s | %s | %s | %s | %s | %d/%d/%s | %s/%s | %d %s | %d/%d |" % (
            r.get("case_id"), e["precision"], e["recall"], e["f1"],
            e["qty_accuracy"] if e["qty_accuracy"] is not None else "-",
            r["node_count_confirmed"], r["node_count_unverified"], r["expected_node_count"],
            r["max_depth"], r["expected_max_depth"],
            len(r["unresolved_component_indices"]),
            r["unresolved_component_indices"] or "",
            r["bom_rows_predicted"], r["bom_rows_expected"]))
    lines.append("")
    for r in results:
        e = r.get("relations") or {}
        issues = acceptance_issues(r)
        lines.append("## %s" % r.get("case_id"))
        lines.append("")
        if issues:
            lines.extend("- " + i for i in issues)
        else:
            lines.append("- 全部通过")
        lines.append("")
    return "\n".join(lines)
