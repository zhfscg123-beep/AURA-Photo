"""Landmark-guided local retouch; face-only warping with LaMa hole completion."""
import numpy as np
import cv2
from core import OVAL,FEATURES
from ai_engine import inpaint_selected,square_box
from skin_enhance import wrinkle_zone_strength,eye_wrinkle_region
from region_masks import face_beauty_mask,soft_edge
from beauty_settings import ZONES

def region_mask(points,shape,ids):
    mask=np.zeros(shape,np.uint8);cv2.fillPoly(mask,[np.rint(points[ids]).astype(np.int32)],1);return mask

def wrinkle_skin_scope(session,fi):
    """Geometric/semantic protection, independent from the retired ridge lift."""
    f=session.faces[fi];a,b,_,_=f.box;p=f.points.astype(np.float32)-[a,b];fw=f.width
    beauty=face_beauty_mask(session,fi)>0;guard=np.zeros(beauty.shape,np.uint8)
    for ids in FEATURES[:2]:cv2.fillConvexPoly(guard,cv2.convexHull(p[ids].astype(np.int32)),1)
    radius=max(2,round(fw*.009));guard=cv2.dilate(guard,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,)*2))
    down=p[152]-p[10];down/=max(1,np.linalg.norm(down))
    for ids in ([33,246,161,160,159,158,157,173,133],[263,466,388,387,386,385,384,398,362]):
        edge=p[ids];band=np.concatenate((edge+down*fw*.007,(edge-down*fw*.030)[::-1]))
        cv2.fillPoly(guard,[np.rint(band).astype(np.int32)],1)
    safe=beauty&(guard==0)&~np.isin(session.part_labels[fi],[2,3,6,9,11,12,13,17,18])&(session.nostrils[fi]==0)
    return safe,guard>0

def eye_wrinkle_lift(light,session,fi,whole_face=False):
    """Multi-scale shallow dark ridges within a landmark-guided lower-eye band.

    Wrinkle candidates are image features, not a wrinkle-trained neural model.
    Correct luminance only and keep eye openings, lashes, brows and hair safe.
    """
    f=session.faces[fi];fw=f.width;a,b,_,_=f.box;p=f.points.astype(np.float32)-[a,b]
    region=np.ones(light.shape,np.float32) if whole_face else eye_wrinkle_region(f)
    beauty=face_beauty_mask(session,fi)>0
    guard=np.zeros(light.shape,np.uint8)
    for ids in FEATURES[:2]:cv2.fillConvexPoly(guard,cv2.convexHull(p[ids].astype(np.int32)),1)
    # A wide symmetric eye guard also preserved the lower crease itself,
    # leaving a colored strip when the skin immediately below was repaired.
    radius=max(2,round(fw*.009))
    guard=cv2.dilate(guard,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1)))
    down=p[152]-p[10];down/=max(1,np.linalg.norm(down))
    for ids in ([33,246,161,160,159,158,157,173,133],[263,466,388,387,386,385,384,398,362]):
        upper=p[ids];lash_band=np.concatenate((upper+down*fw*.007,(upper-down*fw*.030)[::-1]))
        cv2.fillPoly(guard,[np.rint(lash_band).astype(np.int32)],1)
    labels=session.part_labels[fi]
    safe=beauty&(guard==0)&~np.isin(labels,[2,3,6,9,11,12,13,17,18])&(session.nostrils[fi]==0)
    allowed=safe&(region>.02);lift=np.zeros(light.shape,np.float32)
    for fraction in (.0015,.003,.0055):
        sigma=max(.55,fw*fraction);fine=cv2.GaussianBlur(light,(0,0),sigma)
        r=max(2,round(sigma*3.5));kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*r+1,2*r+1))
        depth=cv2.morphologyEx(fine,cv2.MORPH_BLACKHAT,kernel)
        # Hessian coherence rejects round pores and broad illumination ramps.
        xx=cv2.Sobel(fine,cv2.CV_32F,2,0,ksize=3)/4
        yy=cv2.Sobel(fine,cv2.CV_32F,0,2,ksize=3)/4
        xy=cv2.Sobel(fine,cv2.CV_32F,1,1,ksize=3)/4
        gap=np.sqrt((xx-yy)**2+4*xy**2)
        major=(xx+yy+gap)*.5;minor=(xx+yy-gap)*.5
        ridge=(major>.015)&(np.abs(minor)<major*.65)
        candidates=((depth>.30)&ridge&allowed).astype(np.uint8)
        count,cc,stats,_=cv2.connectedComponentsWithStats(candidates,8);lines=np.zeros(light.shape,np.uint8)
        for idx in range(1,count):
            x,y,w,h,area=stats[idx]
            if area>=3 and max(w,h)>=max(4,fw*.006):lines[y:y+h,x:x+w][cc[y:y+h,x:x+w]==idx]=1
        spread=cv2.dilate(lines,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*max(1,round(sigma))+1,)*2))
        soft=cv2.GaussianBlur(spread.astype(np.float32),(0,0),max(.65,sigma*.6))
        confidence=np.clip((depth-.15)/.8,0,1)
        lift=np.maximum(lift,np.minimum(depth,8)*soft*confidence)
    boundary=cv2.distanceTransform(np.pad(safe.astype(np.uint8),1),cv2.DIST_L2,5)[1:-1,1:-1]
    fade=np.clip(boundary/max(2,fw*.006),0,1)
    return np.minimum(lift*region*fade*allowed*1.6,9),allowed,guard>0

