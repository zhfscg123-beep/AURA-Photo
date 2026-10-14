"""Per-person body skin processing; experimental type candidates are labelled.

Parts are cached as small disconnected skin ROIs, not repeated full-image
model passes. Clothing/other persons are excluded; user mask edits persist.
"""
import hashlib
import cv2,numpy as np
from region_masks import soft_edge,part_mask
from feature_catalog import BODY,BODY_REPAIR,BODY_SKIN
from face_details import blobs

def body_blend(mask,face_width):
    """One photometric edge rule for every body tone/texture control."""
    # The photo edge is not a skin/background boundary. Replicate it rather
    # than fading confirmed skin just because the photo cropped through it.
    distance=cv2.distanceTransform(np.pad(mask.astype(np.uint8),1,mode='edge'),cv2.DIST_L2,5)[1:-1,1:-1]
    # Small hand/finger regions or a narrow user stroke need a usable centre;
    # a fixed face-scale feather otherwise suppresses nearly the whole stroke.
    edge=np.zeros(mask.shape,np.float32);count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
    for i in range(1,count):
        x,y,w,h,_=stats[i];selected=labels[y:y+h,x:x+w]==i;local=distance[y:y+h,x:x+w]
        width=max(1,min(max(3,face_width*.06),float(local[selected].max())*.45))
        edge[y:y+h,x:x+w][selected]=np.clip(local[selected]/width,0,1)
    return edge*edge*(3-2*edge)

def body_scope(session,fi,layers):
    mask=part_mask(session,fi,'body')
    for layer in reversed(layers):
        if layer.get('feature_key')=='body_skin' and layer.get('person_index')==fi:
            from smart_selection import refine
            mask=refine(layer['mask'],layer.get('parameters',{}).get('expand',0)).copy() if layer.get('enabled',True) else np.zeros_like(mask)
            break
    supplement=getattr(session,'body_beauty_include',{}).get(fi)
    if supplement is not None:mask|=supplement
    excluded=getattr(session,'body_beauty_exclude',{}).get(fi)
    if excluded is not None:mask&=~excluded
    owner=session.body_owner;mask&=(owner==0)|(owner==fi+1)
    # A manually extended body scope still cannot include another face.
    for f in session.faces:
        a,b,c,d=f.box;mask[b:d,a:c][f.mask>0]=False
    for f,labels in zip(session.faces,getattr(session,'part_labels',[])):
        from region_masks import facial_exclusion
        a,b,c,d=f.box;mask[b:d,a:c][facial_exclusion(f,labels)]=False
    return mask

def build_body_parts(session,fi,layers,neural=False,progress=None,cancel=None):
    scope=body_scope(session,fi,layers);signature=hashlib.sha256(np.packbits(scope)).hexdigest()
    old=getattr(session,'body_parts',{}).get(fi)
    if old and old['signature']==signature and (not neural or old['neural']):return old
    n,labels,stats,_=cv2.connectedComponentsWithStats(scope.astype(np.uint8),8)
    f=session.faces[fi];parts=[]
    for i in range(1,n):
        x,y,w,h,area=stats[i]
        if area<8:continue
        pad=max(3,round(f.width*.02));a,b=max(0,x-pad),max(0,y-pad);c,d=min(scope.shape[1],x+w+pad),min(scope.shape[0],y+h+pad)
        safe=scope[b:d,a:c]&(labels[b:d,a:c]==i);src=session.original[b:d,a:c]
        lab=cv2.cvtColor(src.astype(np.float32)/255,cv2.COLOR_RGB2LAB);light=lab[:,:,0]
        low=cv2.GaussianBlur(light,(0,0),max(1,f.width*.012));depth=low-light
        probability=np.zeros(safe.shape,np.float32)
        if neural:
            from damo_engine import detection_probability
            count=0
            for yy in range(0,d-b,448):
                for xx in range(0,c-a,448):
                    if not safe[yy:yy+448,xx:xx+448].any():continue
                    count+=1
                    if count>64:raise ValueError('身体区域较大，请分批使用局部修复。')
                    if cancel and cancel.is_set():raise RuntimeError('已取消身体处理。')
                    z,t=min(c-a,xx+512),min(d-b,yy+512)
                    if progress:progress(f'人像 {fi+1} · 身体瑕疵检测 {count}…')
                    p=detection_probability(src,(xx,yy,z,t),getattr(session,'retouch_engine',1))
                    probability[yy:t,xx:z]=np.maximum(probability[yy:t,xx:z],p)
        dark=blobs((depth>3)&safe,f.width);deep=blobs((depth>11)&safe,f.width)
        chroma=lab[:,:,1:3];baseline=np.median(chroma[safe],axis=0)
        ink=((depth>6)|(np.linalg.norm(chroma-baseline,axis=2)>12))&safe
        ink=cv2.morphologyEx(ink.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))>0
        candidates={'body_spots':((probability>.35)&safe)|dark,'body_moles':deep,'body_tattoo':ink&safe}
        parts.append({'box':[a,b,c,d],'mask':safe,'candidates':candidates})
    data={'parts':parts,'signature':signature,'neural':neural}
    if not hasattr(session,'body_parts'):session.body_parts={}
    session.body_parts[fi]=data
    return data

