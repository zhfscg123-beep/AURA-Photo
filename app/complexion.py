"""Texture-aware frequency smoothing and masked, restrained skin brightening.

Recommendations are explicit rules using AI masks and measured image values;
the neural network does not predict these four slider values.
"""
import numpy as np
import cv2
import copy,hashlib
from region_masks import skin_blend,soft_edge,face_beauty_mask

def beauty_regions(session):
    """Cached connected skin patches per person; joint face/neck correction.

    Body ownership is prepared during import, never inferred on a slider drag.
    Split disconnected arms/hands so filters do not process a full-image box.
    The precise face mask remains untouched for detection and mask editing.
    """
    owners=getattr(session,'body_owner',None)
    if owners is not None:
        from person_masks import ensure_body_owners
        ensure_body_owners(session)
        owners=session.body_owner
    regions=[]
    for fi,f in enumerate(session.faces):
        beauty=face_beauty_mask(session,fi)
        if owners is None:
            region=copy.copy(f);region.mask=beauty
            regions.append((fi,region));continue
        mask=(owners==fi+1).astype(np.uint8)
        if fi in getattr(session,'body_beauty_include',{}) or fi in getattr(session,'body_beauty_exclude',{}):
            from body_details import body_scope
            mask=body_scope(session,fi,[]).astype(np.uint8)
        a,b,c,d=f.box;mask[b:d,a:c]|=(beauty>0).astype(np.uint8)
        # Coarse body ownership must not overwrite the head's explicit hair /
        # accessory exclusion. Preserve confirmed neck/ears below the jaw.
        from region_masks import below_jaw
        face_area=~below_jaw(f,f.box)&~np.isin(session.part_labels[fi],[7,8,14])
        mask[b:d,a:c][face_area&(beauty==0)]=0
        mask[b:d,a:c][np.isin(session.part_labels[fi],[6,9,17,18])&(beauty==0)]=0
        mask[b:d,a:c][f.beauty_eye_mask]=0
        key=(2,hashlib.blake2b(mask.tobytes()+f.beauty_eye_mask.tobytes(),digest_size=12).hexdigest(),float(f.width))
        cached=getattr(f,'_beauty_regions_cache',None)
        if cached is not None and cached[0]==key:
            regions.extend((fi,r) for r in cached[1]);continue
        n,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
        patches=[];pad=max(3,round(f.width*.025));height,width=mask.shape
        for i in range(1,n):
            x,y,w,h,area=stats[i]
            if not area:continue
            a,b,c,d=max(0,x-pad),max(0,y-pad),min(width,x+w+pad),min(height,y+h+pad)
            region=copy.copy(f);region.box=(a,b,c,d)
            for attr in ('_beauty_regions_cache','_skin_blend_cache','beauty_mask','beauty_mask_key','beauty_eye_mask'):region.__dict__.pop(attr,None)
            region.mask=soft_edge(labels[b:d,a:c]==i,max(1,f.width*.003))
            region.beauty_eye_mask=np.zeros(region.mask.shape,bool)
            fa,fb,fc,fd=f.box;x0,y0,x1,y1=max(a,fa),max(b,fb),min(c,fc),min(d,fd)
            if x0<x1 and y0<y1:region.beauty_eye_mask[y0-b:y1-b,x0-a:x1-a]=f.beauty_eye_mask[y0-fb:y1-fb,x0-fa:x1-fa]
            patches.append(region)
        f._beauty_regions_cache=(key,patches)
        regions.extend((fi,r) for r in patches)
    return regions

def small_blemishes(session):
    mask=np.zeros(session.original.shape[:2],np.uint8);count=0
    for spot,component in zip(session.spots,session.component_masks):
        f=session.faces[spot['face']]
        if spot['r']>max(3,round(f.width*.012)):continue
        a,b,c,d=f.box;mask[b:d,a:c]|=component*255;count+=1
    # New point repair remains effective when smoothing is zero. Legacy
    # projects retain the old small-defect shortcut through the smoothing layer.
    if getattr(session,'retouch_engine',1)==2:mask.fill(0)
    return mask,count

