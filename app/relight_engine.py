"""Per-person offline geometric lighting; bounded caches and native FP32 pixels.

Transport coefficients are cached at the model's spatial scale. The original
RGB is never replaced by a generated/downsampled photograph. Current edited
RGB supplies reflectance proxies and is composited at source resolution.
"""
from collections import OrderedDict
import hashlib,json,threading
import numpy as np,cv2
from core import OVAL
import relight_math as math
from relight_settings import checked,active,renderer_lamp

_geometry=OrderedDict();_fields=OrderedDict();_lock=threading.RLock();_build_lock=threading.RLock()
GEOMETRY_BUDGET=256*1024**2;FIELD_BUDGET=96*1024**2
_stats=dict(geometry_builds=0,geometry_hits=0,field_builds=0,field_hits=0)

def _bytes(v):return sum(x.nbytes for x in v.values() if isinstance(x,np.ndarray))
def _put(cache,key,value,budget):
    cache[key]=value
    while len(cache)>1 and sum(_bytes(v) for v in cache.values())>budget:cache.popitem(last=False)
def cache_info():
    with _lock:return dict(_stats,geometry_bytes=sum(_bytes(x) for x in _geometry.values()),field_bytes=sum(_bytes(x) for x in _fields.values()))
def clear_cache():
    with _lock:_geometry.clear();_fields.clear()

def person_box(session,fi,masks):
    f=session.faces[fi];h,w=session.original.shape[:2]
    polygon=f.points[OVAL].astype(float);lo=polygon.min(0);hi=polygon.max(0);center=(lo+hi)*.5
    side=np.max(hi-lo)*2.4;center[1]+=side*.10
    a,b=np.floor(center-side*.5).astype(int);c,d=np.ceil(center+side*.5).astype(int)
    selected=masks['person']|masks['light']|masks['clothes']
    pts=cv2.findNonZero(selected.astype(np.uint8))
    if pts is not None:
        x,y,rh,rv=cv2.boundingRect(pts);pad=max(4,round(f.width*.10))
        a=min(a,x-pad);b=min(b,y-pad);c=max(c,x+rh+pad);d=max(d,y+rv+pad)
    return (max(0,a),max(0,b),min(w,c),min(h,d))