def body_feature_mask(session,fi,key,layers,progress=None,cancel=None,allow_inference=True):
    if key=='body_skin':return body_scope(session,fi,layers)
    for layer in reversed(layers):
        if layer.get('feature_key')==key and layer.get('person_index')==fi:
            return (layer['mask']&body_scope(session,fi,layers)) if layer.get('enabled',True) else np.zeros(session.original.shape[:2],bool)
    data=(build_body_parts(session,fi,layers,neural=key=='body_spots',progress=progress,cancel=cancel)
          if allow_inference else getattr(session,'body_parts',{}).get(fi))
    mask=np.zeros(session.original.shape[:2],bool)
    if data is None:return mask
    for p in data['parts']:
        a,b,c,d=p['box'];mask[b:d,a:c]|=p['candidates'][key]
    return mask

def prepare_body(session,settings,layers,progress=None,cancel=None):
    from damo_engine import inpaint_portrait
    from ai_engine import inpaint_selected
    if any(v.get('clavicle',0) for v in settings):
        from person_masks import ensure_body_owners
        ensure_body_owners(session,need_pose=True)
    for fi,v in enumerate(settings):
        if not any(v.get(k,0) for k,_,_,_ in BODY):continue
        data=build_body_parts(session,fi,layers,neural=v.get('body_spots',0)>0,progress=progress,cancel=cancel)
        requested=[k for k,_,_,_ in BODY_REPAIR if v.get(k,0)>0]
        if not requested:continue
        masks={k:body_feature_mask(session,fi,k,layers,progress,cancel) for k in requested}
        for p in data['parts']:
            a,b,c,d=p['box'];selected=np.zeros(p['mask'].shape,bool);tattoo=np.zeros_like(selected)
            for k,m in masks.items():
                selected|=m[b:d,a:c]
                if k=='body_tattoo':tattoo|=m[b:d,a:c]
            src=session.original[b:d,a:c]
            if cancel and cancel.is_set():raise RuntimeError('已取消身体修复。')
            if not selected.any():
                p['repaired_mask']=selected
                continue
            if tattoo.any():generated,info=inpaint_selected(src,selected,progress,cancel,precision=True)
            else:generated,info=inpaint_portrait(src,selected,progress,cancel,precision=True,retouch_engine=getattr(session,'retouch_engine',1))
            p['repaired_mask']=selected;p['delta']=generated.astype(np.float32)-src.astype(np.float32);p['info']=info
    return getattr(session,'body_parts',{})

