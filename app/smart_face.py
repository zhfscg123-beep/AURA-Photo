"""Conservative WFLW-98 feature targets in the calibrated face coordinate frame.

Landmark groups follow the vendored SPIGA WFLW annotation/edge definitions.
This changes geometry only; it never synthesizes pixels or blends a second face.
"""
import numpy as np
from reshape_settings import SMART_KEYS

def targets(points,target,values,horizontal,vertical,pivot,width,visibility,contour_visibility):
    if not any(float(values.get(k,0)) for k in SMART_KEYS):return target
    basis=np.column_stack((horizontal,vertical))
    p=(points-pivot)@basis;out=p.copy()
    def value(key):return float(values.get(key,0))/100
    def move(ids,new):
        ids=np.asarray(ids);support=np.asarray(visibility)[ids]
        # A glasses/hair/foreground-occluded feature is held still as a unit.
        confidence=0. if np.mean(support)<.65 else float(np.mean(support))
        out[ids]+= (new-p[ids])*confidence
    eye_distance=np.linalg.norm(points[60:68].mean(0)-points[68:76].mean(0))
    for side,ids,pupil in (('right',np.arange(60,68),96),('left',np.arange(68,76),97)):
        center=p[ids].mean(0);ids=np.r_[ids,pupil];local=p[ids]-center
        size=value('fs_eye_'+side+'_size')*.20
        factors=np.clip([1+size+value('fs_eye_'+side+'_width')*.20,
                         1+size+value('fs_eye_'+side+'_height')*.25],.65,1.40)
        # Positive tilt raises the anatomical outer corner on both sides.
        angle=value('fs_eye_'+side+'_tilt')*np.deg2rad(10)*(-1 if side=='left' else 1)
        c,s=np.cos(angle),np.sin(angle);rotation=np.array([[c,s],[-s,c]])
        new=(local*factors)@rotation+center
        new[:,0]+=np.sign(center[0])*eye_distance*.09*value('fs_eye_distance')
        move(ids,new)
    ids=np.arange(51,60);new=p[ids].copy();center=np.mean(p[55:60,0]);top=p[51,1]
    # Width affects the nose base progressively, without broadening the bridge.
    extent=max(width*.05,float(np.max(p[ids,1])-top))
    base=np.clip((new[:,1]-top)/extent,0,1)
    new[:,0]+=(new[:,0]-center)*.22*value('fs_nose_width')*base
    new[:,1]=top+(new[:,1]-top)*(1+.15*value('fs_nose_height'))
    move(ids,new)
    ids=np.arange(76,96);new=p[ids].copy();center=(p[76]+p[82])/2
    new[:,0]=center[0]+(new[:,0]-center[0])*(1+.22*value('fs_mouth_width'))
    new[:,1]+=width*.025*value('fs_mouth_height')
    # Shared mouth corners stay on the same seam; lip thickness changes only
    # the upper/lower rings, not teeth independently from the lip aperture.
    for ring,key in (([77,78,79,80,81,89,90,91],'fs_upper_lip'),
                     ([83,84,85,86,87,93,94,95],'fs_lower_lip')):
        ring=np.asarray(ring);t=np.clip((p[ring,0]-p[76,0])/max(1e-6,p[82,0]-p[76,0]),0,1)
        seam=p[76,1]*(1-t)+p[82,1]*t
        new[ring-76,1]+=(p[ring,1]-seam)*.35*value(key)
    span=max(width*.04,(p[82,0]-p[76,0])/2)
    corner=np.clip(np.abs(p[ids,0]-center[0])/span,0,1)**2
    new[:,1]-=width*.025*value('fs_smile')*corner
    move(ids,new)
    profile=np.sin(np.linspace(0,np.pi,33))**.5
    out[:33,0]+=p[:33,0]*.12*value('fs_face_width')*profile*np.asarray(contour_visibility)
    out[[0,32]]=p[[0,32]]
    addition=(out-p)@basis.T
    length=np.linalg.norm(addition,axis=1)
    addition*=np.minimum(1,width*.085/np.maximum(length,1e-9))[:,None]
    return target+addition