def recommend(session):
    brightness=[];roughness=[];fine_energy=[]
    for f in session.faces:
        a,b,c,d=f.box;p=session.original[b:d,a:c].astype(np.float32)/255
        lab=cv2.cvtColor(p,cv2.COLOR_RGB2LAB);safe=f.mask>.95
        if np.count_nonzero(safe)<30:continue
        l=lab[:,:,0];fine=cv2.GaussianBlur(l,(0,0),max(.65,f.width*.0035))
        base=cv2.GaussianBlur(fine,(0,0),max(2,f.width*.015))
        brightness.append(float(np.median(l[safe])))
        roughness.append(float(np.median(np.abs((fine-base)[safe]))))
        fine_energy.append(float(np.median(np.abs((l-fine)[safe]))))
    if not brightness:return {'repair':75,'smooth':0,'whiten':0,'texture':50}, {'reason':'未定位到可靠面部，保留手动 AI 修复。'}
    bright=float(np.median(brightness));rough=float(np.median(roughness));fine=float(np.median(fine_energy))
    score=float(np.median([s['confidence'] for s in session.spots])) if session.spots else .7
    small,count=small_blemishes(session)
    values={'repair':int(np.clip(round(75+(score-.7)*15),65,85)),
      'smooth':int(np.clip(round(40+rough*5+count*5),30,70)),
      'whiten':int(np.clip(round((80-bright)*2.5),10,60)),
      'texture':int(np.clip(round(50-max(0,fine-.8)*10),35,55))}
    if getattr(session,'retouch_engine',1)==2:
        values['smooth']=int(np.clip(round(28+rough*3),15,55))
        values['texture']=50
    return values,{'median_skin_L':round(bright,2),'mid_frequency_deviation':round(rough,3),'fine_texture_deviation':round(fine,3),'small_candidates':count,'method':'AI segmentation/detection + explicit image-statistic rules; not network-predicted slider values'}

def render_skin(rgb,session,smooth=0,whiten=0,texture=50,small_mask=None,face_settings=None):
    if face_settings is None and smooth==0 and whiten==0 and texture==50:return rgb.copy()
    floating=np.issubdtype(rgb.dtype,np.floating)
    result=rgb.copy();sm=float(np.clip(smooth,0,100)/100);wh=float(np.clip(whiten,0,100)/100)
    # 50 preserves existing fine detail, 0 softens it, 100 mildly enhances it.
    gain=float(np.interp(np.clip(texture,0,100),[0,50,100],[.20,1.,1.20]))
    for fi,f in beauty_regions(session):
        if face_settings is not None:
            settings=face_settings[fi];sm=float(settings['smooth']/100);wh=float(settings['whiten']/100)
            gain=float(np.interp(settings['texture'],[0,50,100],[.20,1.,1.20]))
            if sm==0 and wh==0 and settings['texture']==50:continue
        a,b,c,d=f.box;source=rgb[b:d,a:c].astype(np.float32)
        modern=getattr(session,'retouch_engine',1)==2
        if modern:
            from skin_texture import adaptive
            fine,low,structure,boost=adaptive(source,f.width)
            high=source-fine;mid=fine-low
            detail_gain=1+(gain-1)*boost[:,:,None] if gain>1 else gain
            edited=low+mid*(1-.78*sm*structure[:,:,None])+high*detail_gain
        else:
            from skin_surface_cache import surfaces
            fine,low=surfaces(source,f.width)
            high=source-fine;mid=fine-low
            edited=low+mid*(1-.82*sm)+high*gain
        if small_mask is not None and sm>0:
            selected=(small_mask[b:d,a:c]>0).astype(np.uint8)
            weight=np.clip(cv2.distanceTransform(selected,cv2.DIST_L2,5)/1.5,0,1)*sm
            # Suppress identified tiny defects at both scales, while preserving
            # texture elsewhere. Tiny selected defects are not treated as pores.
            localbase=cv2.GaussianBlur(fine,(0,0),max(1.5,f.width*.009))
            edited+=(localbase-edited)*weight[:,:,None]
        if modern:
            from skin_detail_protection import strength_mask
            # Repair/texture guards must not create unbrightened brow halos.
            # Apply them to the texture delta before the separate tonal step.
            edited=source+(edited-source)*strength_mask(session,fi,f.box)[:,:,None]
        if wh>0:
            lab=cv2.cvtColor(np.clip(edited/255,0,1).astype(np.float32),cv2.COLOR_RGB2LAB)
            l=lab[:,:,0];highlight_guard=np.clip((98-l)/22,0,1)
            lab[:,:,0]=np.minimum(100,l+wh*8*highlight_guard)
            brightened=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
            tone_weight=strength_mask(session,fi,f.box,include_brows=True)[:,:,None] if modern else 1
            edited+=(brightened-edited)*tone_weight
        # Precise selections use a separate broad falloff for beauty blending.
        weight=skin_blend(f)
        if modern:
            beyond=(source.min(2)<0)|(source.max(2)>255);edited[beyond]=source[beyond]
        edited=source+(edited-source)*weight[:,:,None]
        target=result[b:d,a:c];region=f.mask>0
        final=(edited if modern else np.clip(edited,0,255)) if floating else np.clip(np.rint(edited),0,255).astype(np.uint8)
        target[region]=final[region]
    return result