def body_pending(session,settings,layers):
    for fi,v in enumerate(settings):
        if not any(v.get(k,0) for k,_,_,_ in BODY_REPAIR):continue
        scope=body_scope(session,fi,layers)
        # Empty scope is a recognition/selection issue, not a neural job to
        # run repeatedly. Report it through body_notices instead.
        if not scope.any():continue
        data=getattr(session,'body_parts',{}).get(fi)
        if data is None:return True
        if v.get('body_spots',0) and not data['neural']:return True
        ready=np.zeros_like(scope)
        for p in data['parts']:
            a,b,c,d=p['box'];ready[b:d,a:c]|=p['mask']
        gained=(scope&~ready).astype(np.uint8)
        if gained.any():
            n,_,stats,_=cv2.connectedComponentsWithStats(gained,8)
            if any(stats[i,4]>=8 for i in range(1,n)):return True
        for k,_,_,_ in BODY_REPAIR:
            if not v.get(k,0):continue
            target=body_feature_mask(session,fi,k,layers,allow_inference=False);prepared=np.zeros_like(scope)
            for p in data['parts']:
                a,b,c,d=p['box'];prepared[b:d,a:c]|=p.get('repaired_mask',np.zeros(p['mask'].shape,bool))
            if (target&~prepared).any():return True
    return False

def body_notices(session,settings,layers):
    """Explain an unavailable selection separately from pending repair work."""
    messages=[]
    for fi,v in enumerate(settings):
        if not any(v.get(k,0) for k,_,_,_ in BODY):continue
        scope=body_scope(session,fi,layers)
        custom=any(l.get('feature_key')=='body_skin' and l.get('person_index')==fi for l in layers)
        if not scope.any():
            messages.append(f'人像 {fi+1} '+('身体范围蒙版为空或已关闭，请检查蒙版' if custom else '未找到可用身体皮肤，请补选范围'))
        elif not custom and fi not in getattr(session,'person_landmarks',{}):
            messages.append(f'人像 {fi+1} 已确认局部脖颈/耳朵，其他身体部位可补选')
        if v.get('clavicle',0) and fi not in getattr(session,'person_landmarks',{}):
            messages.append(f'人像 {fi+1} 锁骨增强尚缺可确认的肩部姿态')
    return messages

