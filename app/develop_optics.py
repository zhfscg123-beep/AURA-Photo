"""Final geometric optics stage with a shared inverse map for painting/picking."""
from functools import lru_cache
import json,numpy as np,cv2
import color_science as cs
CONTROLS=[('distortion','手动畸变',-100,100,0),('lens_vignette','镜头暗角补偿',-100,100,0),('ca_red','红色色差',-100,100,0),('ca_blue','蓝色色差',-100,100,0),
 ('defringe','紫绿边去除',0,100,0),('vertical','垂直透视',-100,100,0),('horizontal','水平透视',-100,100,0),('rotation','微调旋转',-10,10,0),
 ('aspect','纵横比例',-100,100,0),('scale','变换缩放',50,200,100),('shift_x','水平位移',-100,100,0),('shift_y','垂直位移',-100,100,0),
 ('crop_factor','传感器倍率',.5,4,1),('focal','焦距 mm',1,1200,50),('aperture','光圈',.7,64,5.6)]
DEFAULTS={k:d for k,_,_,_,d in CONTROLS};DEFAULTS.update(enabled=False,profile='',constrain=True)
DEFAULTS.update(homography=[[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]],guides=[],upright_mode='off')
LENS_KEYS=('enabled','profile','crop_factor','focal','aperture','distortion','lens_vignette','ca_red','ca_blue','defringe')
TRANSFORM_KEYS=tuple(k for k in DEFAULTS if k not in LENS_KEYS)

def reset_scope(data,scope):
    """The same field contract serves reset and temporary comparison."""
    import copy
    value=copy.deepcopy(checked(data))
    for key in LENS_KEYS if scope=='optics_lens' else TRANSFORM_KEYS:
        value[key]=copy.deepcopy(DEFAULTS[key])
    return value

def checked(data):
    if not isinstance(data,dict):raise ValueError('镜头与变换参数无效。')
    v=dict(DEFAULTS,**{k:data[k] for k in DEFAULTS if k in data})
    for k in ('enabled','constrain'):
        if type(v[k]) is not bool:raise ValueError('镜头开关无效。')
    if not isinstance(v['profile'],str) or len(v['profile'])>300:raise ValueError('镜头配置名称无效。')
    for k,_,lo,hi,_ in CONTROLS:
        x=v[k]
        if type(x) not in (int,float) or not np.isfinite(x) or not lo<=x<=hi:raise ValueError('镜头参数超范围：'+k)
    matrix=np.asarray(v['homography'],float)
    if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or np.max(np.abs(matrix))>20 or abs(np.linalg.det(matrix))<1e-6:raise ValueError('透视矩阵无效。')
    if v['upright_mode'] not in ('off','level','vertical','full','guided'):raise ValueError('透视校正模式无效。')
    if not isinstance(v['guides'],list) or len(v['guides'])>4:raise ValueError('最多四条透视引导线。')
    for guide in v['guides']:
        pts=np.array([guide.get('start',[]),guide.get('end',[])])
        if guide.get('axis') not in ('vertical','horizontal') or pts.shape!=(2,2) or not np.isfinite(pts).all() or np.max(np.abs(pts))>4 or np.linalg.norm(pts[1]-pts[0])<.001:raise ValueError('透视引导线无效。')
    v['homography']=matrix.tolist()
    return v

def geometry_active(data):
    v=checked(data)
    return bool(v['enabled'] and v['profile']) or v['homography']!=DEFAULTS['homography'] or any(v[k]!=DEFAULTS[k] for k in ('distortion','ca_red','ca_blue','vertical','horizontal','rotation','aspect','scale','shift_x','shift_y'))

def raw_defaults(document):
    """Enable only a unique calibrated lens match for a newly imported RAW."""
    if not document.is_raw:return {}
    from lens_profiles import match
    profile,crop=match(document.metadata)
    if not profile:return {}
    return checked(dict(enabled=True,profile=profile,crop_factor=crop or 1,
                        focal=document.metadata.get('focal_length',50) or 50,
                        aperture=document.metadata.get('aperture',5.6) or 5.6))

@lru_cache(maxsize=8)
def calibration(signature,w,h):
    v=json.loads(signature);sw=max(16,round(w*min(1,513/max(w,h))));sh=max(16,round(h*min(1,513/max(w,h))))
    if v['enabled'] and v['profile']:
        from lens_profiles import field
        delta,gain,flags=field(v['profile'],v['crop_factor'],v['focal'],v['aperture'],sw,sh)
    else:delta=np.zeros((sh,sw,3,2),np.float32);gain=np.ones((sh,sw,3),np.float32);flags=0
    delta.flags.writeable=False;gain.flags.writeable=False
    return delta,gain,flags

