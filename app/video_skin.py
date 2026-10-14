"""Photo-mode facial beauty support, separate from repair feature guards."""
import copy
from types import SimpleNamespace
import cv2,numpy as np
from region_masks import face_parts,face_beauty_mask,skin_blend,soft_edge
from core import FEATURES

SKIN_REVISION=2

def masks(rgb,face,context,labels):
    # Keep the original generous repair exclusion unchanged. Photo-mode parts
    # build the continuous skin/lid/brow/lip support on a lightweight copy.
    f=copy.copy(face);f.mask=face.mask.copy();f.protected=face.protected.copy()
    parts,hair,nostrils,local_labels=face_parts(rgb,f,context,labels)
    session=SimpleNamespace(original=rgb,faces=[f],part_regions=[parts],part_labels=[local_labels],semantic_skin=[parts['skin']],hair=[hair],nostrils=[nostrils])
    face_beauty_mask(session,0)
    a,b,_,_=f.box;p=f.points-[a,b]
    cavity=local_labels==11
    inner=np.zeros(f.mask.shape,np.uint8)
    ids=[78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95]
    cv2.fillPoly(inner,[p[ids].astype(np.int32)],1);cavity&=inner>0
    # The eye/mouth openings stay fixed. Their adjoining skin does not inherit
    # the old dilated safety ring used for blemish detection/inpainting.
    openings=f.beauty_eye_mask|cavity
    f.beauty_mask[openings]=0;f.beauty_eye_mask=openings;f.__dict__.pop('_skin_blend_cache',None)
    tone=skin_blend(f)
    details=np.isin(local_labels,[2,3,11,12,13])
    for ids in FEATURES[2:5]:
        patch=np.zeros(details.shape,np.uint8);cv2.fillConvexPoly(patch,cv2.convexHull(p[ids].astype(np.int32)),1);details|=patch>0
    detail_keep=soft_edge(~details,max(1,f.width*.01))
    smooth=tone*detail_keep
    return {'tone':tone,'smooth':smooth,'detail_keep':detail_keep,'openings':openings,'labels':local_labels,'support':f.beauty_mask,'revision':SKIN_REVISION}

def retouch(source,fine,low,weights,recipe):
    gain=float(np.interp(recipe.texture,[0,50,100],[.2,1,1.2]))
    patch=low+(fine-low)*(1-.82*recipe.smooth/100)+(source-fine)*gain
    base=source+(patch-source)*weights['smooth'][:,:,None]
    if recipe.whiten or recipe.redness or recipe.skin_warmth:
        lab=cv2.cvtColor(np.clip(base/255,0,1).astype(np.float32),cv2.COLOR_RGB2LAB);light=lab[:,:,0]
        # Shared photometric treatment crosses brows/lips smoothly, retaining
        # their source detail and LAB chroma. Tint stays on facial skin.
        lab[:,:,0]=np.minimum(100,light+recipe.whiten/100*8*np.clip((98-light)/22,0,1))
        lab[:,:,1]+=recipe.redness/100*3*weights['detail_keep'];lab[:,:,2]+=recipe.skin_warmth/100*5*weights['detail_keep']
        colored=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
        base=base+(colored-base)*weights['tone'][:,:,None]
    return base