EYE_REPAIR_REVISION=15

def compact_dark_marks(light,safe,fw):
    """Protect distinct rounded dark marks, not shallow crease fragments."""
    darkness=cv2.GaussianBlur(light,(0,0),max(2,fw*.009))-light
    count,cc,stats,_=cv2.connectedComponentsWithStats(((darkness>3)&safe).astype(np.uint8),8)
    compact=np.zeros(safe.shape,np.uint8)
    for idx in range(1,count):
        x,y,w,h,area=stats[idx]
        if area<4 or max(w,h)>fw*.04 or max(w,h)>1.8*max(1,min(w,h)) or area/(w*h)<.4:continue
        local=cc[y:y+h,x:x+w]==idx;depth=darkness[y:y+h,x:x+w][local]
        # Low-contrast pore/crease shadows must remain repairable; protecting
        # them exactly while lifting neighboring skin made new-looking spots.
        if np.median(depth)<6 or np.percentile(depth,90)<10:continue
        coords=np.column_stack(np.where(local));eigen=np.linalg.eigvalsh(np.cov(coords.T))
        if eigen[-1]<2.5*max(.1,eigen[0]):compact[y:y+h,x:x+w][local]=1
    r=max(1,round(fw*.0025))
    context=cv2.dilate(compact,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(r*2+1,r*2+1)))>0
    return compact>0,context

def skin_context_blur(values,valid,sigma):
    """Estimate skin tone without letting a protected mole darken its neighbors."""
    weight=valid.astype(np.float32)
    denominator=cv2.GaussianBlur(weight,(0,0),sigma)
    numerator=cv2.GaussianBlur(values*weight[:,:,None],(0,0),sigma)
    result=numerator/np.maximum(denominator[:,:,None],1e-5)
    result[denominator<.05]=values[denominator<.05]
    return result

def lower_cheek_chroma(lab,f,healthy):
    """Sample below the orbital pigmentation, independently for both eyes."""
    a,b,c,d=f.box;p=f.points.astype(np.float32)-[a,b];fw=f.width
    down=p[152]-p[10];down/=max(1,np.linalg.norm(down))
    h,w=healthy.shape;yy,xx=np.mgrid[:h,:w].astype(np.float32)
    refs=[];weights=[];stats=[]
    for ids in ([33,7,163,144,145,153,154,155,133],[263,249,390,373,374,380,381,382,362]):
        edge=p[ids];donor=np.zeros((h,w),np.uint8)
        band=np.concatenate((edge+down*fw*.17,(edge+down*fw*.29)[::-1]))
        cv2.fillPoly(donor,[np.rint(band).astype(np.int32)],1)
        usable=(donor>0)&(healthy>0)
        if usable.sum()<20:continue
        colors=lab[usable,1:3];median=np.median(colors,axis=0)
        # Exclude colored blemishes, hair shadows and extreme sample outliers.
        usable&=np.linalg.norm(lab[:,:,1:3]-median,axis=2)<8
        if usable.sum()<20:continue
        tone=np.median(lab[usable],axis=0)
        # Preserve the cheek's local pink/warm gradient instead of copying
        # one median color across the entire crescent. Extrapolation is small.
        dy,dx=np.where(usable);origin=np.array([dx.mean(),dy.mean()])
        design=np.column_stack(((dx-origin[0])/fw,(dy-origin[1])/fw,np.ones(len(dx))))
        coefficients=np.linalg.lstsq(design,lab[usable,1:3],rcond=None)[0]
        gradient=((xx-origin[0])/fw)[:,:,None]*np.clip(coefficients[0],-12,12)+((yy-origin[1])/fw)[:,:,None]*np.clip(coefficients[1],-12,12)
        field=np.empty(lab.shape,np.float32);field[:,:,0]=tone[0]
        field[:,:,1:]=tone[1:]+np.clip(gradient,-2,2)
        center=edge.mean(axis=0)+down*fw*.075
        distance=((xx-center[0])**2+(yy-center[1])**2)/(fw*.16)**2
        weights.append(np.exp(-distance*2).astype(np.float32));refs.append(field)
        stats.append(dict(pixels=int(usable.sum()),lab=tuple(float(x) for x in tone)))
    if not refs:return None,stats
    denominator=sum(weights);reference=sum(q[:,:,None]*v for q,v in zip(weights,refs))/np.maximum(denominator[:,:,None],1e-8)
    return reference.astype(np.float32),stats

