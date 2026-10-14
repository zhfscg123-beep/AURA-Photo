"""Bounded photographic corrections on AI masks; no invented generative detail."""
import cv2,numpy as np
from region_masks import skin_blend,face_beauty_mask
from beauty_settings import EXTRA,ZONES

def enhance_skin(rgb,session,settings):
    if not settings or not any(any(v.get(k,0) for k,_,_,_ in EXTRA) for v in settings):return rgb
    out=rgb.copy()
    tones=[]
    if any(v.get('skin_match',0) for v in settings):
        for f in session.faces:
            a,b,c,d=f.box;safe=f.mask>.8
            if safe.sum()<20:continue
            lab=cv2.cvtColor(np.clip(rgb[b:d,a:c].astype(np.float32)/255,0,1),cv2.COLOR_RGB2LAB)
            tones.append(np.median(lab[safe,1:3],axis=0))
    common_tone=np.median(tones,axis=0) if len(tones)>1 else None
    for fi,(f,v) in enumerate(zip(session.faces,settings)):
        if not any(v.get(k,0) for k,_,_,_ in EXTRA):continue
        if common_tone is None and not any(v.get(k,0) for k,_,_,_ in EXTRA if k!='skin_match'):continue
        face_beauty_mask(session,fi)
        a,b,c,d=f.box;src=rgb[b:d,a:c].astype(np.float32);mask=skin_blend(f);safe=f.mask>.8
        if safe.sum()<20:continue
        lab=cv2.cvtColor(np.clip(src/255,0,1),cv2.COLOR_RGB2LAB);light=lab[:,:,0].copy()
        fine=cv2.GaussianBlur(light,(0,0),max(.7,f.width*.003))
        low=cv2.GaussianBlur(fine,(0,0),max(2,f.width*.018))
        broad=cv2.GaussianBlur(light,(0,0),max(4,f.width*.06))
        if v.get('skin_translucent',0):
            lab[:,:,0]+=np.clip((100-light)/65,0,1)*v['skin_translucent']/100*4
        if v.get('skin_hydrate',0):
            lab[:,:,0]+=(fine-light)*v['skin_hydrate']/100*.35
            lab[:,:,0]+=np.clip((broad-np.median(broad[safe]))/20,0,1)*v['skin_hydrate']/100*1.5
        if v.get('skin_fill',0):
            target=float(np.percentile(broad[safe],70))
            lab[:,:,0]+=np.clip(target-broad,0,8)*v['skin_fill']/100*.6
        if v.get('skin_shadow',0):
            surrounding=cv2.GaussianBlur(broad,(0,0),max(8,f.width*.14))
            lab[:,:,0]+=np.clip(surrounding-broad,0,6)*v['skin_shadow']/100*.7
        if v.get('even_light',0):
            broad=cv2.GaussianBlur(light,(0,0),max(4,f.width*.06))
            deviation=broad-cv2.GaussianBlur(broad,(0,0),max(8,f.width*.13))
            lab[:,:,0]-=np.clip(deviation,-6,6)*v['even_light']/100*.55
        if v.get('low_smooth',0):lab[:,:,0]+=(low-fine)*v['low_smooth']/100*.5
        if v.get('clarity',0):lab[:,:,0]+=(fine-low)*v['clarity']/100*.4
        highlights=np.clip((light-np.percentile(light[safe],75))/15,0,1)
        if v.get('oil',0):lab[:,:,0]-=highlights*np.maximum(light-low,0)*v['oil']/100*.6
        if v.get('gloss',0):lab[:,:,0]+=highlights*v['gloss']/100*4
        if v.get('skin_even',0):
            for ch in (1,2):
                blurred=cv2.GaussianBlur(lab[:,:,ch],(0,0),max(2,f.width*.016))
                median=float(np.median(blurred[safe]));lab[:,:,ch]+=np.clip(median-blurred,-5,5)*v['skin_even']/100*.55
        if v.get('skin_match',0) and common_tone is not None:
            local=np.median(lab[safe,1:3],axis=0)
            lab[:,:,1:3]+=np.clip(common_tone-local,-6,6)*v['skin_match']/100*.65
        lab[:,:,1]+=v.get('redness',0)/100*3+v.get('skin_tint',0)/100*3
        lab[:,:,2]+=v.get('skin_temp',0)/100*5
        lab[:,:,0]=np.clip(lab[:,:,0],0,100);edited=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
        target=out[b:d,a:c];region=mask>0
        target[region]=np.clip((src+(edited-src)*mask[:,:,None])[region],0,255)
    return out