def _masks(session,fi,m,box):
    a,b,c,d=box;h,w=d-b,c-a
    skin=m['light'][b:d,a:c].astype(np.float32);hair=m['hair'][b:d,a:c].astype(np.float32)
    person=(m['person']|m['clothes']|m['light'])[b:d,a:c].astype(np.float32)
    guard=np.zeros((h,w),np.float32);lips=np.zeros_like(guard);brows=np.zeros_like(guard)
    f=session.faces[fi];fa,fb,fc,fd=f.box
    x,y,z,t=max(a,fa),max(b,fb),min(c,fc),min(d,fd)
    if x<z and y<t:
        parts=session.part_regions[fi];labels=session.part_labels[fi]
        protected=parts['eyes']|(session.nostrils[fi]>0)|(labels==11)
        protected=cv2.dilate(protected.astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
        patch=np.s_[y-fb:t-fb,x-fa:z-fa];dest=np.s_[y-b:t-b,x-a:z-a]
        guard[dest]=protected[patch];lips[dest]=parts['lips'][patch];brows[dest]=parts['brows'][patch]
        # Face lighting uses the existing editable beauty envelope, including
        # lip/brow material, while eye/cavity protection remains independent.
        skin[dest][protected[patch]]=0
    skin*=1-guard
    return dict(skin=skin,hair=hair,person=person,feature_guard=guard,lip_mask=lips,brow_mask=brows)

def _geometry_for(session,fi,masks,progress=None):
    box=person_box(session,fi,masks);a,b,c,d=box
    original=np.ascontiguousarray(session.original[b:d,a:c]);mask=_masks(session,fi,masks,box)
    signature=hashlib.blake2b(original.tobytes(),digest_size=20)
    for name,v in sorted(mask.items()):signature.update(name.encode());signature.update(v.tobytes())
    from relight_models import CACHE_ID
    key=(5,CACHE_ID,box,signature.hexdigest())
    stored=getattr(session,'relight_cache',{}).get(fi)
    if stored is not None and stored.get('key')==key:
        with _lock:_stats['geometry_hits']+=1;_put(_geometry,key,stored['geometry'],GEOMETRY_BUDGET)
        return key,stored['geometry'],box,mask
    with _lock:
        if key in _geometry:
            _stats['geometry_hits']+=1;g=_geometry.pop(key);_geometry[key]=g;return key,g,box,mask
    with _build_lock:
        with _lock:
            if key in _geometry:_stats['geometry_hits']+=1;return key,_geometry[key],box,mask
        from relight_models import predict
        factor=min(1,1024/max(original.shape[:2]));size=(max(4,round(original.shape[1]*factor)),max(4,round(original.shape[0]*factor)))
        small=cv2.resize(original,size,interpolation=cv2.INTER_AREA)
        depth,normal,confidence=predict(small,progress)
        # Full-body photographs need a head-scale pass; coarse whole-person
        # geometry alone made the face too small for useful light placement.
        f=session.faces[fi]
        if f.width/max(c-a,d-b)<.30:
            poly=f.points[OVAL].astype(float);lo=poly.min(0);hi=poly.max(0);center=(lo+hi)/2;side=np.max(hi-lo)*2.4;center[1]+=side*.1
            x,y=np.maximum(np.floor(center-side/2).astype(int),[a,b]);z,t=np.minimum(np.ceil(center+side/2).astype(int),[c,d])
            if x<z and y<t:
                if progress:progress('正在细化面部受光方向…')
                rgb=np.ascontiguousarray(session.original[y:t,x:z]);s=min(1,1024/max(rgb.shape[:2]));head=cv2.resize(rgb,(max(4,round(rgb.shape[1]*s)),max(4,round(rgb.shape[0]*s))),interpolation=cv2.INTER_AREA)
                hd,hn,hc=predict(head,progress)
                x0,y0=max(0,round((x-a)*factor)),max(0,round((y-b)*factor));x1,y1=min(size[0],round((z-a)*factor)),min(size[1],round((t-b)*factor))
                if x0<x1 and y0<y1:
                    shp=(x1-x0,y1-y0);hd=cv2.resize(hd,shp);hn=cv2.resize(hn,shp);hc=cv2.resize(hc,shp)
                    old=depth[y0:y1,x0:x1];oq=np.percentile(old,[10,50,90]);hq=np.percentile(hd,[10,50,90])
                    gain=np.clip((oq[2]-oq[0])/max(1e-6,hq[2]-hq[0]),.05,20);hd=hd*gain+(oq[1]-gain*hq[1])
                    yy,xx=np.mgrid[:shp[1],:shp[0]].astype(np.float32)
                    edge=np.minimum.reduce([xx,yy,shp[0]-1-xx,shp[1]-1-yy]);fade=np.clip(edge/max(2,min(shp)*.15),0,1)
                    normal[y0:y1,x0:x1]=math.unit(normal[y0:y1,x0:x1]*(1-fade[:,:,None])+hn*fade[:,:,None])
                    depth[y0:y1,x0:x1]=old*(1-fade)+hd*fade
                    confidence[y0:y1,x0:x1]=confidence[y0:y1,x0:x1]*(1-fade)+hc*fade
        reduced={name:cv2.resize(v,size,interpolation=cv2.INTER_AREA).astype(np.float32) for name,v in mask.items()}
        valid=np.linalg.norm(normal,axis=2)>.5
        g=math.prepare_geometry(depth,normal,reduced['hair']*valid,reduced['skin']*valid,small)
        g=math.controls(small,g,reduced['person'])
        g.update(feature_guard=reduced['feature_guard'],lip_mask=reduced['lip_mask'],brow_mask=reduced['brow_mask'])
        g['confidence']=confidence
        g['skin_fill']*=1-g['feature_guard'];g['scope']=np.maximum(g['skin_fill'],g['hair'])*(1-g['feature_guard'])*valid
        for v in g.values():
            if isinstance(v,np.ndarray):v.flags.writeable=False
        with _lock:_stats['geometry_builds']+=1;_put(_geometry,key,g,GEOMETRY_BUDGET)
    return key,g,box,mask

def _coefficients(geo_key,g,lamp):
    # Color and power are applied after transport, so changing either reuses
    # the same 16-sample light field immediately.
    shape={k:v for k,v in lamp.items() if k not in ['power','color','color_hex','temperature','tint','saturation','color_mix','enabled',
        'shadow_priority','highlight_protect','geometry_protect']}
    key=(geo_key,json.dumps(shape,sort_keys=True))
    with _lock:
        if key in _fields:_stats['field_hits']+=1;v=_fields.pop(key);_fields[key]=v;return v
    h,w=g['z'].shape;factor=min(1,640/max(h,w));size=(max(4,round(w*factor)),max(4,round(h*factor)))
    gg=math.native_geometry(g,(size[1],size[0]))
    light=dict(shape,power=1,enabled=True,color=[1,1,1],hair_gloss=0,hair_transmission=0)
    black=np.zeros((size[1],size[0],3),np.float32);white=np.full_like(black,255)
    no_rim=dict(light,rim_gain=0)
    s=math.contribution(black,gg,dict(lights=[no_rim]))[:,:,0]
    d=math.contribution(white,gg,dict(lights=[no_rim]))[:,:,0]-s
    if light['type']=='back':r=math.contribution(white,gg,dict(lights=[light]))[:,:,0]-d-s
    else:r=np.zeros_like(d)
    value=dict(diffuse=np.maximum(d,0),specular=np.maximum(s,0),rim=np.maximum(r,0))
    for v in value.values():v.flags.writeable=False
    with _lock:_stats['field_builds']+=1;_put(_fields,key,value,FIELD_BUDGET)
    return value

def allocation(coarse,max_channel,confidence,lamp):
    """Bounded spatial energy policy, independent of the V1 display response."""
    t=np.clip((coarse-.06)/.5,0,1);t=t*t*(3-2*t)
    shadow=1+.25*lamp.get('shadow_priority',0)*(1-t)
    highlight=1-lamp.get('highlight_protect',0)*max_channel**4
    reliable=1-lamp.get('geometry_protect',0)*(1-confidence)
    return np.clip(shadow*highlight*reliable,0,1.25).astype(np.float32)

def apply(rgb,session,fi,masks,rig,progress=None):
    settings=checked(rig)
    if not active(settings):return rgb
    key,g,box,mask=_geometry_for(session,fi,masks,progress);a,b,c,d=box
    current=getattr(session,'relight_cache',{})
    if fi not in current or current[fi]['key']!=key:
        session.relight_cache=dict(current,**{})
        session.relight_cache[fi]=dict(key=key,geometry=g)
    source=rgb[b:d,a:c].astype(np.float32);normal=math.linear(source);energy=np.zeros_like(source)
    luminance=normal@np.array([.2126,.7152,.0722],np.float32)
    coarse=cv2.GaussianBlur(luminance,(0,0),max(1,session.faces[fi].width*.012))
    confidence=cv2.resize(g['confidence'],(c-a,d-b),interpolation=cv2.INTER_LINEAR)
    for v in settings['lights']:
        if not v['enabled'] or v['power']<=0:continue
        lamp=renderer_lamp(v)
        if progress:progress('正在更新 '+v['name']+'…')
        fields=_coefficients(key,g,lamp);size=(c-a,d-b)
        D=cv2.resize(fields['diffuse'],size,interpolation=cv2.INTER_LINEAR)
        S=cv2.resize(fields['specular'],size,interpolation=cv2.INTER_LINEAR)
        R=cv2.resize(fields['rim'],size,interpolation=cv2.INTER_LINEAR)
        amount=normal*D[:,:,None]+S[:,:,None]+np.maximum(normal,0)**.65*R[:,:,None]
        allowed=mask['person'] if v['scope']=='person' else mask['skin']
        amount*=allowed[:,:,None]*(1-mask['feature_guard'][:,:,None])
        # These controls change spatial light allocation, not the approved
        # V1 intensity/display curve. Shadow emphasis is capped at +25%.
        amount*=allocation(coarse,np.max(normal,axis=2),confidence,v)[:,:,None]
        energy+=amount*float(v['power'])*math.light_rgb(lamp)
    result=rgb.copy();result[b:d,a:c]=math.compose(source,energy)
    if not np.isfinite(result).all():raise ValueError('补光输出包含无效数值。')
    if progress:progress('几何补光已更新 · 复用深度与法线缓存')
    return result
