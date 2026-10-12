"""Regressions minimized from the four real gearbox detection records."""
import json
import unittest

from engine_bom.assembly import infer_assembly, validate_tree
from engine_bom.inspect_rules import check_dimensions, check_titleblock
from engine_bom.hybrid_inspection import gate_visual_chains
from engine_bom.providers.base import ProviderResponse


def node(key, index, name, parent=None, parent_index=None, feature='直接安装配合'):
    return dict(id=key, component_index=index, component_name=name, parent_id=parent,
                parent_component_index=parent_index, quantity_per_parent=1,
                relation_status='supported', source_page=1, evidence=feature,
                visual_evidence=dict(kind='attachment' if parent else 'installation_base', view='A-A', feature=feature))


class GearboxRegressions(unittest.TestCase):
    def test_semantic_tags_do_not_identify_same_feature(self):
        for tag, a, b in [('总高','174','178'), ('轴伸直径','Φ18h7','Φ24h7'),
                          ('键槽宽','6','8'), ('轴承座孔直径','Φ47H9/h9','Φ62J7')]:
            with self.subTest(tag=tag):
                self.assertEqual(check_dimensions([dict(part_id='ZD100-00',tag=tag,value=a,view='A'),
                                                   dict(part_id='ZD100-00',tag=tag,value=b,view='B')]), [])

    def test_same_feature_nominal_conflict_still_detected(self):
        dims=[dict(part_id='P1',feature_id='hole1',value='Φ60H9',bbox=[.1,.1,.2,.2],source_page=1),
              dict(part_id='P1',feature_id='hole1',value='Φ62H9',bbox=[.3,.3,.4,.4],source_page=1)]
        issues=check_dimensions(dims)
        self.assertEqual(len(issues),1)
        self.assertEqual(issues[0]['dimension_indices'],[0,1])

    def test_nominal_52_with_fit_and_without_fit_is_not_numeric_conflict(self):
        dims=[dict(part_id='P',feature_id='diameter',value=v) for v in ['Φ52h9','Φ52']]
        self.assertFalse(any(i['err_id']=='ERR-01' for i in check_dimensions(dims)))

    def test_assembly_material_flag_alone_is_not_applicability(self):
        self.assertFalse(any(i['err_id']=='ERR-06' for i in check_titleblock(
            dict(drawing_type='assembly', material='',material_applicable=True))))

    def test_cross_view_prose_cannot_bless_wrong_dimension_group(self):
        issue=dict(err_id='ERR-01',check_kind='cross_view',message='174与178总体高度不一致',evidence='纸面都是竖直')
        allowed,unknown=gate_visual_chains([issue],[])
        self.assertEqual(allowed,[])
        self.assertEqual(len(unknown),1)

    def test_structural_failure_keeps_candidates_for_review(self):
        components=[dict(name_zh=n,quantity=1) for n in ['箱体','透盖','油封']]
        nodes=[node('base',0,'箱体'),node('cover',1,'透盖','base',0),
               node('seal',2,'错误名称','cover',1)]
        class Model:
            name='recorded'
            def analyze(self,*args):return ProviderResponse(json.dumps({'nodes':nodes},ensure_ascii=False))
        result=infer_assembly(Model(),[object()],components,
                              dict(method='installation',max_attempts=1,verify_visual=False))
        self.assertEqual(result['nodes'],[])  # No failed attempt is automatically certified.
        self.assertEqual(len(result['unverified_nodes']),3)
        self.assertTrue(all(n.get('verification_reason') for n in result['unverified_nodes']))

    def test_oil_seal_contact_is_not_direct_installation_parent(self):
        components=[dict(name_zh=n,quantity=1) for n in ['箱体','输入轴透盖','齿轮轴','油封20×35×7']]
        nodes=[node('base',0,'箱体'),node('cover',1,'输入轴透盖','base',0),
               node('shaft',2,'齿轮轴','base',0),
               node('seal',3,'油封20×35×7','shaft',2,
                    '油封20×35×7嵌入输入轴透盖孔内，唇口贴齿轮轴轴颈')]
        result=validate_tree({'nodes':nodes},components,True)
        self.assertNotIn('seal',[n['id'] for n in result['nodes']])
        self.assertIn('seal',[n['id'] for n in result['unverified_nodes']])


if __name__=='__main__':unittest.main()