def eye_wrinkle_region(f):
    """Follow each lower lid; include under-eye creases, not just outer corners."""
    a,b,c,d=f.box;p=f.points.astype(np.float32)-[a,b];fw=f.width
    down=p[152]-p[10];down/=max(1,np.linalg.norm(down));side=np.array([down[1],-down[0]])
    zone=np.zeros(f.mask.shape,np.uint8)
    for ids in ([33,7,163,144,145,153,154,155,133],[263,249,390,373,374,380,381,382,362]):
        edge=p[ids]
        band=np.concatenate((edge+down*fw*.020,(edge+down*fw*.155)[::-1]))
        cv2.fillPoly(zone,[np.rint(band).astype(np.int32)],1)
    yy,xx=np.mgrid[:d-b,:c-a].astype(np.float32);corners=np.zeros(zone.shape,np.float32)
    for point,sign in ((p[33],1),(p[263],-1)):
        center=point+side*fw*.035*sign+down*fw*.04;dx=xx-center[0];dy=yy-center[1]
        value=np.clip(1-((dx*side[0]+dy*side[1])/(fw*.13))**2-((dx*down[0]+dy*down[1])/(fw*.12))**2,0,1)
        corners=np.maximum(corners,value)
    band=cv2.GaussianBlur(zone.astype(np.float32),(0,0),max(1,fw*.008))
    return np.maximum(band,corners).astype(np.float32)

def wrinkle_zone_strength(f,values):
    """Landmark-oriented zone weights, retaining face skin/features protection."""
    a,b,c,d=f.box;p=f.points.astype(np.float32)-[a,b];yy,xx=np.mgrid[:d-b,:c-a].astype(np.float32)
    down=p[152]-p[10];down/=max(1,np.linalg.norm(down));side=np.array([down[1],-down[0]],np.float32)
    def ellipse(center,rx,ry):
        dx=xx-center[0];dy=yy-center[1]
        return np.clip(1-((dx*side[0]+dy*side[1])/max(1,rx))**2-((dx*down[0]+dy*down[1])/max(1,ry))**2,0,1)
    fw=f.width;strength=np.full(f.mask.shape,values.get('wrinkles',0)/100,np.float32)
    zones={
      'wr_forehead':[ellipse((p[10]+p[151])/2-down*fw*.08,fw*.35,fw*.22)],
      'wr_glabella':[ellipse(p[168]-down*fw*.04,fw*.10,fw*.12)],
      'wr_eyes':[eye_wrinkle_region(f)],
      'wr_naso_left':[ellipse((p[327]+p[291])/2,fw*.10,fw*.17)],
      'wr_naso_right':[ellipse((p[98]+p[61])/2,fw*.10,fw*.17)],
      'wr_mouth':[ellipse(p[17]+down*fw*.03,fw*.26,fw*.13)],
      'wr_nose':[ellipse((p[168]+p[6])/2,fw*.085,fw*.16)],
      'wr_cheek':[ellipse((p[50]+p[101])/2,fw*.20,fw*.23),ellipse((p[280]+p[330])/2,fw*.20,fw*.23)],
      'wr_marionette':[ellipse(p[61]+down*fw*.12,fw*.09,fw*.19),ellipse(p[291]+down*fw*.12,fw*.09,fw*.19)]}
    for name,masks in zones.items():
        value=values.get(name,0)/100
        if value:strength=np.maximum(strength,np.maximum.reduce(masks)*value)
    return strength.astype(np.float32)
