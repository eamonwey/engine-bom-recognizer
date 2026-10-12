import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine_bom import webapp
from engine_bom.assembly import infer_assembly, validate_tree, reconcile_quantities
from engine_bom.providers import ProviderError
from engine_bom.evaluation.tree_metrics import evaluate_assembly_case, render_hierarchy_report
from tests.test_assembly_reconcile_loop import (ScriptedProvider, occurrence, _payload,
                                               _tree_h04, _comps_h04, CFG)


class AssemblyRetryRegressions(unittest.TestCase):
    def test_ambiguous_shift_rejected_without_mutating_input(self):
        nodes = [occurrence('B-root', 1), occurrence('bad-child', 3, 'B-root', 1)]
        original = copy.deepcopy(nodes)
        with self.assertRaises(ValueError):
            validate_tree({'nodes': nodes}, [{}, {}, {}])
        self.assertEqual(nodes, original)

    def test_deleted_downgraded_and_unknown_usage_cannot_hide_conflict(self):
        for mode in ('delete', 'uncertain', 'unknown', 'changed_usage', 'wrong_parent'):
            with self.subTest(mode=mode):
                full = _tree_h04()
                candidate = copy.deepcopy(full)
                if mode == 'delete':
                    candidate.pop()
                elif mode == 'uncertain':
                    candidate[-1]['relation_status'] = 'uncertain'
                elif mode == 'unknown':
                    candidate[-1]['quantity_per_parent'] = None
                elif mode == 'changed_usage':
                    candidate[-1]['quantity_per_parent'] = 11 / 3
                else:
                    candidate[-1].update(parent_id='root', parent_component_index=0)
                result = infer_assembly(ScriptedProvider([_payload(full), _payload(candidate)]),
                                        [object()], _comps_h04(), CFG)
                self.assertEqual(len(result['nodes']), 4)
                self.assertEqual(result['quantity_conflicts'][0]['exploded_quantity'], 12)
                self.assertEqual(result['inference_status'], 'needs_review')
                self.assertEqual(result['unresolved_component_indices'], [])

    def test_node_id_rename_does_not_lose_valid_evidence(self):
        full = _tree_h04()
        renamed = copy.deepcopy(full)
        for n in renamed:
            n['id'] = 'new-' + n['id']
            if n['parent_id'] is not None:
                n['parent_id'] = 'new-' + n['parent_id']
        result = infer_assembly(ScriptedProvider([_payload(full), _payload(renamed)]),
                                [object()], _comps_h04(), CFG)
        self.assertEqual(result['inference_status'], 'validated')
        self.assertEqual(len(result['quantity_conflicts']), 1)

    def test_underprinted_quantity_keeps_full_tree(self):
        comps = [{'quantity': 1}, {'quantity': 2}]
        nodes = [occurrence('r', 0), occurrence('b', 1, 'r', 0, 3)]
        result = infer_assembly(ScriptedProvider([_payload(nodes)]), [object()], comps, CFG)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['quantity_conflicts'][0]['printed_quantity'], 2)
        self.assertEqual(result['quantity_conflicts'][0]['exploded_quantity'], 3)

    def test_retry_provider_error_keeps_tree_and_events(self):
        class Failing(ScriptedProvider):
            def analyze(self, images, prompt):
                if self.calls:
                    raise ProviderError('simulated timeout')
                return super().analyze(images, prompt)
        result = infer_assembly(Failing([_payload(_tree_h04())]), [object()], _comps_h04(), CFG)
        self.assertEqual(len(result['nodes']), 4)
        self.assertEqual(len(result['quantity_conflicts']), 1)
        self.assertEqual(result['inference_status'], 'provider_failed')
        self.assertEqual([e['action'] for e in result['events']], ['extract_validate', 'provider_error'])

    def test_initial_provider_error_has_no_fabricated_tree(self):
        provider = ScriptedProvider([])
        with patch.object(provider, 'analyze', side_effect=ProviderError('offline')):
            result = infer_assembly(provider, [object()], _comps_h04(), CFG)
        self.assertEqual(result['nodes'], [])
        self.assertEqual(len(result['events']), 1)


