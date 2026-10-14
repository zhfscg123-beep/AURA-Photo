"""Non-generative, float-preserving source/target healing and cloning."""
import cv2
import numpy as np

def validate_patches(records,shape):
    h,w=shape
    if not isinstance(records,list) or len(records)>500:raise ValueError('迁移修复列表无效。')
    for p in records:
        if not isinstance(p,dict) or p.get('mode') not in ('heal','clone'):raise ValueError('迁移修复模式无效。')
        if type(p.get('enabled',True)) is not bool:raise ValueError('迁移显示开关无效。')
        for name,lo,hi in [('radius',1,250),('feather',0,100),('opacity',0,100)]:
            v=p.get(name)
            if type(v) not in (int,float) or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('迁移修复参数无效。')
        for name in ('source','target'):
            xy=p.get(name)
            if not isinstance(xy,(list,tuple)) or len(xy)!=2 or any(type(v) not in (int,float) or not np.isfinite(v) for v in xy):raise ValueError('迁移修复坐标无效。')
            if not 0<=xy[0]<w or not 0<=xy[1]<h:raise ValueError('迁移修复位置超出照片。')
    return records

def sample(rgb,x,y,radius):
    r=int(np.ceil(radius));dy,dx=np.mgrid[-r:r+1,-r:r+1].astype(np.float32)
    return cv2.remap(rgb.astype(np.float32,copy=False),(dx+np.float32(x)).astype(np.float32),(dy+np.float32(y)).astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)

def choose_source(rgb,target,radius,allowed=None):
    """Rank nearby non-overlapping source disks; user may move either handle."""
    x,y=target;r=max(1,float(radius));h,w=rgb.shape[:2]
    reference=sample(rgb,x,y,r*1.7);yy,xx=np.mgrid[:reference.shape[0],:reference.shape[1]]
    distance=np.hypot(xx-(reference.shape[1]-1)/2,yy-(reference.shape[0]-1)/2)
    ring=(distance>r*1.15)&(distance<r*1.65)
    center=np.median(reference[ring],axis=0) if np.any(ring) else np.median(reference.reshape(-1,3),axis=0)
    candidates=[]
    for k in (3,4.5,6):
        for angle in np.linspace(0,2*np.pi,16,endpoint=False):
            sx,sy=x+np.cos(angle)*r*k,y+np.sin(angle)*r*k
            if not r<=sx<w-r or not r<=sy<h-r:continue
            if allowed is not None:
                a,b,c,d=max(0,int(sx-r)),max(0,int(sy-r)),min(w,int(sx+r+1)),min(h,int(sy+r+1))
                if np.mean(allowed[b:d,a:c])<.98:continue
            patch=sample(rgb,sx,sy,r);median=np.median(patch.reshape(-1,3),axis=0)
            # Reject strong structure and favor similar surrounding skin color.
            deviation=np.mean(np.abs(patch-median));score=np.linalg.norm(median-center)+deviation*.5+k*.2
            candidates.append((score,[float(sx),float(sy)]))
    if not candidates:raise ValueError('附近没有足够的取样区域；请缩小修复圆框。')
    return min(candidates,key=lambda v:v[0])[1]

def plane(patch,radius,ring_only=False):
    h,w=patch.shape[:2];yy,xx=np.mgrid[:h,:w].astype(np.float32);xx-=(w-1)/2;yy-=(h-1)/2
    d=np.hypot(xx,yy);keep=(d>radius*1.12)&(d<radius*1.65) if ring_only else d<radius
    if np.count_nonzero(keep)<6:return np.broadcast_to(np.median(patch.reshape(-1,3),axis=0),patch.shape).copy()
    design=np.stack([np.ones_like(xx),xx/max(1,radius),yy/max(1,radius)],axis=-1)
    a=design[keep];values=patch[keep];coef=np.linalg.lstsq(a,values,rcond=None)[0]
    residual=np.mean(np.abs(values-a@coef),axis=1);good=residual<=np.quantile(residual,.85)
    if np.count_nonzero(good)>6:coef=np.linalg.lstsq(a[good],values[good],rcond=None)[0]
    return (design@coef).astype(np.float32)

def apply_patches(rgb,records):
    if not records:return rgb
    validate_patches(records,rgb.shape[:2]);out=rgb.astype(np.float32,copy=True);h,w=out.shape[:2]
    for p in records:
        if p['opacity']==0 or not p.get('enabled',True):continue
        x,y=p['target'];sx,sy=p['source'];r=float(p['radius']);reach=int(np.ceil(r*1.7))
        source=sample(out,sx,sy,reach);target=sample(out,x,y,reach)
        corrected=source
        if p['mode']=='heal':
            # Transfer real source texture while matching target illumination
            # from the unmodified surrounding ring, excluding the defect itself.
            corrected=source-plane(source,r)+plane(target,r,ring_only=True)
        yy,xx=np.mgrid[-reach:reach+1,-reach:reach+1].astype(np.float32)
        distance=np.hypot(xx,yy);edge=max(.75,r*float(p['feather'])/100)
        alpha=np.clip((r-distance)/edge,0,1)*float(p['opacity'])/100
        # Fractional coordinates sampled above; destination placement stays aligned.
        cx,cy=int(round(x)),int(round(y));a,b,c,d=max(0,cx-reach),max(0,cy-reach),min(w,cx+reach+1),min(h,cy+reach+1)
        xa,ya=a-(cx-reach),b-(cy-reach);weight=alpha[ya:ya+d-b,xa:xa+c-a,None]
        dest=out[b:d,a:c];patch=corrected[ya:ya+d-b,xa:xa+c-a]
        dest+=(patch-dest)*weight
    return np.clip(out,0,255)
