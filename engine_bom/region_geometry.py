"""Bounded image-content refinement of VLM display boxes, never edit boxes.

Connected ink intersecting the original region is followed in a local window.
Neighbors outside that region are not selected. A component touching the search
limit or a separator is ambiguous and is flagged rather than swallowing a page.
This is a visibility heuristic, NOT semantic completeness certification.
"""
import math


def refine_region(image, region):
    original=list(region['bbox'])
    result=dict(region,model_bbox=original,bbox=list(original),bbox_status='not_checked',
                bbox_basis='model_only',needs_review=True)
    if region.get('kind') not in ('view','title_block','bom_table','technical_notes'):
        result['bbox_status']='not_applicable'
        return result
    try:
        import cv2
        import numpy as np
    except ImportError:
        result.update(bbox_status='uncertain',bbox_warning='未安装OpenCV，区域仅为模型粗定位；请人工核对完整性。')
        return result
    if not hasattr(image,'size') or not hasattr(image,'convert'):
        result.update(bbox_status='uncertain',bbox_warning='缺少可检查的原页图像。')
        return result
    width,height=image.size
    scale=min(1,1600/max(width,height))
    page=image.convert('L')
    if scale<1:page=page.resize((max(1,round(width*scale)),max(1,round(height*scale))))
    w,h=page.size
    x0,y0,x1,y1=(original[0]*w,original[1]*h,original[2]*w,original[3]*h)
    pad_x=max(8,min(w*.15,(x1-x0)*.25))
    pad_y=max(8,min(h*.15,(y1-y0)*.25))
    left,top=max(0,math.floor(x0-pad_x)),max(0,math.floor(y0-pad_y))
    right,bottom=min(w,math.ceil(x1+pad_x)),min(h,math.ceil(y1+pad_y))
    pixels=np.array(page.crop((left,top,right,bottom)))
    ink=(pixels<195).astype('uint8')
    # Join only tiny raster gaps; no large dilation connecting neighboring views.
    ink=cv2.morphologyEx(ink,cv2.MORPH_CLOSE,np.ones((2,2),'uint8'))
    count,labels,stats,_=cv2.connectedComponentsWithStats(ink,8)
    sx0,sy0=max(0,math.floor(x0-left)),max(0,math.floor(y0-top))
    sx1,sy1=min(right-left,math.ceil(x1-left)),min(bottom-top,math.ceil(y1-top))
    seed=labels[sy0:sy1,sx0:sx1]
    ids,hits=np.unique(seed[seed>0],return_counts=True)
    minimum_area=max(3,round(w*h/1000000))
    bounds=[x0,y0,x1,y1]
    selected,blocked=0,0
    for component,inside in zip(ids,hits):
        x,y,cw,ch,area=stats[component]
        if area<minimum_area or inside<max(2,area*.15):
            continue
        # Unbroken page/table dividers can connect unrelated views. They must
        # not be used to grow a view box into a neighboring panel.
        touches_limit=(x<=1 or y<=1 or x+cw>=right-left-1 or y+ch>=bottom-top-1)
        extends=(x+left<x0-2 or y+top<y0-2 or x+cw+left>x1+2 or y+ch+top>y1+2)
        if touches_limit and extends:
            blocked+=1
            continue
        selected+=1
        bounds=[min(bounds[0],x+left),min(bounds[1],y+top),
                max(bounds[2],x+cw+left),max(bounds[3],y+ch+top)]
    if not selected:
        result.update(bbox_status='uncertain',bbox_warning='未找到可独立跟踪的区域内容；请核对边界。')
        return result
    safety=max(2,min(w,h)*.003)
    box=[max(0,(bounds[0]-safety)/w),max(0,(bounds[1]-safety)/h),
         min(1,(bounds[2]+safety)/w),min(1,(bounds[3]+safety)/h)]
    result.update(bbox=box,bbox_basis='model_plus_local_ink',bbox_status='refined' if any(abs(a-b)>.002 for a,b in zip(box,original)) else 'checked')
    if blocked:
        result.update(bbox_status='uncertain',bbox_warning='部分线条延伸到局部搜索边界或相邻区域，不能保证框选完整，请人工调整。')
    else:
        result['bbox_warning']='已按相连图面内容补边；独立标注或未相连轮廓仍需人工核对。'
    return result
