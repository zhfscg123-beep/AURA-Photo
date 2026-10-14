"""AI-guided candidates + neural local repair, with editable per-type masks.

The neural model predicts blemishes, not diagnoses of moles or freckles.
Colour/scale rules split candidates; ambiguous types need preview/correction.
"""
import cv2,numpy as np
from feature_catalog import FACE_REPAIR,FACE_DETAILS
from region_masks import soft_edge

def blobs(binary,fw,min_depth=None):
    n,labels,stats,_=cv2.connectedComponentsWithStats(binary.astype(np.uint8),8)
    result=np.zeros(binary.shape,bool)
    for i in range(1,n):
        x,y,w,h,area=stats[i]
        if area<2 or max(w,h)>fw*.09 or max(w,h)/max(1,min(w,h))>3.5:continue
        if area/(w*h)<.25:continue
        result[labels==i]=True
    return result

def candidates(session,fi):
    cached=getattr(session,'detail_candidates',{})
    if fi in cached:return cached[fi]
    f=session.faces[fi];a,b,c,d=f.box;rgb=session.original[b:d,a:c].astype(np.float32)
    lab=cv2.cvtColor(rgb/255,cv2.COLOR_RGB2LAB);light=lab[:,:,0];safe=f.mask>.8
    local=cv2.GaussianBlur(light,(0,0),max(1,f.width*.014));dark=local-light
    prob=session.probabilities[fi]
    spots=blobs((dark>2.5)&safe&((prob>.15)|(dark>4.5)),f.width)
    deep=blobs((dark>10)&safe,f.width)
    acne=(prob>=session.confidence)&safe
    sweat=blobs((light-local>7)&(light>70)&safe,f.width)
    p=f.points-[a,b];down=p[152]-p[10];down=down/max(1,np.linalg.norm(down))
    yy,xx=np.mgrid[:d-b,:c-a];dx=xx-p[13,0];dy=yy-p[13,1]
    mouth_band=(dx*down[0]+dy*down[1]>-f.width*.10)&(dx*down[0]+dy*down[1]<f.width*.36)
    fine=cv2.GaussianBlur(light,(0,0),max(.7,f.width*.003))
    beard=(dark>2.8)&(local-fine>1.3)&safe&mouth_band
    chroma=np.linalg.norm(lab[:,:,1:3],axis=2)
    centre=float(np.median(chroma[safe])) if safe.any() else 0
    makeup=safe&(chroma>centre+12)
    nose=(session.part_labels[fi]==10)&safe
    # Bright particles inside a cavity can be repaired. Never classify the
    # whole dark nostril, its rim, or deep natural cavity as an acne/mole.
    cavity=session.nostrils[fi]>0
    particle=blobs((light-local>9)&cavity,f.width)
    result={'blemish_all':acne|spots,'dark_spots':spots&~deep,'moles':deep,'sweat':sweat,
        'nose_debris':(spots&nose)|particle,'beard_remove':beard,'beard_protect':beard,'makeup_protect':makeup}
    if getattr(session,'retouch_engine',1)==2 and fi<len(getattr(session,'detail_protection',[])):
        guard=session.detail_protection[fi]
        protected=guard['features']|(guard['marks'] if getattr(session,'protect_dark_points',False) else False)
        for key in ('blemish_all','dark_spots','sweat'):result[key]&=~protected
    if not hasattr(session,'detail_candidates'):session.detail_candidates={}
    session.detail_candidates[fi]=result
    return result

def feature_mask(session,fi,key,layers):
    f=session.faces[fi];a,b,c,d=f.box;mask=candidates(session,fi)[key].copy()
    for layer in reversed(layers):
        if layer.get('feature_key')==key and layer.get('person_index')==fi:
            mask=layer['mask'][b:d,a:c].copy() if layer.get('enabled',True) else np.zeros_like(mask)
            break
    if key!='nose_debris':mask&=f.mask>.5
    else:mask&=(f.mask>.5)|(session.nostrils[fi]>0)
    return mask

def prepare_face_repairs(session,settings,layers,progress=None,cancel=None):
    from damo_engine import inpaint_portrait
    caches=dict(getattr(session,'detail_cache',{}))
    for fi,(f,values) in enumerate(zip(session.faces,settings)):
        enabled=[k for k,_,_,_ in FACE_REPAIR if values.get(k,0)>0]
        if not enabled:continue
        if cancel and cancel.is_set():raise RuntimeError('已取消，未应用面部细节。')
        masks={k:feature_mask(session,fi,k,layers) for k in enabled}
        selected=np.logical_or.reduce(list(masks.values()))
        a,b,c,d=f.box;src=session.original[b:d,a:c]
        if progress:progress(f'人像 {fi+1} · AI 正在修复细节候选…')
        generated,info=inpaint_portrait(src,selected,progress,cancel,precision=True,retouch_engine=getattr(session,'retouch_engine',1))
        caches[fi]={'mask':selected,'delta':generated-src.astype(np.float32),'types':enabled,'info':info}
    return caches