class QuantitySaveRegressions(unittest.TestCase):
    def test_save_reconciles_and_clears_only_assembly_findings(self):
        with tempfile.TemporaryDirectory() as folder:
            comps = [{'part_number': 'BASE', 'quantity': 1}, {'part_number': 'BOLT', 'quantity': 2}]
            nodes = [occurrence('r', 0), occurrence('b', 1, 'r', 0, 3)]
            job = {'kind': 'bom', 'status': 'done', 'dir': folder, 'result': {'document_id': 'test',
                'bom': {'components': comps, 'validation_issues': ['Other finding']}}}
            handler = object.__new__(webapp.Handler)
            replies = []
            handler._json = lambda data, *a, **k: replies.append(data)
            handler._read_json_body = lambda: {'job_id': 'j', 'reviewer': 'test', 'assembly': {'nodes': nodes}}
            with patch.object(webapp, '_jobs', {'j': job}), patch.object(webapp, 'DATA_DIR', folder), patch.object(webapp, 'REVIEWLOG_PATH', str(Path(folder, 'log.json'))):
                handler._api_assembly_save()
                self.assertEqual(replies[-1]['assembly']['status'], 'reviewed_with_conflicts')
                self.assertEqual(len(replies[-1]['assembly']['quantity_conflicts']), 1)
                self.assertEqual(len(replies[-1]['validation_issues']), 2)
                nodes[1]['quantity_per_parent'] = 2
                handler._api_assembly_save()
                self.assertEqual(replies[-1]['assembly']['quantity_status'], 'consistent')
                self.assertEqual(replies[-1]['assembly']['quantity_conflicts'], [])
                self.assertEqual(replies[-1]['validation_issues'], ['Other finding'])
                persisted = json.loads(Path(folder, 'result.json').read_text(encoding='utf-8'))
                self.assertEqual(persisted, job['result'])
                nodes[1]['quantity_per_parent'] = None
                handler._api_assembly_save()
                self.assertEqual(replies[-1]['assembly']['quantity_status'], 'incomplete')


class MetricRegressions(unittest.TestCase):
    def setUp(self):
        self.comps = [{'part_number': p} for p in ('A', 'B', 'C')]
        self.nodes = [occurrence('r', 0), occurrence('b', 1, 'r', 0, 2), occurrence('c', 2, 'r', 0, 3)]
        self.expected = {'case_id': 'case', 'components': self.comps, 'assembly': {'nodes': self.nodes},
                         'expected_node_count': 3, 'max_depth': 2}

    def score(self, nodes, **extra):
        return evaluate_assembly_case(dict(nodes=nodes, max_depth=2, inference_status='validated', **extra),
                                      self.comps, self.expected)

    def test_unknown_and_missing_edge_quantities_count_as_wrong(self):
        for mode in ('unknown', 'missing'):
            nodes = copy.deepcopy(self.nodes)
            if mode == 'unknown':
                nodes[-1]['quantity_per_parent'] = None
            else:
                nodes.pop()
            result = self.score(nodes)
            self.assertEqual(result['relations']['qty_total'], 2)
            self.assertEqual(result['relations']['qty_accuracy'], 0.5)
            self.assertEqual(result['acceptance_status'], 'failed')
            self.assertNotIn('全部通过', render_hierarchy_report([result]))

    def test_duplicate_edge_quantities_match_without_sort_shift(self):
        self.nodes[-1]['component_index'] = 1
        nodes = copy.deepcopy(self.nodes)
        nodes[1]['quantity_per_parent'] = None
        result = self.score(nodes)
        self.assertEqual(result['relations']['qty_correct'], 1)
        self.assertEqual(result['relations']['qty_total'], 2)

    def test_extra_root_fails_even_with_perfect_edge_f1(self):
        result = self.score(self.nodes + [occurrence('extra', 1)])
        self.assertEqual(result['relations']['f1'], 1.0)
        self.assertEqual(result['acceptance_status'], 'failed')
        self.assertNotIn('全部通过', render_hierarchy_report([result]))

    def test_depth_and_unverified_nodes_fail_acceptance(self):
        result = self.score(self.nodes, unverified_nodes=[{'id': 'candidate'}])
        self.assertEqual(result['acceptance_status'], 'failed')
        self.expected['max_depth'] = 3
        result = self.score(self.nodes)
        self.assertEqual(result['acceptance_status'], 'failed')

    def test_perfect_case_passes(self):
        result = self.score(self.nodes)
        self.assertEqual(result['acceptance_status'], 'passed')
        self.assertEqual(result['relations']['qty_accuracy'], 1.0)
        self.assertIn('全部通过', render_hierarchy_report([result]))


if __name__ == '__main__':
    unittest.main()
