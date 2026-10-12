"""Offline, temporary-directory reproductions for the 2026-09-29 code review."""
import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine_bom import webapp
from engine_bom.assembly import infer_assembly, validate_tree, reconcile_quantities
from engine_bom.providers import ProviderError
from engine_bom.evaluation.tree_metrics import evaluate_assembly_case, render_hierarchy_report
from tests.test_assembly_reconcile_loop import (ScriptedProvider, occurrence, _payload,
    _tree_h04, _comps_h04, CFG)


def main():
    results = {}
    components = [{'part_number': p} for p in ('A', 'B', 'C')]
    nodes = [occurrence('B-root', 1), occurrence('bad-child', 3, 'B-root', 1)]
    try:
        tree = validate_tree({'nodes': nodes}, components)
        results['ambiguous_index_shift'] = {
            'supplied_root_index': 1, 'accepted_root_index': tree['nodes'][0]['component_index'],
            'accepted_root_part': components[tree['nodes'][0]['component_index']]['part_number']}
    except ValueError:
        results['ambiguous_index_shift'] = {'rejected': True, 'root_index_unchanged': nodes[0]['component_index'] == 1}

    full = _tree_h04()
    provider = ScriptedProvider([_payload(full), _payload(full[:-1])])
    tree = infer_assembly(provider, [object()], _comps_h04(), CFG)
    results['retry_deletes_conflicting_node'] = {'nodes': len(tree['nodes']),
        'conflicts': tree['quantity_conflicts'], 'status': tree['inference_status'],
        'unresolved': tree['unresolved_component_indices']}

    components = [{'part_number': 'BASE', 'quantity': 1}, {'part_number': 'BOLT', 'quantity': 2}]
    provider = ScriptedProvider([_payload([occurrence('r', 0), occurrence('b', 1, 'r', 0, 3)])])
    tree = infer_assembly(provider, [object()], components, CFG)
    results['printed_underquantity_rejects_evidence'] = {'nodes': len(tree['nodes']),
        'conflicts': tree.get('quantity_conflicts'), 'status': tree['inference_status'],
        'last_errors': tree['events'][-1]['errors']}

    class FailingRetry(ScriptedProvider):
        def analyze(self, images, prompt):
            if self.calls:
                raise ProviderError('simulated timeout')
            return super().analyze(images, prompt)
    tree = infer_assembly(FailingRetry([_payload(full)]), [object()], _comps_h04(), CFG)
    results['retry_api_failure_loses_stash'] = {'nodes': len(tree['nodes']),
        'events': len(tree['events']), 'status': tree['inference_status']}

    with tempfile.TemporaryDirectory() as directory:
        comps = _comps_h04()
        original = validate_tree({'nodes': copy.deepcopy(full)}, comps, True)
        original['quantity_conflicts'] = reconcile_quantities(original, comps)
        job = {'kind': 'bom', 'status': 'done', 'dir': directory,
               'result': {'document_id': 'review', 'bom': {'components': comps, 'assembly': original}}}
        handler = object.__new__(webapp.Handler)
        handler._json = lambda *a, **k: None
        handler._read_json_body = lambda: {'job_id': 'j', 'bom_revision': 0, 'reviewer': 'test',
                                            'assembly': {'nodes': copy.deepcopy(full)}}
        with patch.object(webapp, '_jobs', {'j': job}), patch.object(webapp, 'DATA_DIR', directory), patch.object(webapp, 'REVIEWLOG_PATH', str(Path(directory, 'log.json'))):
            handler._api_assembly_save()
        saved = job['result']['bom']['assembly']
        results['manual_save_drops_quantity_conflicts'] = {'before': len(original['quantity_conflicts']),
            'after': saved.get('quantity_conflicts'), 'status': saved['status'],
            'recomputed_conflicts': len(reconcile_quantities(saved, comps))}

    comps = [{'part_number': p} for p in ('A', 'B', 'C')]
    expected_nodes = [occurrence('r', 0), occurrence('b', 1, 'r', 0, 2), occurrence('c', 2, 'r', 0, 3)]
    expected = {'case_id': 'quantity', 'components': comps, 'assembly': {'nodes': expected_nodes},
                'expected_node_count': 3, 'max_depth': 2}
    predicted = copy.deepcopy(expected_nodes)
    predicted[2]['quantity_per_parent'] = None
    score = evaluate_assembly_case({'nodes': predicted, 'max_depth': 2, 'inference_status': 'validated'}, comps, expected)
    results['unknown_quantity_excluded'] = {'qty_accuracy': score['relations']['qty_accuracy'],
        'qty_total': score['relations']['qty_total'], 'report_says_all_pass': '全部通过' in render_hierarchy_report([score])}
    predicted = copy.deepcopy(expected_nodes) + [occurrence('extra-root', 1)]
    score = evaluate_assembly_case({'nodes': predicted, 'max_depth': 2, 'inference_status': 'validated'}, comps, expected)
    results['extra_root_all_pass'] = {'f1': score['relations']['f1'],
        'gt_roots': score['relations']['gt_roots'], 'pred_roots': score['relations']['pred_roots'],
        'expected_node_count': score['expected_node_count'], 'node_count': score['node_count_confirmed'],
        'report_says_all_pass': '全部通过' in render_hierarchy_report([score])}
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
