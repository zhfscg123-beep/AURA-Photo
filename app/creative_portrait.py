"""Conservative non-generative lighting, fabric shading and masked recoloring."""
import hashlib
import cv2,numpy as np
from region_masks import soft_edge
from smart_selection import refine
CONTROLS=[('light','柔光补光',-100,100,0),('light_x','光源横向位置',0,100,50),('light_y','光源纵向位置',0,100,50),
 ('light_softness','光源柔和程度',0,100,50),('light_temp','补光色温',-100,100,0),
 ('fabric','衣物细褶皱淡化',0,100,0),('fabric_texture','衣物纹理保护',0,100,100),
 ('clothes_clean','衣物 AI 清理强度',0,100,0),('lip','唇色强度',0,100,0),('blush','腮红强度',0,100,0),
 ('hair','发色强度',0,100,0),('clothes_color','衣物改色强度',0,100,0)]
DEFAULTS={k:default for k,_,_,_,default in CONTROLS}
COLORS={'lip_rgb':[180,65,95],'blush_rgb':[210,110,130],'hair_rgb':[95,50,30],'clothes_rgb':[60,105,170]}
BACKGROUND=[('exposure','背景曝光',-2,2),('temperature','背景色温',-100,100),('saturation','背景饱和度',-100,100),('blur','背景柔化',0,100),('clean','背景 AI 清理强度',0,100)]

def person_values(data):
    values=dict(DEFAULTS,**{k:v for k,v in data.items() if k in DEFAULTS})
    for k,_,lo,hi,_ in CONTROLS:
        v=values[k]
        if type(v) not in (int,float) or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('人像创作参数无效：'+k)
    for k,default in COLORS.items():
        v=data.get(k,default)
        if not isinstance(v,list) or len(v)!=3 or any(type(x) not in (int,float) or not np.isfinite(x) or not 0<=x<=255 for x in v):raise ValueError('人像创作颜色无效。')
        values[k]=v
    from relight_settings import checked
    values['relight']=checked(data['relight']) if 'relight' in data else None
    return values

def scope(data,key,layers,automatic):
    ident=data.get(key)
    if ident is None:return automatic
    layer=next((l for l in layers if l.get('id')==ident),None)
    if layer is None or not layer.get('enabled',True):return np.zeros_like(automatic)
    return refine(layer['mask'],layer.get('parameters',{}).get('expand',0))

def roi(mask,pad=0):
    if not mask.any():return None
    x,y,w,h=cv2.boundingRect(cv2.findNonZero(mask.astype(np.uint8)));H,W=mask.shape
    return max(0,x-pad),max(0,y-pad),min(W,x+w+pad),min(H,y+h+pad)

def masked(rgb,mask,editor,feather=5):
    box=roi(mask,feather+2)
    if box is None:return rgb
    a,b,c,d=box;src=rgb[b:d,a:c];local=mask[b:d,a:c];edited=editor(src,box)
    if edited is src:return rgb
    alpha=soft_edge(local,feather);out=rgb.copy();out[b:d,a:c]=src+(edited-src)*alpha[:,:,None]
    return out

def legacy_light(rgb,mask,values):
    if not values['light']:return rgb
    h,w=rgb.shape[:2];position=np.array([values['light_x']*w/100,values['light_y']*h/100])
    sigma=max(h,w)*(.08+.5*values['light_softness']/100)
    def edit(src,box):
        a,b,c,d=box;y,x=np.mgrid[b:d,a:c].astype(np.float32)
        field=np.exp(-((x-position[0])**2+(y-position[1])**2)/(2*sigma*sigma))
        image=np.clip(src/255,0,1);linear=np.where(image<=.04045,image/12.92,((image+.055)/1.055)**2.4)
        strength=values['light']/100;guard=1-np.max(image,axis=2)**4 if strength>0 else np.ones(field.shape,np.float32)
        gain=1+field*strength*.65*guard;linear*=gain[:,:,None]
        output=np.where(linear<=.0031308,linear*12.92,1.055*np.maximum(linear,0)**(1/2.4)-.055)*255
        if values['light_temp']:
            lab=cv2.cvtColor(np.clip(output/255,0,1).astype(np.float32),cv2.COLOR_RGB2LAB);lab[:,:,2]+=field*abs(strength)*values['light_temp']*.055
            output=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
        return np.clip(output,0,255)
    return masked(rgb,mask,edit,6)

light=legacy_light  # Historical recipe/reference-script compatibility only.