def apply_body(rgb,base,session,settings,layers):
    if not any(v.get(k,0) for v in settings for k,_,_,_ in BODY):return rgb
    out=rgb;cache=getattr(session,'body_parts',{})
    for fi,v in enumerate(settings):
        if not any(v.get(k,0) for k,_,_,_ in BODY):continue
        # Photometric controls need only cached ownership + CPU region setup,
        # not the explicit neural blemish-repair button. This also refreshes
        # a formerly empty cache when a confirmed neck has been recovered.
        if any(v.get(k,0) for k,_,_,_ in BODY_SKIN):
            data=build_body_parts(session,fi,layers,neural=False)
            cache=getattr(session,'body_parts',{})
        if fi not in cache:continue
        f=session.faces[fi];a,b,c,d=f.box;face_lab=cv2.cvtColor(np.clip(rgb[b:d,a:c].astype(np.float32)/255,0,1),cv2.COLOR_RGB2LAB)
        face_tone=np.median(face_lab[f.mask>.8],axis=0) if (f.mask>.8).sum()>=20 else None
        scope=body_scope(session,fi,layers)
        repair_masks={k:body_feature_mask(session,fi,k,layers,allow_inference=False) for k,_,_,_ in BODY_REPAIR if v.get(k,0)>0}
        for part in cache[fi]['parts']:
            a,b,c,d=part['box'];src=rgb[b:d,a:c].astype(np.float32);mask=part['mask']&scope[b:d,a:c]
            if not mask.any():continue
            # Broad, smooth photometric falloff at face/neck, clothing and
            # hair boundaries; repair selections keep their separate alpha.
            edited=src.copy();alpha=body_blend(mask,f.width)
            repair=np.zeros(mask.shape,np.float32)
            for k,m in repair_masks.items():repair=np.maximum(repair,m[b:d,a:c]*v[k]/100)
            repair*=part.get('repaired_mask',np.zeros(mask.shape,bool))
            if repair.any():
                target=base[b:d,a:c]+part['delta'];edited+=(target-edited)*repair[:,:,None]
            if not any(v.get(k,0) for k,_,_,_ in BODY_SKIN if k not in ('sample_body','color_body','match_body_bright')):
                if not repair.any():continue
                if out is rgb:out=rgb.copy()
                selected=(repair>0)&mask;weight=soft_edge(selected,1.5)
                out[b:d,a:c][selected]=np.clip((src+(edited-src)*weight[:,:,None])[selected],0,255)
                continue
            lab=cv2.cvtColor(np.clip(edited/255,0,1),cv2.COLOR_RGB2LAB);light=lab[:,:,0].copy()
            fine=cv2.GaussianBlur(light,(0,0),max(.7,f.width*.003));low=cv2.GaussianBlur(fine,(0,0),max(2,f.width*.016))
            lab[:,:,0]+=(low-fine)*(v.get('body_smooth',0)*.5+v.get('body_lf',0)*.35)/100
            lab[:,:,0]+=(light-fine)*v.get('body_hf',0)/100*.5
            lab[:,:,0]+=(fine-light)*v.get('body_hydrate',0)/100*.4
            lab[:,:,0]+=np.clip((98-light)/24,0,1)*v.get('body_whiten',0)/100*7
            lab[:,:,0]+=np.clip((100-light)/65,0,1)*v.get('body_translucent',0)/100*4
            if v.get('body_even',0):
                for ch in (1,2):
                    blurred=cv2.GaussianBlur(lab[:,:,ch],(0,0),max(2,f.width*.018))
                    lab[:,:,ch]+=np.clip(np.median(blurred[mask])-blurred,-6,6)*v['body_even']/100*.6
            if v.get('body_to_face',0) and face_tone is not None:
                median=np.median(lab[mask],axis=0);difference=np.clip(face_tone-median,[-8,-6,-6],[8,6,6])
                lab+=difference*v['body_to_face']/100*.65
            lab[:,:,1]+=v.get('body_redness',0)/100*3+v.get('body_tint',0)/100*3
            lab[:,:,2]+=v.get('body_temp',0)/100*5
            yy,xx=np.mgrid[b:d,a:c];p=f.points.astype(np.float32);down=p[152]-p[10];down/=max(1,np.linalg.norm(down));side=np.array([down[1],-down[0]])
            center=p[152]+down*f.width*.20;dx=xx-center[0];dy=yy-center[1]
            neck=np.clip(1-((dx*side[0]+dy*side[1])/(f.width*.33))**2-((dx*down[0]+dy*down[1])/(f.width*.32))**2,0,1)
            depth=np.clip(fine-light,0,8)
            lab[:,:,0]+=depth*neck*v.get('neck_wrinkles',0)/100*.65
            if v.get('stretch_marks',0):
                band=np.clip(np.abs(fine-low)-1.2,0,4)/4
                lab[:,:,0]+=np.clip(low-fine,-6,6)*band*v['stretch_marks']/100*.5
            if v.get('clavicle',0):
                pose=getattr(session,'person_landmarks',{}).get(fi)
                if pose is not None and min(pose[11,2],pose[12,2])>.7:
                    l,r=pose[11,:2],pose[12,:2];axis=r-l;length=max(1,np.linalg.norm(axis));normal=np.array([-axis[1],axis[0]])/length
                    if normal@down<0:normal=-normal
                    centre=(l+r)/2-normal*length*.12;ddx=xx-centre[0];ddy=yy-centre[1]
                    across=(ddx*axis[0]+ddy*axis[1])/length;along=ddx*normal[0]+ddy*normal[1]
                    band=np.exp(-(along/(length*.025+1))**2)*np.clip(1-(across/(length*.38+1))**2,0,1)
                    lab[:,:,0]+=(band-cv2.GaussianBlur(band.astype(np.float32),(0,0),max(1,length*.04)))*v['clavicle']/100*3
            lab[:,:,0]=np.clip(lab[:,:,0],0,100);desired=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
            if out is rgb:out=rgb.copy()
            selected=alpha>0;out[b:d,a:c][selected]=np.clip((src+(desired-src)*alpha[:,:,None])[selected],0,255)
    return out