def gamut_safe_lift(lab,lift):
    """Avoid clipping a bright RGB channel into an orange/red color shift."""
    result=lift.copy();mask=lift>1e-6
    values=lab[mask];amount=lift[mask]
    if not len(values):return result
    def valid(delta):
        fy=(values[:,0]+delta+16)/116
        xyz=np.column_stack((fy+values[:,1]/500,fy,fy-values[:,2]/200))
        xyz=np.where(xyz>6/29,xyz**3,3*(6/29)**2*(xyz-4/29))*[.950456,1,1.088754]
        linear=xyz@np.array([[3.240479,-.969256,.055648],[-1.537150,1.875991,-.204043],[-.498535,.041556,1.057311]])
        return (linear.min(axis=1)>=.00001)&(linear.max(axis=1)<=.9999)
    constrained=~valid(amount);low=np.zeros(len(amount),np.float32);high=amount.copy()
    for _ in range(10):
        mid=(low+high)/2;inside=valid(mid);low=np.where(inside,mid,low);high=np.where(inside,high,mid)
    amount[constrained]=low[constrained]
    result[mask]=amount;return result

def wrinkle_requested(values):
    return values.get('wrinkles',0)>0 or any(values.get(k,0)>0 for k,_,_,_ in ZONES)

def eye_wrinkle_pending(session,settings):
    caches=getattr(session,'eye_wrinkle_cache',{})
    return any(wrinkle_requested(v) and
        (i not in caches or caches[i].get('revision')!=EYE_REPAIR_REVISION)
        for i,v in enumerate(settings) if session.faces[i].points is not None)

def prepare_eye_wrinkles(session,settings,progress=None,cancel=None):
    """Cache original-coordinate protections; learn the blend from current RGB."""
    caches=dict(getattr(session,'eye_wrinkle_cache',{}))
    for fi,(f,v) in enumerate(zip(session.faces,settings)):
        if not wrinkle_requested(v) or f.points is None:continue
        if fi in caches and caches[fi].get('revision')==EYE_REPAIR_REVISION:continue
        a,b,c,d=f.box;src=session.original[b:d,a:c]
        lab=cv2.cvtColor(src.astype(np.float32)/255,cv2.COLOR_RGB2LAB)
        if cancel is not None and cancel.is_set():raise InterruptedError('已取消DAMO祛纹范围准备。')
        safe,guard=wrinkle_skin_scope(session,fi)
        compact,mark_context=compact_dark_marks(lab[:,:,0],safe,f.width)
        safe=safe&~mark_context
        if progress:progress(f'人像 {fi+1} · 准备DAMO祛纹保护范围…')
        fade=soft_edge(safe,max(3,f.width*.018))
        fade=fade*fade*(3-2*fade)
        alpha=fade.astype(np.float32);alpha[~safe]=0
        caches[fi]=dict(revision=EYE_REPAIR_REVISION,alpha=alpha,guard=guard,compact=compact,
            mark_context=mark_context,safe=safe,info={'model':'DAMO learned blend','extra_whitening':False,'legacy_luminance_lift':False})
    return caches

