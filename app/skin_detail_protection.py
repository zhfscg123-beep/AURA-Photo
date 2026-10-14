"""Conservative detail guards; dark dots are candidates, never diagnoses."""
import numpy as np,cv2

def build(session,fi):
    f=session.faces[fi];a,b,c,d=f.box;src=session.original[b:d,a:c].astype(np.float32)
    features=f.protected>0
    for key in ('eyes','brows','lips','iris','sclera','teeth'):
        region=session.part_regions[fi].get(key)
        if region is not None:features=features|(region>0)
    features=features|(session.nostrils[fi]>0)|np.isin(session.part_labels[fi],[2,3,4,5,6,9,11,12,13,17,18])
    # Tonal brightening may include brows and their surrounding skin. Keep the
    # existing eye/mouth/nostril protections, without inheriting the brow guard
    # used for texture processing and blemish repair.
    from core import FEATURES
    tonal=np.zeros(f.mask.shape,np.uint8);p=f.points-[a,b]
    for ids in (FEATURES[0],FEATURES[1],FEATURES[4]):
        cv2.fillConvexPoly(tonal,cv2.convexHull(p[ids].astype(np.int32)),1)
    radius=max(2,round(f.width*.018))
    tonal=cv2.dilate(tonal,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1)))>0
    for key in ('eyes','lips','iris','sclera','teeth'):
        region=session.part_regions[fi].get(key)
        if region is not None:tonal|=region>0
    tonal|=(session.nostrils[fi]>0)|np.isin(session.part_labels[fi],[4,5,6,9,11,12,13,17,18])
    lab=cv2.cvtColor(np.clip(src/255,0,1),cv2.COLOR_RGB2LAB)
    local=cv2.GaussianBlur(lab,(0,0),max(1,f.width*.009))
    dark=local[:,:,0]-lab[:,:,0];red=lab[:,:,1]-local[:,:,1]
    safe=(f.mask>.7)&~features
    dots=(dark>5)&(red<3)&safe
    n,labels,stats,_=cv2.connectedComponentsWithStats(dots.astype(np.uint8),8);marks=np.zeros(dots.shape,bool)
    for i in range(1,n):
        x,y,w,h,area=stats[i]
        if 2<=area<=max(8,f.width*f.width*.003) and max(w,h)<=max(4,f.width*.075) and max(w,h)/max(1,min(w,h))<2.4 and area/(w*h)>.4:
            marks[labels==i]=True
    marks=cv2.dilate(marks.astype(np.uint8),np.ones((3,3),np.uint8))>0
    return dict(features=features,tonal_features=tonal,marks=marks,automatic=safe&(~marks if getattr(session,'protect_dark_points',False) else True),
                note='深色点保护候选；颜色与形状规则，不代表痣／雀斑分类。')

def strength_mask(session,fi,box,include_brows=False):
    a,b,c,d=box;out=np.ones((d-b,c-a),np.float32)
    guards=getattr(session,'detail_protection',[])
    if fi>=len(guards):return out
    f=session.faces[fi];x,y,z,t=f.box;x0,y0,x1,y1=max(a,x),max(b,y),min(c,z),min(d,t)
    if x0<x1 and y0<y1:
        key='tonal_features' if include_brows else 'features'
        protected=guards[fi].get(key,guards[fi]['features'])|(guards[fi]['marks'] if getattr(session,'protect_dark_points',False) else False)
        out[y0-b:y1-b,x0-a:x1-a]*=~protected[y0-y:y1-y,x0-x:x1-x]
    return out