def apply_face_repairs(rgb,base,session,settings,layers,excluded=None):
    out=rgb;caches=getattr(session,'detail_cache',{})
    for fi,(f,values) in enumerate(zip(session.faces,settings)):
        if not any(values.get(k,0) for k,_,_,_ in FACE_REPAIR) or fi not in caches:continue
        a,b,c,d=f.box;cache=caches[fi];alpha=np.zeros(f.mask.shape,np.float32)
        for k,_,_,_ in FACE_REPAIR:
            if values.get(k,0):alpha=np.maximum(alpha,feature_mask(session,fi,k,layers)*values[k]/100)
        alpha*=cache['mask']
        if excluded is not None:alpha[excluded[b:d,a:c]]=0
        alpha*=soft_edge(alpha>0,1.5)
        if not alpha.any():continue
        delta=cache['delta']
        if values.get('texture_keep',0):
            low=cv2.GaussianBlur(delta,(0,0),max(.6,f.width*.002))
            delta=delta+(low-delta)*values['texture_keep']/100*.7
        if out is rgb:out=rgb.copy()
        src=rgb[b:d,a:c];desired=base[b:d,a:c]+delta
        changed=alpha>0;out[b:d,a:c][changed]=np.clip((src+(desired-src)*alpha[:,:,None])[changed],0,255)
    return out

def apply_face_details(rgb,base,session,settings):
    keys=('eye_bags','lip_lines','jaw_enhance')
    if not any(v.get(k,0) for v in settings for k in keys):return rgb
    out=rgb.copy()
    for fi,(f,v) in enumerate(zip(session.faces,settings)):
        if not any(v.get(k,0) for k in keys):continue
        a,b,c,d=f.box;src=rgb[b:d,a:c].astype(np.float32);p=f.points.astype(np.float32)-[a,b]
        lab=cv2.cvtColor(np.clip(src/255,0,1),cv2.COLOR_RGB2LAB);light=lab[:,:,0]
        down=p[152]-p[10];down/=max(1,np.linalg.norm(down));side=np.array([down[1],-down[0]])
        yy,xx=np.mgrid[:d-b,:c-a].astype(np.float32)
        def ellipse(center,rx,ry):
            dx=xx-center[0];dy=yy-center[1]
            return np.clip(1-((dx*side[0]+dy*side[1])/max(1,rx))**2-((dx*down[0]+dy*down[1])/max(1,ry))**2,0,1)
        change=np.zeros(light.shape,np.float32)
        if v.get('eye_bags',0):
            region=np.maximum(ellipse((p[33]+p[133])/2+down*f.width*.10,f.width*.14,f.width*.10),ellipse((p[263]+p[362])/2+down*f.width*.10,f.width*.14,f.width*.10))*f.mask
            low=cv2.GaussianBlur(light,(0,0),max(2,f.width*.017))
            broad=cv2.GaussianBlur(low,(0,0),max(3,f.width*.055))
            change+=np.clip(broad-low,-5,7)*region*v['eye_bags']/100*.65
        if v.get('lip_lines',0):
            lips=session.part_regions[fi]['lips'];soft=soft_edge(lips,max(1,f.width*.004))
            low=cv2.GaussianBlur(light,(0,0),max(.7,f.width*.0035))
            change+=np.clip(low-light,-4,5)*soft*v['lip_lines']/100*.65
        if v.get('jaw_enhance',0):
            band=np.zeros(light.shape,np.uint8)
            ids=[172,136,150,149,176,148,152,377,400,378,379,365,397]
            cv2.polylines(band,[p[ids].astype(np.int32)],False,1,max(1,round(f.width*.035)))
            change-=cv2.GaussianBlur(band.astype(np.float32),(0,0),max(1,f.width*.008))*f.mask*v['jaw_enhance']/100*3
        selected=np.abs(change)>1e-6
        if selected.any():
            lab[:,:,0]=np.clip(light+change,0,100);edited=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
            out[b:d,a:c][selected]=np.clip(edited[selected],0,255)
    return out

def protect_face_details(rgb,base,session,settings):
    if not any(v.get(k,0) for v in settings for k in ('beard_protect','makeup_protect')):return rgb
    out=rgb.copy()
    for fi,(f,v) in enumerate(zip(session.faces,settings)):
        if not (v.get('beard_protect',0) or v.get('makeup_protect',0)):continue
        a,b,c,d=f.box;protect=np.zeros(f.mask.shape,np.float32)
        for k in ('beard_protect','makeup_protect'):
            if v.get(k,0):protect=np.maximum(protect,candidates(session,fi)[k]*v[k]/100)
        target=out[b:d,a:c];keep=protect>0
        target[keep]=(target+(base[b:d,a:c]-target)*protect[:,:,None])[keep]
    return out

def face_repairs_pending(session,settings,layers):
    for fi,values in enumerate(settings):
        cache=getattr(session,'detail_cache',{}).get(fi)
        for k,_,_,_ in FACE_REPAIR:
            if not values.get(k,0):continue
            mask=feature_mask(session,fi,k,layers)
            if mask.any() and (cache is None or (mask&~cache['mask']).any()):return True
    return False