def chroma_preserving_lift(source,light,lift):
    """Raise luminance with a uniform linear-RGB gain, preserving chromaticity."""
    srgb=np.clip(source.astype(np.float32)/255,0,1)
    linear=np.where(srgb<=.04045,srgb/12.92,((srgb+.055)/1.055)**2.4)
    old_y=linear@np.array([.2126,.7152,.0722],np.float32)
    target_l=np.clip(light+lift,0,100)
    target_y=np.where(target_l>8,((target_l+16)/116)**3,target_l/903.3)
    gain=np.maximum(1,target_y/np.maximum(old_y,1e-8))
    # Shared channel headroom avoids hue changes caused by single-channel clipping.
    gain=np.minimum(gain,1/np.maximum(linear.max(2),1e-8))
    wanted=linear*gain[:,:,None]
    result=np.where(wanted<=.0031308,wanted*12.92,1.055*np.maximum(wanted,0)**(1/2.4)-.055)*255
    result[lift<=1e-6]=source[lift<=1e-6]
    return np.clip(result,0,255).astype(np.float32)

def wrinkle_and_circles(rgb,session,wrinkles=0,dark_circles=0,face_settings=None):
    """DAMO current-input blend in requested zones; no old orange-producing lift."""
    settings=face_settings if face_settings is not None else [dict(wrinkles=wrinkles,dark_circles=dark_circles) for _ in session.faces]
    if not any(wrinkle_requested(v) or v.get('dark_circles',0)>0 for v in settings):return rgb.copy()
    if eye_wrinkle_pending(session,settings):session.eye_wrinkle_cache=prepare_eye_wrinkles(session,settings)
    out=rgb.copy()
    for fi,(f,values) in enumerate(zip(session.faces,settings)):
        if f.points is None:continue
        a,b,c,d=f.box
        cache=getattr(session,'eye_wrinkle_cache',{}).get(fi)
        if wrinkle_requested(values) and cache is not None:
            opacity=np.clip(wrinkle_zone_strength(f,values)*cache['alpha'],0,1)
            opacity[cache['guard']|cache['mark_context']]=0
            if opacity.any():
                # Use the current pre-wrinkle image, including skin brightening,
                # rather than borrowing RGB/lightness deltas from the raw input.
                polygon=f.points[OVAL].astype(np.float32);lo=polygon.min(0);hi=polygon.max(0)
                center=(lo+hi)*.5;side=float(np.max(hi-lo))*1.5
                x,y=np.maximum(np.floor(center-side*.5).astype(int),[0,0])
                z,t=np.minimum(np.ceil(center+side*.5).astype(int),[rgb.shape[1],rgb.shape[0]])
                aa,bb,cc,dd=max(a,x),max(b,y),min(c,z),min(d,t)
                if aa<cc and bb<dd:
                    from damo_blend_engine import blend_map,compose
                    source=out[y:t,x:z].astype(np.float32)
                    weight=np.zeros(source.shape[:2],np.float32)
                    weight[bb-y:dd-y,aa-x:cc-x]=opacity[bb-b:dd-b,aa-a:cc-a]
                    corrected=compose(source,blend_map(source),weight)
                    active=weight>0;target=out[y:t,x:z]
                    target[active]=corrected[active] if np.issubdtype(out.dtype,np.floating) else np.rint(corrected[active]).astype(out.dtype)
        # Preserve the separate historical dark-circle API. It is not part of
        # the new wrinkle correction and defaults to zero in current recipes.
        amount=values.get('dark_circles',0)
        if amount>0:
            source=out[b:d,a:c].astype(np.float32);p=f.points.astype(np.float32)-[a,b]
            lab=cv2.cvtColor(np.clip(source/255,0,1),cv2.COLOR_RGB2LAB);light=lab[:,:,0]
            safe=(session.semantic_skin[fi]>0)&(f.protected==0)
            down=p[152]-p[10];down/=max(1,np.linalg.norm(down));region=np.zeros(light.shape,np.uint8)
            for ids in ([33,7,163,144,145,153,154,155,133],[263,249,390,373,374,380,381,382,362]):
                edge=p[ids];poly=np.concatenate((edge+down*f.width*.018,(edge+down*f.width*.105)[::-1]))
                cv2.fillPoly(region,[np.rint(poly).astype(np.int32)],1)
            soft=cv2.GaussianBlur(region.astype(np.float32),(0,0),max(1,f.width*.009))*safe
            local=cv2.GaussianBlur(light,(0,0),max(3,f.width*.05))
            lift=np.clip(local-light,0,10)*(amount/100)*.8*soft
            if cache is not None:lift[cache['guard']|cache['mark_context']]=0
            edited=chroma_preserving_lift(source,light,np.minimum(lift,100-light))
            active=lift>1e-6;target=out[b:d,a:c]
            target[active]=edited[active] if np.issubdtype(out.dtype,np.floating) else np.rint(edited[active]).astype(out.dtype)
    return out