def fabric(rgb,mask,values):
    if not values['fabric']:return rgb
    def edit(src,box):
        scale=min(1,1400/max(src.shape[:2]));small=cv2.resize(src,(round(src.shape[1]*scale),round(src.shape[0]*scale)),interpolation=cv2.INTER_AREA)
        lab=cv2.cvtColor(np.clip(small/255,0,1).astype(np.float32),cv2.COLOR_RGB2LAB);l=lab[:,:,0]
        fine=cv2.GaussianBlur(l,(0,0),1.4);coarse=cv2.GaussianBlur(l,(0,0),5);ridge=coarse-fine
        # Only shallow tonal ridges. Strong seams/prints and color boundaries
        # are attenuated; the high-frequency fabric texture is never replaced.
        chroma=np.linalg.norm(cv2.Sobel(lab[:,:,1:],cv2.CV_32F,1,0),axis=2)+np.linalg.norm(cv2.Sobel(lab[:,:,1:],cv2.CV_32F,0,1),axis=2)
        protect=np.exp(-chroma*.25)*np.exp(-(ridge/7)**4)
        delta=np.clip(ridge,-4,4)*protect*values['fabric']/100*.7
        delta*=1-.45*values['fabric_texture']/100
        full=cv2.resize(delta,(src.shape[1],src.shape[0]),interpolation=cv2.INTER_LINEAR)
        labfull=cv2.cvtColor(np.clip(src/255,0,1).astype(np.float32),cv2.COLOR_RGB2LAB);labfull[:,:,0]+=full
        return cv2.cvtColor(labfull,cv2.COLOR_LAB2RGB)*255
    return masked(rgb,mask,edit,5)

def recolor(rgb,mask,chosen,strength,lift=False):
    if not strength:return rgb
    target=cv2.cvtColor(np.asarray(chosen,np.float32).reshape(1,1,3)/255,cv2.COLOR_RGB2LAB)[0,0]
    def edit(src,box):
        lab=cv2.cvtColor(np.clip(src/255,0,1).astype(np.float32),cv2.COLOR_RGB2LAB);valid=mask[box[1]:box[3],box[0]:box[2]]
        mean=np.median(lab[valid],axis=0);shift=np.clip(target[1:]-mean[1:],-32,32)*strength/100
        lab[:,:,1:]+=shift
        if lift:lab[:,:,0]+=np.clip(target[0]-mean[0],0,12)*strength/100
        return cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
    return masked(rgb,mask,edit,4)

def blush(rgb,face,mask,chosen,strength):
    if not strength:return rgb
    spots=np.zeros(mask.shape,np.float32);p=face.points
    for index in (50,280):
        x,y=p[index];rx=max(4,face.width*.11);ry=max(4,face.width*.07)
        box=(max(0,int(x-rx*3)),max(0,int(y-ry*3)),min(mask.shape[1],int(x+rx*3+1)),min(mask.shape[0],int(y+ry*3+1)))
        a,b,c,d=box
        if a>=c or b>=d:continue
        yy,xx=np.mgrid[b:d,a:c];spots[b:d,a:c]=np.maximum(spots[b:d,a:c],np.exp(-((xx-x)**2/rx**2+(yy-y)**2/ry**2)/2))
    changed=recolor(rgb,mask,chosen,strength*.40)
    if changed is rgb:return rgb
    return rgb+(changed-rgb)*spots[:,:,None]

def background(rgb,mask,values):
    if not any(values.get(k,0) for k in ('exposure','temperature','saturation','blur')):return rgb
    out=rgb
    if values.get('blur') and mask.any():
        sigma=values['blur']*.4;factor=min(1,1600/max(rgb.shape[:2]));size=(round(rgb.shape[1]*factor),round(rgb.shape[0]*factor))
        weights=cv2.resize(mask.astype(np.float32),size,interpolation=cv2.INTER_AREA)
        image=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA)
        denominator=cv2.GaussianBlur(weights,(0,0),max(.4,sigma*factor))
        blurred=cv2.GaussianBlur(image*weights[:,:,None],(0,0),max(.4,sigma*factor))/np.maximum(denominator[:,:,None],1e-5)
        blurred=cv2.resize(blurred,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_LINEAR)
        alpha=soft_edge(mask,max(3,sigma*.4));out=rgb+(blurred-rgb)*alpha[:,:,None]
    def edit(src,box):
        changed=src*2**values.get('exposure',0)
        if values.get('temperature') or values.get('saturation'):
            lab=cv2.cvtColor(np.clip(changed/255,0,1).astype(np.float32),cv2.COLOR_RGB2LAB);lab[:,:,2]+=values.get('temperature',0)*.12;lab[:,:,1:]*=1+values.get('saturation',0)/100*.7
            changed=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
        return np.clip(changed,0,255)
    return masked(out,mask,edit,6)

def source_hash(rgb,mask,box):
    a,b,c,d=box;return hashlib.blake2b(np.ascontiguousarray(rgb[b:d,a:c][mask[b:d,a:c]]).tobytes(),digest_size=16).hexdigest()

def apply_clean(rgb,data,key,strength,allowed):
    rec=data.get('clean_records',{}).get(key);asset=data.get('assets',{}).get(key);mask=data.get('masks',{}).get('apply-'+key)
    if not rec or asset is None or mask is None or not strength:return rgb,False
    if source_hash(rgb,mask,rec['box'])!=rec['source_hash']:return rgb,True
    a,b,c,d=rec['box'];local=mask[b:d,a:c]&allowed[b:d,a:c];alpha=soft_edge(local,3)*strength/100
    result=rgb.copy();result[b:d,a:c]=rgb[b:d,a:c]+asset*alpha[:,:,None];return np.clip(result,0,255),False
