"""Smooth inverse warp of observed torso/lower-body envelopes for video.

Lower-body slimming and lengthening adjust the visible region when clothes or
crossed legs prevent separate anatomical contours. They do not reveal anatomy.
"""
import cv2,numpy as np
from liquify import cell_jacobian
from live_body import apply_body_field,BODY_KEYS

def field(shape,profile,values):
    if profile is None or not any(values.values()):return None
    h,w=shape;s=np.asarray(profile['origin']);hip=np.asarray(profile['hip']);axis=hip-s
    torso=float(np.linalg.norm(axis));width=profile['width'];length=profile['length']
    if torso<20 or width<16 or length<16:return None
    down=axis/torso;side=np.array([down[1],-down[0]])
    gh=257;gw=max(64,round(gh*w/h));yy,xx=np.meshgrid(np.linspace(0,h-1,gh),np.linspace(0,w-1,gw),indexing='ij')
    u=(xx-s[0])*side[0]+(yy-s[1])*side[1];v=(xx-s[0])*down[0]+(yy-s[1])*down[1]
    levels=np.r_[np.array([.2,.35,.5,.65,.8,.95])*torso,torso+np.array([.2,.4,.6,.8,.95])*length]
    bounds=profile['bounds'];left=np.interp(v,levels,bounds[:,0]);right=np.interp(v,levels,bounds[:,1])
    center=(left+right)/2;half=np.maximum((right-left)/2,width*.18)
    # Plateau over the actual silhouette; smooth background falloff outside.
    distance=np.maximum(0,np.abs(u-center)-half*.92)/(width*.70)
    horizontal=np.clip(1-distance,0,1);horizontal=horizontal**3*(10-15*horizontal+6*horizontal**2)
    neck=np.clip((v-torso*.12)/(torso*.22),0,1);neck=neck*neck*(3-2*neck)
    bottom=np.clip((torso+length+width*.38-v)/(width*.38),0,1);bottom=bottom*bottom*(3-2*bottom)
    edge=np.minimum.reduce([xx,yy,w-1-xx,h-1-yy]);image_fade=np.clip(edge/max(8,width*.2),0,1);image_fade=image_fade*image_fade*(3-2*image_fade)
    support=horizontal*neck*bottom*image_fade
    lower=np.clip((v-torso*.85)/(torso*.25),0,1);lower=lower*lower*(3-2*lower)
    amount=values['body_slim']/100*(.16*(1-lower)+.064*lower)
    amount+=values['waist_slim']/100*.20*np.exp(-((v/torso-.65)/.23)**2)
    amount+=values['leg_slim']/100*.16*lower
    # Entire lower visible region scales about the pelvis. This keeps bent and
    # overlapping legs together and removes per-frame knee/foot threshold pops.
    foot=s+down*(torso+length);margin=min((h-2-foot[1])/max(.1,down[1]),w)
    extension=max(0,min(length*values['leg_length']/100*.12,margin*.45))
    dv=-np.clip(v-torso,0,length)*(extension/max(1,length))/(1+extension/max(1,length))
    dv*=horizontal*image_fade
    after=np.clip((torso+length+extension+width*.38-v)/(width*.38),0,1);after=after*after*(3-2*after);dv*=after
    du=(u-center)*(1/(1-amount)-1)*support
    displacement=np.stack((du*side[0]+dv*down[0],du*side[1]+dv*down[1]),axis=2).astype(np.float32)
    for attempt in range(12):
        strength=.85**attempt;grid=displacement*strength
        minimum=float(cell_jacobian(grid,(w-1)/(gw-1),(h-1)/(gh-1)).min())
        if np.isfinite(grid).all() and minimum>.55:break
    else:return None
    actual=[k for k in BODY_KEYS if values[k]>0 and (k!='leg_length' or extension>=.1)]
    if not actual:return None
    return {'roi':(0,0,w,h),'grid':grid,'jacobian_min':minimum,'effective_scale':strength,'line_anchors':0,
            'extension_pixels':extension*strength,'features':actual,'method':'visible-envelope','background_protection':'bounded smooth field; nearby lines may still bend'}

def apply(rgb,track,recipe):
    values={k:getattr(recipe,k) for k in BODY_KEYS};result=field(rgb.shape[:2],track.get('profile'),values)
    return (apply_body_field(rgb,result),result) if result is not None else (rgb,None)