def face_alpha(session,fi):
    f=session.faces[fi];a,b,c,d=f.box;p=f.points.astype(np.float32)-[a,b]
    hull=region_mask(p,f.mask.shape,OVAL)
    foreground=hull*((session.semantic_skin[fi]>0)|(f.protected>0))*(session.hair[fi]==0)
    return np.clip(cv2.distanceTransform(foreground.astype(np.uint8),cv2.DIST_L2,5)/2,0,1)

def slim_maps(f,strength):
    a,b,c,d=f.box;p=f.points.astype(np.float32)-[a,b];h,w=d-b,c-a
    yy,xx=np.mgrid[:h,:w].astype(np.float32);dx=np.zeros((h,w),np.float32);dy=dx.copy();total=dx.copy()
    centre=(p[1]+p[152])*.5;radius=max(8,f.width*.18)
    for idx in (234,93,132,58,172,454,323,361,288,397):
        origin=p[idx];toward=centre-origin;toward/=max(1,np.linalg.norm(toward))
        movement=toward*f.width*.035*(strength/100)
        destination=origin+movement
        weight=np.clip(1-((xx-destination[0])**2+(yy-destination[1])**2)/radius**2,0,1)**2
        dx+=movement[0]*weight;dy+=movement[1]*weight;total+=weight
    divisor=np.maximum(1,total)
    return xx-dx/divisor,yy-dy/divisor

def prepare_slim_background(rgb,session,progress=None,cancel=None):
    cache={}
    for fi,f in enumerate(session.faces):
        if f.points is None:continue
        a,b,c,d=f.box;alpha=face_alpha(session,fi)
        mx,my=slim_maps(f,100);warped=cv2.remap(alpha,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        hole=(alpha>0)&(warped<.999)
        if not hole.any():continue
        # Remove the face in a contextual crop to let LaMa reconstruct background,
        # rather than stretching existing background or inventing skin in a strip.
        x,y,z,t=square_box(f.box,rgb.shape,1.65);image=rgb[y:t,x:z]
        fullmask=np.zeros(image.shape[:2],np.uint8);fullmask[b-y:d-y,a-x:c-x]=(alpha>0).astype(np.uint8)
        scale=min(1,1024/max(image.shape[:2]));W,H=round(image.shape[1]*scale),round(image.shape[0]*scale)
        small=cv2.resize(image,(W,H),interpolation=cv2.INTER_AREA)
        mask=cv2.resize(fullmask,(W,H),interpolation=cv2.INTER_NEAREST)
        mask=cv2.dilate(mask,np.ones((5,5),np.uint8))
        if progress:progress(f'LaMa 正在补全第 {fi+1} 张脸收缩后的背景…')
        generated,info=inpaint_selected(small,mask,progress,cancel,precision=True)
        background=cv2.resize(generated,(image.shape[1],image.shape[0]),interpolation=cv2.INTER_CUBIC)[b-y:d-y,a-x:c-x]
        cache[fi]={'background':background,'alpha':alpha,'model':info['model']}
    return cache

def apply_slim(rgb,session,strength,cache,face_settings=None):
    if face_settings is None and strength==0:return rgb.copy(),np.zeros(rgb.shape[:2],bool)
    out=rgb.copy();changed=np.zeros(rgb.shape[:2],bool)
    for fi,f in enumerate(session.faces):
        if face_settings is not None:strength=face_settings[fi]['slim']
        if strength==0:continue
        if fi not in cache:continue
        a,b,c,d=f.box;source=rgb[b:d,a:c].astype(np.float32);alpha=cache[fi]['alpha']
        mx,my=slim_maps(f,strength)
        dest_alpha=cv2.remap(alpha,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        # Remap foreground only. Never remap background pixels.
        premult=cv2.remap(source*alpha[:,:,None],mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        exposed=np.maximum(alpha-dest_alpha,0)
        destination=source*(1-dest_alpha[:,:,None])+premult
        destination+=(cache[fi]['background']-source)*exposed[:,:,None]
        # Preserve the source exactly outside the original/destination face union.
        region=((alpha>0)|(dest_alpha>0))&((np.abs(mx-np.arange(c-a)[None,:])>.001)|(np.abs(my-np.arange(d-b)[:,None])>.001))
        target=out[b:d,a:c];target[region]=np.clip(destination[region],0,255);changed[b:d,a:c]|=region
    return out,changed
