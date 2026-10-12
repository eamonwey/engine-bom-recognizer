import json
import unittest
from PIL import Image
from engine_bom.installation_review import verify_installation, review_images
from engine_bom.assembly import validate_tree
from engine_bom.providers.base import ProviderResponse, ProviderError
from tests.test_assembly_evidence import occurrence


def check(node, supported=True, parent=None, qty=None):
    return dict(id=node['id'], component_index=node['component_index'], supported=supported,
                parent_id=parent, quantity_per_parent=qty, source_page=1,
                view='A-A', feature='直接配合孔', evidence='A-A剖面显示直接配合')


class ReviewTests(unittest.TestCase):
    def test_uncertain_occurrence_can_be_corrected_in_visual_review(self):
        self.setUp()
        nodes=[dict(n) for n in self.nodes]
        nodes[-1]['relation_status']='uncertain'
        tree=validate_tree({'nodes':nodes},self.components,True)
        self.assertEqual(len(tree['unverified_nodes']),1)
        checks=[check(nodes[0]),check(nodes[1],parent='base',qty=1),
                check(nodes[2],parent='base',qty=1),check(nodes[3],parent='sleeve',qty=1)]
        result=verify_installation(self.model(checks),[object()],tree,self.components)
        self.assertEqual(next(n for n in result['nodes'] if n['id']=='plunger')['parent_id'],'sleeve')
        self.assertFalse(result['unverified_nodes'])

    def setUp(self):
        self.components = [{'quantity': 1}, {'quantity': 1}, {'quantity': 1}, {'quantity': 1}]
        self.nodes = [occurrence('base', 0), occurrence('sleeve', 1, 'base', 0),
                      occurrence('valve', 2, 'base', 0), occurrence('plunger', 3, 'valve', 2)]
        self.tree = validate_tree({'nodes': self.nodes}, self.components, True)

    def model(self, checks):
        class Model:
            def analyze(self, images, prompt):
                return ProviderResponse(json.dumps({'checks': checks}))
        return Model()

    def test_correct_wrong_attachment_from_visual_review(self):
        checks = [check(self.nodes[0]), check(self.nodes[1], parent='base', qty=1),
                  check(self.nodes[2], parent='base', qty=1), check(self.nodes[3], parent='sleeve', qty=1)]
        checks[-1].pop('supported')
        checks[-1]['decision'] = 'correct'
        result = verify_installation(self.model(checks), [object()], self.tree, self.components)
        plunger = next(n for n in result['nodes'] if n['id'] == 'plunger')
        self.assertEqual(plunger['parent_id'], 'sleeve')
        self.assertEqual(plunger['parent_component_index'], 1)
        self.assertIn('candidate_evidence', plunger)
        self.assertEqual(result['verification_status'], 'completed')

    def test_rejected_parent_does_not_promote_descendants(self):
        checks = [check(self.nodes[0]), check(self.nodes[1], parent='base', qty=1),
                  check(self.nodes[2], False), check(self.nodes[3], parent='valve', qty=1)]
        result = verify_installation(self.model(checks), [object()], self.tree, self.components)
        self.assertEqual([n['id'] for n in result['nodes']], ['base', 'sleeve'])
        self.assertEqual(result['unresolved_component_indices'], [2, 3])

    def test_failed_review_keeps_candidates_but_not_accepted_edges(self):
        class Broken:
            def analyze(self, *args):
                raise ProviderError('offline')
        result = verify_installation(Broken(), [object()], self.tree, self.components)
        self.assertEqual(result['nodes'], [])
        self.assertEqual(len(result['unverified_nodes']), 4)
        self.assertEqual(result['unresolved_component_indices'], [0, 1, 2, 3])

    def test_review_cannot_invent_root_or_change_identity(self):
        checks = [check(n) for n in self.nodes]
        result = verify_installation(self.model(checks), [object()], self.tree, self.components, attempts=1)
        self.assertEqual(result['nodes'], [])
        self.assertIn('安装根', result['verification_events'][0]['errors'][0])
        checks[0]['component_index'] = 1
        result = verify_installation(self.model(checks), [object()], self.tree, self.components, attempts=1)
        self.assertIn('索引', result['verification_events'][0]['errors'][0])

    def test_detail_crops_keep_page_numbers(self):
        images, note = review_images([Image.new('RGB', (100, 100))])
        self.assertEqual(len(images), 5)
        self.assertIn('裁切不是新页', note)

    def test_review_can_correct_quantity_by_evidence(self):
        self.components[2]['quantity'] = 2
        checks = [check(self.nodes[0]), check(self.nodes[1], parent='base', qty=1),
                  check(self.nodes[2], parent='base', qty=2), check(self.nodes[3], False)]
        result = verify_installation(self.model(checks), [object()], self.tree, self.components)
        self.assertEqual(next(n for n in result['nodes'] if n['id'] == 'valve')['quantity_per_parent'], 2)

    def test_candidate_quantity_conflict_is_not_drawing_verdict(self):
        from engine_bom.assembly import update_quantity_checks
        self.components[2]['quantity'] = 2
        bom = {'components': self.components, 'assembly': self.tree}
        update_quantity_checks(bom)
        self.assertEqual(bom['assembly']['quantity_basis'], 'candidate')
        self.assertTrue(bom['validation_issues'][0].startswith('装配候选数量待复核：'))
        for n in self.tree['nodes']:
            n['status'] = 'confirmed'
        update_quantity_checks(bom)
        self.assertTrue(bom['validation_issues'][0].startswith('ERR-08 数量不一致:'))

    def test_one_corrected_duplicate_branch_does_not_erase_other_verified_edges(self):
        from tests.test_gearbox_regressions import node
        components=[{'name_zh':n,'quantity':q} for n,q in [('箱体',1),('盖',1),('油封',2)]]
        nodes=[node('base',0,'箱体'),node('cover',1,'盖','base',0),
               node('seal1',2,'油封','cover',1),node('seal2',2,'油封','base',0)]
        tree=validate_tree({'nodes':nodes},components,True)
        checks=[check(nodes[0]),check(nodes[1],parent='base',qty=1),
                check(nodes[2],parent='cover',qty=1),check(nodes[3],parent='cover',qty=1)]
        result=verify_installation(self.model(checks),[object()],tree,components,attempts=1)
        self.assertEqual({n['id'] for n in result['nodes']},{'base','cover'})
        self.assertEqual({n['id'] for n in result['unverified_nodes']},{'seal1','seal2'})
        self.assertEqual(result['verification_status'],'partial')
