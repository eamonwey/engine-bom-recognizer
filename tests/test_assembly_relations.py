import copy
import json
from pathlib import Path
import unittest
from engine_bom.assembly_relations import parse_facts, build_tree
from engine_bom.assembly import infer_assembly, validate_tree, update_quantity_checks, assembly_rows
from engine_bom.evaluation.tree_metrics import evaluate_assembly_case
from engine_bom.providers import ProviderError
from tests.test_assembly_reconcile_loop import ScriptedProvider

PACK = Path(__file__).resolve().parents[1] / 'data/acceptance/assembly_hierarchy_20260926'


def fixture(case):
    expected = json.loads((PACK / (case + '.expected.json')).read_text(encoding='utf-8'))
    nodes = expected['assembly']['nodes']
    by_id = {n['id']: n for n in nodes}
    payload = {'roots': [], 'relations': []}
    for n in nodes:
        base = {'source_page': n['source_page'], 'evidence': n['evidence']}
        if n['parent_id'] is None:
            payload['roots'].append(dict(base, component_id='c%d' % n['component_index']))
        else:
            payload['relations'].append(dict(base, parent='c%d' % by_id[n['parent_id']]['component_index'],
                child='c%d' % n['component_index'], quantity_per_parent=n['quantity_per_parent'], kind='explicit_contains'))
    facts = parse_facts(payload, expected['components'], 1)
    checks = [dict(id=f['id'], supported=True, source_page=1, evidence=f['evidence'],
                   quantity_per_parent=f.get('quantity_per_parent')) for f in facts]
    return expected, payload, facts, checks


