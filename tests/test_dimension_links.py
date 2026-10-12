import copy
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image,ImageDraw
from engine_bom.dimension_links import inspect_dimension_links,validate_links,nominal,profile_support,propose_bore_links,validate_text_coverage,contour_candidates
from engine_bom.ingestion import load_document
from engine_bom.providers.base import ProviderResponse,ProviderError


COMPONENTS=[{'name_zh':'箱体'},{'name_zh':'端盖'}]


def pair(a='Φ62J7',b='Φ60H9/h9'):
    def obs(key,value,index,box):
        return dict(id=key,value=value,unit='mm',kind='diameter',source_page=1,bbox=box,
                    view='A-A',component_index=index,feature='输出端配合面',physical_axis='output_diameter',evidence=value+'尺寸界线落在输出端圆柱面')
    return {'observations':[obs('d1',a,0,[.2,.5,.3,.6]),obs('d2',b,1,[.2,.7,.3,.8])],
            'links':[dict(id='p1',left_id='d1',right_id='d2',relation='mating_nominal',physical_axis='output_diameter',
                          evidence='端盖止口与箱体孔直接配合',geometry=dict(left_surface='箱体孔',right_surface='端盖止口',boundary_correspondence='同轴圆柱界线连续且直接接合，无不同轴段阶梯'))]}


def verification(data,decision='keep'):
    a,b=data['observations']
    return {'checks':[dict(id='p1',decision=decision,left_value=a['value'],right_value=b['value'],
                          left_component_index=a['component_index'],right_component_index=b['component_index'],
                          left_bbox=a['bbox'],right_bbox=b['bbox'],same_feature_confirmed=True,
                          continuous_profile_confirmed=True,
                          evidence='独立局部重新读取两处标注及配合界线',boundary_correspondence='两个圆柱面直接接合') ]}


class Provider:
    name='recorded'
    def __init__(self,values):self.values=iter(values);self.calls=[]
    def analyze(self,images,prompt):
        self.calls.append((images,prompt));value=next(self.values)
        if isinstance(value,Exception):raise value
        return ProviderResponse(json.dumps(value,ensure_ascii=False))


