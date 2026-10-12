import json
import unittest
from PIL import Image, ImageDraw
from engine_bom.drawing_layout import locate_regions, crop_region
from engine_bom.providers import ProviderResponse
from engine_bom.region_geometry import refine_region
from unittest.mock import patch


def clipped_view():
    image=Image.new('RGB',(500,500),'white')
    draw=ImageDraw.Draw(image)
    draw.line([(125,120),(305,120),(340,155),(340,420),(145,420),(125,395)],fill='black',width=4)
    draw.line([(145,150),(285,150),(310,170),(310,395),(155,395)],fill='black',width=3)
    draw.line((225,105,225,440),fill='black',width=1)
    # Neighboring view: widening must not swallow it.
    draw.rectangle((395,120,465,410),outline='black',width=4)
    return image


class LayoutCompletenessTests(unittest.TestCase):
    def region(self, box=None):
        return {'kind':'view','source_page':1,'bbox':box or [.20,.10,.72,.75],'evidence':'B-B'}

    def test_original_box_and_source_are_preserved(self):
        original=self.region(); result=refine_region(clipped_view(),original)
        self.assertEqual(original['bbox'],[.20,.10,.72,.75])
        self.assertEqual(result['model_bbox'],original['bbox'])
        self.assertTrue(result['needs_review'])
        self.assertEqual(result['source_page'],1)
        self.assertEqual(result['bbox_status'],'refined')

    def test_blank_or_missing_image_cannot_claim_complete(self):
        for image in (Image.new('RGB',(500,500),'white'),object()):
            result=refine_region(image,self.region())
            self.assertEqual(result['bbox_status'],'uncertain')
            self.assertEqual(result['bbox'],self.region()['bbox'])

    def test_frame_and_missing_cv_are_explicitly_not_verified(self):
        region=dict(self.region(),kind='frame')
        self.assertEqual(refine_region(clipped_view(),region)['bbox_status'],'not_applicable')
        with patch.dict('sys.modules',{'cv2':None}):
            self.assertEqual(refine_region(clipped_view(),self.region())['bbox_status'],'uncertain')

    def test_long_separator_does_not_expand_box_into_next_view(self):
        image=Image.new('RGB',(500,500),'white')
        ImageDraw.Draw(image).line((0,220,499,220),fill='black',width=3)
        result=refine_region(image,self.region())
        self.assertEqual(result['bbox_status'],'uncertain')
        self.assertEqual(result['bbox'],self.region()['bbox'])

    def test_far_disconnected_content_not_invented_as_complete(self):
        image=clipped_view()
        ImageDraw.Draw(image).rectangle((100,470,200,490),outline='black')
        result=refine_region(image,self.region())
        self.assertLess(result['bbox'][3],.94)
        self.assertIn('未相连',result['bbox_warning'])

    def test_right_overrun_and_clip_to_page(self):
        image=Image.new('RGB',(500,500),'white')
        ImageDraw.Draw(image).rectangle((200,180,445,300),outline='black',width=3)
        result=refine_region(image,self.region([.35,.3,.80,.7]))
        self.assertGreater(result['bbox'][2],.89)
        self.assertTrue(all(0<=n<=1 for n in result['bbox']))

    def test_fractional_crop_retains_boundary_pixel_and_page_mapping(self):
        first=Image.new('RGB',(10,10),'white');second=Image.new('RGB',(10,10),'black')
        result=crop_region([first,second],dict(self.region([.19,.19,.81,.81]),source_page=2))
        self.assertEqual(result.size,(8,8))
        self.assertEqual(result.getpixel((7,7)),(0,0,0))

    def test_clipped_bottom_contour_not_accepted_as_complete(self):
        image=clipped_view()
        class Provider:
            name='test'
            def analyze(self,*args):
                return ProviderResponse(json.dumps({'regions':[{'kind':'view','source_page':1,
                    'bbox':[.20,.10,.72,.75],'evidence':'零件7 B-B剖视图'}]}),'test')
        report=locate_regions(Provider(),[image])
        region=report['regions'][0]
        self.assertGreaterEqual(region['bbox'][3],.845,'Bottom outline is outside the model box')
        self.assertLess(region['bbox'][2],.79,'Do not swallow the neighboring view')
        self.assertEqual(image.getpixel((340,419)),(0,0,0))


if __name__=='__main__':unittest.main()
