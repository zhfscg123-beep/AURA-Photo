"""Blend retouch deltas at a confirmed face/body junction, preserving lighting."""
import cv2,numpy as np
from region_masks import face_beauty_mask
from body_details import body_scope

def blend_junction(rgb,reference,session,layers):
    if getattr(session,'body_owner',None) is None:return rgb
    out=rgb
    for fi,f in enumerate(session.faces):
        a,b,c,d=f.box;fw=f.width;pad=max(8,round(fw*.10));p=f.points
        jaw=p[[234,93,172,136,150,152,377,379,365,397,454]]
        x0=max(0,int(jaw[:,0].min()-pad));x1=min(rgb.shape[1],int(jaw[:,0].max()+pad+1))
        y0=max(0,int(jaw[:,1].min()-pad));y1=min(rgb.shape[0],int(jaw[:,1].max()+pad+1))
        if x0>=x1 or y0>=y1:continue
        face=np.zeros((y1-y0,x1-x0),bool);beauty=face_beauty_mask(session,fi)>0
        xx,yy,zz,tt=max(x0,a),max(y0,b),min(x1,c),min(y1,d)
        if xx<zz and yy<tt:face[yy-y0:tt-y0,xx-x0:zz-x0]=beauty[yy-b:tt-b,xx-a:zz-a]
        body=body_scope(session,fi,layers)[y0:y1,x0:x1]
        if not face.any() or not body.any():continue
        allowed=face|body;distance_f=cv2.distanceTransform((~face).astype(np.uint8),cv2.DIST_L2,5)
        distance_b=cv2.distanceTransform((~body).astype(np.uint8),cv2.DIST_L2,5)
        width=max(4,fw*.065);band=np.clip(1-np.maximum(distance_f,distance_b)/width,0,1)*allowed
        if not np.any(band):continue
        src=reference[y0:y1,x0:x1];edited=rgb[y0:y1,x0:x1];delta=edited-src
        if np.max(np.abs(delta[band>0]),initial=0)<1e-6:continue
        # Filter the change only. The source retains its natural jaw shadow
        # and photographic detail; no original skin RGB is blurred or filled.
        weight=allowed.astype(np.float32);sigma=max(2,width*.45)
        denominator=cv2.GaussianBlur(weight,(0,0),sigma)
        smooth=cv2.GaussianBlur(delta*weight[:,:,None],(0,0),sigma)/np.maximum(denominator[:,:,None],1e-5)
        blend=band*band*(3-2*band);result=edited+(smooth-delta)*blend[:,:,None]
        if out is rgb:out=rgb.copy()
        use=blend>0;out[y0:y1,x0:x1][use]=np.clip(result[use],0,255)
    return out