def _normalized(points,v,zoom=1):
    p=(np.asarray(points,np.float32)-.5)*2
    p/=v['scale']/100*zoom
    angle=np.deg2rad(v['rotation']);c,s=np.cos(angle),np.sin(angle)
    H=np.array([[c*np.exp(v['aspect']*.003),-s,v['shift_x']*.006],[s,c*np.exp(-v['aspect']*.003),v['shift_y']*.006],[v['horizontal']*.002,v['vertical']*.002,1]],np.float32)
    inv=np.linalg.inv(H);q=np.column_stack([p.reshape(-1,2),np.ones(p.size//2,np.float32)])@inv.T
    divisor=q[:,2:3];divisor=np.where(np.abs(divisor)<1e-5,np.copysign(1e-5,divisor),divisor)
    p=(q[:,:2]/divisor).reshape(p.shape)
    if v['homography']!=DEFAULTS['homography']:
        n=p/2+.5;matrix=np.linalg.inv(np.array(v['homography'],np.float32));flat=np.column_stack([n.reshape(-1,2),np.ones(n.size//2,np.float32)])@matrix.T
        divisor=np.where(np.abs(flat[:,2:3])<1e-5,1e-5,flat[:,2:3]);p=((flat[:,:2]/divisor).reshape(n.shape)-.5)*2
    r2=(p*p).sum(-1,keepdims=True);p*=1+v['distortion']*.002*r2
    return p/2+.5

def mapped(points,shape,data,zoom=1,channel=1):
    # OpenCV's CPU remap has a 32767-side limit; CUDA does not. Split only
    # CPU inputs, before normalization, instead of repeating it for each tile.
    if points.ndim==2 and len(points)>30000 and not hasattr(points,'__cuda_array_interface__'):
        return np.concatenate([mapped(points[i:i+30000],shape,data,zoom,channel) for i in range(0,len(points),30000)])
    h,w=shape[:2];v=checked(data);scale=np.array([max(1,w-1),max(1,h-1)],np.float32)
    normalized=np.asarray(points,np.float32)/scale;q=_normalized(normalized,v,zoom)
    delta,_,_=calibration(json.dumps(v,sort_keys=True),w,h);sh,sw=delta.shape[:2]
    coords=q.reshape(-1,2)
    sample=cv2.remap(delta[:,:,channel],(coords[:,0]*(sw-1))[:,None],(coords[:,1]*(sh-1))[:,None],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)[:,0]
    q=q+sample.reshape(q.shape)
    if channel in (0,2):q=(q-.5)*(1+v['ca_red' if channel==0 else 'ca_blue']*.0002)+.5
    return q*scale

@lru_cache(maxsize=8)
def zoom_for(signature,w,h):
    v=json.loads(signature)
    if not v['constrain']:return 1.
    xs,ys=np.meshgrid(np.linspace(0,w-1,25),np.linspace(0,h-1,25));points=np.stack([xs,ys],2).reshape(-1,2).astype(np.float32)
    def valid(z):
        for c in range(3):
            q=mapped(points,(h,w),v,z,c)
            if not (q.min(0)[0]>=0 and q.min(0)[1]>=0 and q.max(0)[0]<=w-1 and q.max(0)[1]<=h-1):return False
        return True
    if valid(1):return 1.
    lo,hi=1.,3.
    for _ in range(18):
        mid=(lo+hi)/2
        if valid(mid):hi=mid
        else:lo=mid
    return hi

def inverse_points(points,shape,data):
    if not geometry_active(data):return np.asarray(points,np.float32)
    h,w=shape[:2];v=checked(data);return mapped(points,shape,v,zoom_for(json.dumps(v,sort_keys=True),w,h))

def apply(rgb,data):
    v=checked(data);h,w=rgb.shape[:2];geometric=geometry_active(v)
    if not geometric and not v['lens_vignette'] and not v['defringe']:return rgb
    signature=json.dumps(v,sort_keys=True);delta,gain,flags=calibration(signature,w,h);zoom=zoom_for(signature,w,h) if geometric else 1.
    source=cs.decode(rgb/255);result=np.empty_like(source);profile_gain=bool(flags&2)
    for a in range(0,h,128):
        b=min(h,a+128);yy,xx=np.mgrid[a:b,:w].astype(np.float32);points=np.stack([xx,yy],2);flat=points.reshape(-1,2)
        for c in range(3):
            q=mapped(flat,(h,w),v,zoom,c).reshape(b-a,w,2) if geometric else points
            tile=cv2.remap(source[:,:,c],q[:,:,0],q[:,:,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
            if profile_gain:
                sh,sw=gain.shape[:2];g=cv2.remap(gain[:,:,c],q[:,:,0]*(sw-1)/max(1,w-1),q[:,:,1]*(sh-1)/max(1,h-1),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE);tile*=g
            if v['lens_vignette']:
                radius=((xx-(w-1)/2)/max(1,w/2))**2+((yy-(h-1)/2)/max(1,h/2))**2;tile*=np.exp2(v['lens_vignette']*.008*radius)
            result[a:b,:,c]=tile
    if v['defringe']:
        lab=cs.oklab(result);chroma=np.linalg.norm(lab[:,:,1:],axis=2);hue=(np.rad2deg(np.arctan2(lab[:,:,2],lab[:,:,1]))+360)%360
        L=lab[:,:,0];edge=np.hypot(cv2.Sobel(L,cv2.CV_32F,1,0),cv2.Sobel(L,cv2.CV_32F,0,1))
        purple=((hue>265)&(hue<345));green=(hue>110)&(hue<175)
        weight=(purple|green)*np.clip(edge/.2,0,1)*np.clip(chroma/.15,0,1)*v['defringe']/100
        lab[:,:,1:]*=1-weight[:,:,None];result=cs.oklab_rgb(lab)
    return cs.encode(result)*255
