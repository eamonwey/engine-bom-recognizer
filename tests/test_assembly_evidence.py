import json
import unittest

from engine_bom.assembly import infer_assembly, validate_tree
from engine_bom.providers.base import ProviderResponse


def occurrence(key, index, parent=None, parent_index=None):
    return dict(id=key, component_index=index, parent_id=parent,
                parent_component_index=parent_index, source_page=1,
                quantity_per_parent=None if parent is None else 1,
                evidence='A-A剖面显示内圈与轴颈配合', relation_status='supported',
                visual_evidence=dict(kind='attachment' if parent else 'installation_base',
                                     view='A-A', feature='内圈与轴颈配合或基体支承座'))


class AssemblyEvidenceTests(unittest.TestCase):
    def test_name_cannot_point_to_another_bom_row(self):
        node = occurrence('shaft', 0)
        node['component_name'] = '轴'
        with self.assertRaisesRegex(ValueError, '名称与索引'):
            validate_tree({'nodes': [node]}, [{'name_zh': '柱塞'}], True)

    def test_default_path_builds_installation_hierarchy(self):
        from engine_bom.config import DEFAULT_CONFIG
        from engine_bom.assembly import reconcile_quantities
        nodes = [occurrence('body', 0), occurrence('valve', 1, 'body', 0),
                 occurrence('ball', 2, 'valve', 1)]
        nodes[1]['quantity_per_parent'] = 2
        class Model:
            name = 'real'
            def analyze(self, images, prompt):
                if prompt.startswith('TASK:INSTALLATION_VERIFY'):
                    return ProviderResponse(json.dumps({'checks': [dict(id=n['id'], component_index=n['component_index'], supported=True,
                        parent_id=n['parent_id'], quantity_per_parent=n['quantity_per_parent'], source_page=1,
                        view='A-A', feature='配合孔', evidence='A-A剖面显示配合孔') for n in nodes]}))
                assert 'TASK:ASSEMBLY\n' in prompt
                return ProviderResponse(json.dumps({'nodes': nodes}))
        components = [{'quantity': 1}, {'quantity': 2}, {'quantity': 2}]
        tree = infer_assembly(Model(), [object()], components, DEFAULT_CONFIG['assembly'])
        self.assertEqual(tree['relation_semantics'], 'installation')
        self.assertEqual(tree['max_depth'], 3)
        self.assertEqual(tree['nodes'][2]['parent_id'], 'valve')
        self.assertEqual(reconcile_quantities(tree, components), [])

    def test_virtual_root_rejected(self):
        with self.assertRaises(ValueError):
            validate_tree({'nodes': [occurrence('assembly', None)]}, [{}])

    def test_parent_id_index_mismatch_rejected(self):
        nodes = [occurrence('shaft', 0), occurrence('ring', 1, 'shaft', 0),
                 occurrence('key', 2, 'ring', 0)]
        with self.assertRaisesRegex(ValueError, '父件索引'):
            validate_tree({'nodes': nodes}, [{}, {}, {}], True)

    def test_uncertain_branch_does_not_erase_supported_branch(self):
        nodes = [occurrence('base', 0), occurrence('shaft', 1, 'base', 0),
                 occurrence('bearing', 2, 'shaft', 1), occurrence('ring', 3, 'base', 0),
                 occurrence('child', 4, 'ring', 3)]
        nodes[3]['relation_status'] = 'uncertain'
        tree = validate_tree({'nodes': nodes}, [{}] * 5, True)
        self.assertEqual([n['id'] for n in tree['nodes']], ['base', 'shaft', 'bearing'])
        self.assertEqual(tree['unresolved_component_indices'], [3, 4])
        self.assertEqual(tree['max_depth'], 3)
        self.assertEqual(len(tree['unverified_nodes']), 2)

    def test_membership_prose_is_not_structured_visual_evidence(self):
        child = occurrence('child', 1, 'base', 0)
        child['evidence'] = '总装明细表第2项，数量1'
        del child['visual_evidence']
        tree = validate_tree({'nodes': [occurrence('base', 0), child]}, [{}, {}], True)
        self.assertEqual(tree['unresolved_component_indices'], [1])

    def test_unknown_root_not_promoted(self):
        root = occurrence('unknown', 0)
        root['relation_status'] = 'uncertain'
        tree = validate_tree({'nodes': [root]}, [{}], True)
        self.assertEqual(tree['nodes'], [])
        self.assertEqual(tree['unresolved_component_indices'], [0])

    def test_quantity_bound_and_unknown_quantity(self):
        nodes = [occurrence('base', 0), occurrence('bolt', 1, 'base', 0)]
        nodes[1]['quantity_per_parent'] = 3
        from engine_bom.assembly import reconcile_quantities
        components = [{'quantity': 1}, {'quantity': 2}]
        tree = validate_tree({'nodes': nodes}, components)
        self.assertEqual(reconcile_quantities(tree, components)[0]['exploded_quantity'], 3)
        nodes[1]['quantity_per_parent'] = None
        self.assertEqual(len(validate_tree({'nodes': nodes}, [{}, {'quantity': 2}])['nodes']), 2)

    def test_legacy_manual_tree_remains_compatible(self):
        root = occurrence('base', 0)
        del root['visual_evidence']
        del root['parent_component_index']
        self.assertEqual(len(validate_tree({'nodes': [root]}, [{}])['nodes']), 1)

    def test_inference_uses_gate_and_retains_review_evidence(self):
        class Model:
            name = 'real'

            def analyze(self, images, prompt):
                child = occurrence('child', 1, 'base', 0)
                child['relation_status'] = 'uncertain'
                return ProviderResponse(json.dumps({'nodes': [occurrence('base', 0), child]}))

        tree = infer_assembly(Model(), [object()], [{}, {}])
        self.assertEqual(tree['inference_status'], 'needs_review')
        self.assertEqual(tree['unresolved_component_indices'], [1])
        self.assertEqual(tree['unverified_nodes'][0]['id'], 'child')