class DimensionLinksTests(unittest.TestCase):
    def inspect(self,data,check):
        self.provider=Provider([data,check])
        return inspect_dimension_links(self.provider,[Image.new('RGB',(3000,2000))],[],COMPONENTS,1)

    def test_modified_diameter_is_located_and_calculated(self):
        data=pair();r=self.inspect(data,verification(data))
        self.assertEqual(r['status'],'checked');self.assertEqual(len(r['issues']),1)
        issue=r['issues'][0]
        self.assertEqual(issue['calculation']['difference_mm'],'2')
        self.assertEqual(issue['linked_dimensions'][1]['bbox'],[.2,.7,.3,.8])
        self.assertIn('Φ60H9/h9',issue['message'])
        self.assertEqual(len(self.provider.calls),2)

    def test_correct_diameters_with_different_fits_are_not_nominal_conflicts(self):
        data=pair(b='Φ62H9/h9');r=self.inspect(data,verification(data))
        self.assertEqual(r['issues'],[]);self.assertEqual(r['status'],'checked')

    def test_inconsistent_reread_is_unknown_not_drawing_error(self):
        data=pair();check=verification(data);check['checks'][0]['right_value']='Φ62H9/h9'
        r=self.inspect(data,check)
        self.assertFalse(r['issues']);self.assertEqual(r['status'],'needs_review');self.assertEqual(len(r['unverified_links']),1)

    def test_disagreeing_component_identity_is_unknown(self):
        data=pair();check=verification(data);check['checks'][0]['right_component_index']=0
        r=self.inspect(data,check);self.assertFalse(r['issues']);self.assertEqual(len(r['unverified_links']),1)

    def test_uncertain_relationship_not_accepted(self):
        data=pair();check={'checks':[dict(id='p1',decision='uncertain',evidence='无法辨认直接配合面')]}
        r=self.inspect(data,check);self.assertFalse(r['issues']);self.assertEqual(r['status'],'needs_review')

    def test_empty_links_do_not_mean_geometry_passed(self):
        r=inspect_dimension_links(Provider([{'observations':[],'links':[]}]),[object()],[],COMPONENTS,1)
        self.assertEqual(r['status'],'insufficient_evidence')

    def test_failed_independent_review_preserves_candidates(self):
        p=Provider([pair(),ProviderError('offline')]);r=inspect_dimension_links(p,[object()],[],COMPONENTS,1)
        self.assertEqual(r['status'],'provider_failed');self.assertFalse(r['issues']);self.assertEqual(len(r['unverified_links']),1)

    def test_failed_review_does_not_erase_previously_rejected_candidate_reasons(self):
        data=pair();bad=copy.deepcopy(data['links'][0]);bad.update(id='rejected',evidence='通过轴承相连，非直接接触')
        data['links'].append(bad)
        r=inspect_dimension_links(Provider([data,ProviderError('offline')]),[object()],[],COMPONENTS,1)
        self.assertEqual(r['status'],'provider_failed');self.assertEqual(len(r['unverified_links']),2)
        self.assertEqual(r['unverified_links'][0]['link']['id'],'rejected')
        self.assertIn('轴承',r['unverified_links'][0]['verification_reason'])

    def test_different_physical_axes_cannot_link(self):
        data=pair();data['observations'][1]['physical_axis']='input_diameter'
        _,errors=validate_links(json.dumps(data),1,COMPONENTS);self.assertTrue(errors)

    def test_direct_fit_requires_different_components(self):
        data=pair();data['observations'][1]['component_index']=0
        _,errors=validate_links(json.dumps(data),1,COMPONENTS);self.assertTrue(errors)

    def test_bearing_mediated_fit_is_not_direct_nominal_equality(self):
        data=pair('Φ62J7','Φ30k6')
        data['links'][0]['evidence']='箱体孔与轴之间通过轴承6206形成配合，分别对应轴承外径和内径'
        r=self.inspect(data,verification(data))
        self.assertFalse(r['issues'])
        self.assertTrue(r['unverified_links'])

    def test_nonobject_geometry_is_rejected_without_crashing(self):
        for geometry in [['bad'],'bad',3]:
            with self.subTest(geometry=geometry):
                data=pair();data['links'][0]['geometry']=geometry
                self.assertTrue(validate_links(json.dumps(data),1,COMPONENTS)[1])

    def test_local_text_conflict_cannot_locate_62_on_the_30_annotation(self):
        from engine_bom.dimension_text import filter_position_conflicts
        data=pair()
        local={'observations':[dict(raw_text='30k6',fit_body='30k6',source_page=1,
                    confidence=.98,bbox=data['observations'][0]['bbox'])]}
        kept,rejected=filter_position_conflicts(data['observations'],local)
        self.assertEqual([o['id'] for o in kept],['d2'])
        self.assertEqual(rejected[0]['observation']['id'],'d1')
        # Nearby text is not enough to contradict an annotation.
        local['observations'][0]['bbox']=[.3,.5,.4,.6]
        self.assertEqual(len(filter_position_conflicts(data['observations'],local)[0]),2)

    def test_same_feature_requires_same_component(self):
        data=pair();data['links'][0]['relation']='same_feature'
        _,errors=validate_links(json.dumps(data),1,COMPONENTS);self.assertTrue(errors)

    def test_existing_same_feature_link_still_gets_blind_geometry_review(self):
        data=pair();data['observations'][1]['component_index']=0
        data['links'][0]['relation']='same_feature'
        check=verification(data)
        blind={'checks':[dict(id='p1',decision='uncertain',evidence='不同孔段，无法证明孔壁连续')]}
        p=Provider([data,blind,check])
        r=inspect_dimension_links(p,[Image.new('RGB',(1000,1000),'white')],[],COMPONENTS,1)
        self.assertIn('BLIND_BORE_GEOMETRY',p.calls[1][1])
        self.assertNotIn('Φ60',p.calls[1][1])
        self.assertFalse(r['issues']);self.assertEqual(r['status'],'needs_review')

    def test_existing_same_feature_requires_actual_ink_support(self):
        data=pair();data['observations'][1]['component_index']=0
        data['links'][0]['relation']='same_feature'
        profile={'axis':'vertical','edges':[[[.18,.45],[.18,.85]],[[.32,.45],[.32,.85]]]}
        blind={'checks':[dict(id='p1',decision='keep',evidence='遮数回读认为孔壁连续',profile=profile)]}
        image=Image.new('RGB',(1000,1000),'white')
        r=inspect_dimension_links(Provider([data,blind,verification(data)]),[image],[],COMPONENTS,1)
        self.assertFalse(r['issues'])
        draw=ImageDraw.Draw(image)
        for x in (180,320):draw.line((x,450,x,850),fill='black',width=2)
        r=inspect_dimension_links(Provider([data,blind,verification(data)]),[image],[],COMPONENTS,1)
        self.assertEqual(len(r['issues']),1)

    def test_reread_rejecting_continuity_cannot_be_overridden_by_blind_ink_support(self):
        data=pair();data['links']=[];data['observations'][1]['component_index']=0
        check=verification(data);check['checks'][0].update(id='candidate-0',continuous_profile_confirmed=False,
            evidence='两处孔段在不同轴系，孔壁不连续，不能比较')
        image=Image.new('RGB',(1000,1000),'white');draw=ImageDraw.Draw(image)
        for x in (180,320):draw.line((x,450,x,850),fill='black',width=2)
        profile={'axis':'vertical','edges':[[[.18,.45],[.18,.85]],[[.32,.45],[.32,.85]]]}
        blind={'checks':[dict(id='candidate-0',decision='keep',evidence='误认为连续孔壁',profile=profile)]}
        r=inspect_dimension_links(Provider([data,blind,check]),[image],[],COMPONENTS,1)
        self.assertFalse(r['issues']);self.assertEqual(r['status'],'needs_review')

    def test_different_candidate_axes_require_explicit_independent_axis_confirmation(self):
        data=pair();data['links']=[];data['observations'][1].update(component_index=0,physical_axis='other shaft')
        image=Image.new('RGB',(1000,1000),'white');draw=ImageDraw.Draw(image)
        for x in (180,320):draw.line((x,450,x,850),fill='black',width=2)
        profile={'axis':'vertical','edges':[[[.18,.45],[.18,.85]],[[.32,.45],[.32,.85]]]}
        blind={'checks':[dict(id='candidate-0',decision='keep',evidence='认为连续',profile=profile)]}
        check=verification(data);check['checks'][0]['id']='candidate-0'
        r=inspect_dimension_links(Provider([data,blind,check]),[image],[],COMPONENTS,1)
        self.assertFalse(r['issues'])
        check['checks'][0].update(left_physical_axis='same confirmed shaft',right_physical_axis='same confirmed shaft')
        r=inspect_dimension_links(Provider([data,blind,check]),[image],[],COMPONENTS,1)
        self.assertEqual(len(r['issues']),1)

    def test_bad_bounds_page_identity_or_missing_geometry_rejected(self):
        for key,value in [('bbox',[.4,.5,.1,.2]),('source_page',2),('component_index',True),('component_index',999),('evidence','')]:
            with self.subTest(key=key,value=value):
                data=pair();data['observations'][0][key]=value
                _,errors=validate_links(json.dumps(data),1,COMPONENTS);self.assertTrue(errors)
        data=pair();data['links'][0]['geometry']={}
        self.assertTrue(validate_links(json.dumps(data),1,COMPONENTS)[1])

    def test_malformed_reference_does_not_crash_validator(self):
        data=pair();data['links'][0]['left_id']=['bad']
        self.assertTrue(validate_links(json.dumps(data),1,COMPONENTS)[1])

    def test_detail_crops_come_from_native_pixels(self):
        data=pair();self.inspect(data,verification(data))
        images=self.provider.calls[0][0]
        self.assertEqual(images[0].size,(3000,2000));self.assertEqual(images[1].size,(1800,1200))
        self.assertEqual(self.provider.calls[1][0][1].size,(780,520))

    def test_ingestion_preserves_native_detail_source(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'sheet.png';Image.new('RGB',(3000,2000)).save(p)
            pages=load_document(str(p),{'image_formats':['.png'],'max_image_long_side':1000})
            self.assertEqual(pages[0].image.size,(1000,666));self.assertEqual(pages[0].original_image.size,(3000,2000))

    def test_nominal_units_and_unparseable_formats(self):
        self.assertEqual(nominal({'value':'Φ6.2H9','kind':'diameter','unit':'cm'}),62)
        for value in ['20±.1','M8','Φ?','100 +.2/-.1',None]:
            self.assertIsNone(nominal({'value':value,'kind':'diameter','unit':'mm'}))

    def test_invalid_extra_observation_does_not_discard_located_pair(self):
        data=pair();check=verification(data);data['observations'].append({'id':'bad','kind':'angle'})
        r=self.inspect(data,check)
        self.assertEqual(len(r['issues']),1);self.assertEqual(len(r['rejected_observations']),1)
        self.assertEqual(r['status'],'needs_review')

    def test_neighbor_proposal_does_not_assert_continuity_or_use_expected_number(self):
        data=pair();data['observations'][1]['component_index']=0
        links=propose_bore_links(data['observations'])
        self.assertEqual(len(links),1);self.assertTrue(links[0]['proposal'])
        data['observations'][1]['value']='Φ100H9/h9'
        self.assertEqual(propose_bore_links(data['observations']),links)
        data['links']=[];check=verification(data);check['checks'][0]['id']='candidate-0'
        blind={'checks':[dict(id='candidate-0',decision='uncertain',evidence='轮廓无法确认')]}
        r=inspect_dimension_links(Provider([data,blind,check]),[Image.new('RGB',(1000,1000),'white')],[],COMPONENTS,1)
        self.assertEqual(r['issues'],[]);self.assertEqual(len(r['unverified_links']),1)

    def test_located_micro_reading_cannot_be_replaced_by_a_remote_equal_value(self):
        data=pair();ref=dict(id='text-1',source_page=1,nominal_diameter='62',bbox=[.2,.8,.3,.82])
        self.assertTrue(validate_text_coverage(data,[ref]))
        data['unmapped_text']=[dict(id='text-1',reason='局部对象不能确定，保留待核实')]
        self.assertFalse(validate_text_coverage(data,[ref]))
        data.pop('unmapped_text');data['observations'][0]['bbox']=ref['bbox']
        self.assertFalse(validate_text_coverage(data,[ref]))

    def test_unmapped_text_is_retained_and_prevents_checked_status(self):
        data=pair(b='Φ62H9/h9')
        data['unmapped_text']=[dict(id='text-1',reason='文字可读，但指向对象不明')]
        r=self.inspect(data,verification(data))
        self.assertEqual(r['status'],'needs_review')
        self.assertEqual(r['unmapped_text'],data['unmapped_text'])

    def test_proposals_survive_axis_aliases_and_other_column_interleaving(self):
        data=pair();data['observations'][1]['physical_axis']='same physical axis, another label'
        other=copy.deepcopy(data['observations'])
        for i,obs in enumerate(other):
            obs.update(id='other-'+str(i),bbox=[.5,obs['bbox'][1]+.02,.6,obs['bbox'][3]+.02])
        links=propose_bore_links(data['observations']+other)
        self.assertEqual({frozenset((l['left_id'],l['right_id'])) for l in links},
                         {frozenset(('d1','d2')),frozenset(('other-0','other-1'))})
        self.assertTrue(all(l['proposal'] for l in links))

    def test_near_aligned_texts_cannot_be_split_by_a_third_texts_column_boundary(self):
        base=pair()['observations'][0]
        observations=[]
        for key,x,y in [('shifted',.195,.56),('upper',.261,.66),('lower',.254,.80),('end',.256,.88)]:
            obs=copy.deepcopy(base);obs.update(id=key,bbox=[x-.01,y-.01,x+.01,y+.01])
            observations.append(obs)
        links=propose_bore_links(observations)
        self.assertIn(('lower','end'),[(l['left_id'],l['right_id']) for l in links])

    def test_contour_coordinate_aid_uses_actual_local_ink_and_still_needs_verification(self):
        image=Image.new('RGB',(1000,1000),'white');draw=ImageDraw.Draw(image)
        for x in (180,320):draw.line((x,450,x,850),fill='black',width=2)
        candidates=contour_candidates(image,pair()['observations'])
        self.assertTrue(candidates)
        self.assertTrue(profile_support({'profile':candidates[0]},image,pair()['observations'])['supported'])
        self.assertEqual(contour_candidates(Image.new('RGB',(1000,1000),'white'),pair()['observations']),[])

    def test_actual_continuous_profile_has_pixel_support_and_local_scope(self):
        image=Image.new('RGB',(1000,1000),'white');draw=ImageDraw.Draw(image)
        for x in (180,320):draw.line((x,450,x,850),fill='black',width=2)
        check={'profile':{'axis':'vertical','edges':[[[.18,.45],[.18,.85]],[[.32,.45],[.32,.85]]]}}
        self.assertTrue(profile_support(check,image,pair()['observations'])['supported'])
        self.assertFalse(profile_support(check,Image.new('RGB',(1000,1000),'white'))['supported'])
        far=copy.deepcopy(check);far['profile']['edges']=[[[.7,.1],[.7,.9]],[[.9,.1],[.9,.9]]]
        self.assertIsNone(profile_support(far,image,pair()['observations']))
        short=copy.deepcopy(check);short['profile']['edges']=[[[.18,.5],[.18,.55]],[[.32,.5],[.32,.55]]]
        self.assertIsNone(profile_support(short,image,pair()['observations']))

    def test_proposal_needs_independent_read_and_contour_ink_before_issue(self):
        data=pair();data['links']=[];data['observations'][1]['component_index']=0
        check=verification(data);check['checks'][0].update(id='candidate-0',continuous_profile_confirmed=True,
            profile={'axis':'vertical','edges':[[[.18,.45],[.18,.85]],[[.32,.45],[.32,.85]]]})
        image=Image.new('RGB',(1000,1000),'white');draw=ImageDraw.Draw(image)
        for x in (180,320):draw.line((x,450,x,850),fill='black',width=2)
        blind={'checks':[dict(id='candidate-0',decision='keep',evidence='独立遮数读取连续孔壁',profile=check['checks'][0]['profile'])]}
        r=inspect_dimension_links(Provider([data,blind,check]),[image],[],COMPONENTS,1)
        self.assertEqual(len(r['issues']),1);self.assertEqual(r['issues'][0]['calculation']['difference_mm'],'2')
        self.assertTrue(r['issues'][0]['profile_support']['supported'])

    def test_blind_geometry_prompt_contains_no_dimension_values(self):
        data=pair();data['links']=[];data['observations'][1]['component_index']=0
        blind={'checks':[dict(id='candidate-0',decision='uncertain',evidence='局部遮挡不能确认')]}
        check=verification(data);check['checks'][0]['id']='candidate-0'
        p=Provider([data,blind,check]);inspect_dimension_links(p,[Image.new('RGB',(1000,1000),'black')],[],COMPONENTS,1)
        images,prompt=p.calls[1]
        self.assertIn('BLIND_BORE_GEOMETRY',prompt);self.assertNotIn('62',prompt);self.assertNotIn('60H9',prompt)
        # The text region is white in transient input, native source was black.
        self.assertEqual(images[0].getpixel((150,100)),(255,255,255))

    def test_continuous_bore_cannot_trace_two_original_pages(self):
        data=pair();data['links'][0]['relation']='continuous_bore';data['observations'][1]['component_index']=0
        data['observations'][1]['source_page']=2
        self.assertTrue(validate_links(json.dumps(data),2,COMPONENTS)[1])

    def test_zero_diameter_is_not_a_valid_nominal(self):
        self.assertIsNone(nominal({'value':'Φ0H9','kind':'diameter','unit':'mm'}))

    def test_ambiguous_duplicate_observation_id_is_fully_quarantined(self):
        data=pair();data['observations'].append(copy.deepcopy(data['observations'][0]))
        value,errors=validate_links(json.dumps(data),1,COMPONENTS,quarantine_invalid=True)
        self.assertEqual(errors,[])
        self.assertEqual([o['id'] for o in value['observations']],['d2'])
        self.assertEqual(len(value['rejected_observations']),2);self.assertEqual(value['links'],[])

if __name__=='__main__':unittest.main()