class RelationTests(unittest.TestCase):
    def test_title_block_root_does_not_add_bom_rows(self):
        components = [{'part_number': 'P1', 'quantity': 4}]
        payload = {'roots': [{'component_id': 'd0', 'part_number': 'A0', 'name_zh': '总成',
                    'quantity': 1, 'source_page': 1, 'evidence': 'A0 每1套本图装配体'}],
                   'relations': [{'parent': 'd0', 'child': 'c0', 'quantity_per_parent': 4,
                    'kind': 'explicit_contains', 'source_page': 1, 'evidence': '明细 P1 4'}]}
        facts = parse_facts(payload, components, 1)
        checks = [dict(id=f['id'], supported=True, evidence=f['evidence'], source_page=1,
                       quantity_per_parent=f.get('quantity_per_parent')) for f in facts]
        tree = build_tree(facts, checks, components)
        self.assertEqual(tree['component_refs'], {'c0': 0, 'd0': 1})
        self.assertEqual(tree['nodes'][0]['component_index'], 1)
        self.assertEqual(tree['unresolved_component_indices'], [])
        self.assertEqual(len(components), 1)
        self.assertTrue(assembly_rows(tree, components))
        self.assertEqual(len(validate_tree(tree, components)['nodes']), 2)
        bom = {'components': components, 'assembly': tree}
        update_quantity_checks(bom)
        self.assertEqual(tree['quantity_status'], 'consistent')
        tree['context_components'][0]['quantity'] = None
        update_quantity_checks(bom)
        self.assertEqual(tree['quantity_status'], 'incomplete')

    def test_title_root_requires_source_and_cannot_duplicate_existing_row(self):
        for root in ({'component_id': 'd0', 'part_number': 'P1', 'source_page': 1, 'evidence': '图号P1'},
                     {'component_id': 'd0', 'part_number': 'A0', 'source_page': 1, 'evidence': ''}):
            with self.assertRaises(ValueError):
                parse_facts({'roots': [root], 'relations': []}, [{'part_number': 'P1'}], 1)

    def test_root_metadata_survives_reference_only_relation_response(self):
        root = {'component_id': 'd0', 'part_number': 'A0', 'quantity': 1,
                'source_page': 1, 'evidence': '标题A0每套'}
        relation = {'parent': 'd0', 'child': 'c0', 'quantity_per_parent': 2,
                    'kind': 'explicit_contains', 'source_page': 1, 'evidence': '明细P1数量2'}
        provider = ScriptedProvider([
            json.dumps({'roots': [root], 'relations': []}),
            json.dumps({'roots': [{'component_id': 'd0'}], 'relations': [relation]}),
            json.dumps({'checks': [{'id': 'r0', 'supported': True, 'source_page': 1, 'evidence': '标题A0'},
                                  {'id': 'e0', 'supported': True, 'source_page': 1, 'evidence': '明细P1数量2', 'quantity_per_parent': 2}]})])
        tree = infer_assembly(provider, [object()], [{'part_number': 'P1', 'quantity': 2}], {'method': 'relations'})
        self.assertEqual(tree['inference_status'], 'validated')
        self.assertEqual(tree['context_components'][0]['part_number'], 'A0')
        self.assertEqual(len(tree['nodes']), 2)

    def test_no_root_evidence_does_not_trigger_guessed_hierarchy(self):
        provider = ScriptedProvider([json.dumps({'roots': [], 'relations': []})])
        tree = infer_assembly(provider, [object()], [{'part_number': 'P1'}], {'method': 'relations'})
        self.assertEqual(tree['inference_status'], 'needs_review')
        self.assertEqual(tree['nodes'], [])
        self.assertEqual(provider.calls, 1)

    def test_known_hierarchy_and_shared_occurrences(self):
        for case in ('H01', 'H02', 'H03', 'H04'):
            with self.subTest(case=case):
                expected, _, facts, checks = fixture(case)
                tree = build_tree(facts, checks, expected['components'])
                score = evaluate_assembly_case(tree, expected['components'], expected)
                self.assertEqual(score['relations']['f1'], 1)
                self.assertEqual(score['relations']['qty_accuracy'], 1)
                self.assertEqual(len(tree['nodes']), expected['expected_node_count'])
                if case == 'H04':
                    self.assertEqual(tree['quantity_conflicts'][0]['printed_quantity'], 11)

    def test_real_entrypoint_runs_extraction_then_independent_review(self):
        expected, payload, _, checks = fixture('H03')
        provider = ScriptedProvider([json.dumps(dict(roots=payload['roots'], relations=[])), json.dumps(payload), json.dumps({'checks': checks})])
        tree = infer_assembly(provider, [object()], expected['components'], {'method': 'relations'})
        self.assertEqual(provider.calls, 3)
        self.assertEqual([e['stage'] for e in tree['events']], ['root', 'relations', 'verify'])
        self.assertEqual(evaluate_assembly_case(tree, expected['components'], expected)['relations']['f1'], 1)

    def test_installation_does_not_become_containment(self):
        expected, _, facts, checks = fixture('H01')
        facts[1]['kind'] = 'installation_only'
        tree = build_tree(facts, checks, expected['components'])
        self.assertTrue(tree['unresolved_relations'])
        self.assertIn(int(facts[1]['child'][1:]), tree['unresolved_component_indices'])

    def test_disagreeing_or_missing_verification_is_not_accepted(self):
        expected, _, facts, checks = fixture('H01')
        checks[1]['quantity_per_parent'] = 99
        checks.pop()
        tree = build_tree(facts, checks, expected['components'])
        self.assertEqual(len(tree['unresolved_relations']), 2)

    def test_root_is_not_invented_from_first_row(self):
        expected, _, facts, checks = fixture('H03')
        tree = build_tree([f for f in facts if f['kind'] != 'root'], checks, expected['components'])
        self.assertEqual(tree['nodes'], [])
        self.assertEqual(len(tree['unresolved_relations']), 6)

    def test_conflicting_usage_is_not_summed_or_silently_selected(self):
        expected, _, facts, checks = fixture('H01')
        extra = dict(facts[1], id='e99', quantity_per_parent=99)
        tree = build_tree(facts + [extra], checks + [dict(checks[1], id='e99', quantity_per_parent=99)], expected['components'])
        self.assertEqual(len(tree['unresolved_relations']), 2)

    def test_cycles_are_not_unfolded_forever(self):
        expected, _, facts, checks = fixture('H03')
        extra = dict(facts[1], id='e99', parent=facts[1]['child'], child=facts[1]['parent'])
        tree = build_tree(facts + [extra], checks + [dict(checks[1], id='e99')], expected['components'])
        self.assertEqual(tree['nodes'], [])
        self.assertTrue(tree['unresolved_relations'])

    def test_verification_failure_preserves_candidates_not_false_relations(self):
        expected, payload, facts, _ = fixture('H03')
        class Broken(ScriptedProvider):
            def analyze(self, images, prompt):
                if self.calls >= 2:
                    raise ProviderError('offline')
                return super().analyze(images, prompt)
        tree = infer_assembly(Broken([json.dumps(dict(roots=payload['roots'], relations=[])), json.dumps(payload)]), [object()], expected['components'], {'method': 'relations'})
        self.assertEqual(len(tree['relation_candidates']), len(facts))
        self.assertEqual(tree['nodes'], [])
        self.assertEqual(tree['inference_status'], 'provider_failed')

    def test_bad_component_ids_and_pages_rejected_without_mutation(self):
        expected, payload, _, _ = fixture('H01')
        payload['relations'][0]['child'] = 'c999'
        snapshot = copy.deepcopy(payload)
        with self.assertRaises(ValueError):
            parse_facts(payload, expected['components'], 1)
        self.assertEqual(payload, snapshot)


if __name__ == '__main__':
    unittest.main()
