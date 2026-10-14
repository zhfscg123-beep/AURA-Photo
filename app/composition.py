"""Export framing and straightening; original editing coordinates stay intact."""
import math
import cv2,numpy as np
RATIOS={'原始':None,'1:1':1.,'3:4':.75,'4:5':.8,'16:9':16/9,'9:16':9/16,'自定义':None}
DEFAULTS=dict(ratio='原始',center_x=50.,center_y=50.,size=100.,rotation=0.,quarter=0,locked=True,width=100.,height=100.,custom_ratio=1.)

def camera_frame(shape,box):
    h,w=shape[:2];a,b,c,d=box
    if not 0<=a<c<=w or not 0<=b<d<=h:raise ValueError('相机构图范围无效。')
    return checked(dict(ratio='自定义',locked=False,width=(c-a)/w*100,height=(d-b)/h*100,center_x=(a+c)/2/w*100,center_y=(b+d)/2/h*100,custom_ratio=(c-a)/(d-b)))
def checked(data):
    v=dict(DEFAULTS,**data)
    if set(v)!=set(DEFAULTS) or v['ratio'] not in RATIOS or type(v['quarter']) is not int or not 0<=v['quarter']<=3:raise ValueError('构图参数无效。')
    if type(v['locked']) is not bool:raise ValueError('固定比例开关无效。')
    for key,lo,hi in [('center_x',0,100),('center_y',0,100),('size',1,100),('rotation',-180,180),('width',1,100),('height',1,100),('custom_ratio',.01,100)]:
        value=v[key]
        if type(value) not in (int,float) or not np.isfinite(value) or not lo<=value<=hi:raise ValueError('构图参数无效：'+key)
    return v
def rectangle(w,h,data,original_ratio=None):
    v=checked(data);ratio=v['custom_ratio'] if v['ratio']=='自定义' else original_ratio if v['ratio']=='原始' and original_ratio is not None else RATIOS[v['ratio']] or w/h
    if v['locked']:cw,ch=(w,w/ratio) if w/h<ratio else (h*ratio,h)
    else:cw,ch=w*v['width']/100,h*v['height']/100
    cw=max(1,min(w,round(cw*v['size']/100)));ch=max(1,min(h,round(ch*v['size']/100)))
    cx=np.clip(w*v['center_x']/100,cw/2,w-cw/2);cy=np.clip(h*v['center_y']/100,ch/2,h-ch/2)
    a,b=int(round(cx-cw/2)),int(round(cy-ch/2));return a,b,a+cw,b+ch
def straight_bounds(w,h,angle):
    angle=abs(math.radians(angle));s,c=abs(math.sin(angle)),abs(math.cos(angle))
    if s<1e-8:return w,h
    long,short=max(w,h),min(w,h)
    if short<=2*s*c*long:
        x=.5*short;rw,rh=(x/s,x/c) if w>=h else (x/c,x/s)
    else:
        cos2=c*c-s*s;rw=(w*c-h*s)/cos2;rh=(h*c-w*s)/cos2
    return max(1,min(w,int(rw))),max(1,min(h,int(rh)))
def oriented(rgb,data,margin=4):
    v=checked(data)
    out=np.rot90(rgb,-v['quarter']) if v['quarter'] else rgb
    turns=round(v['rotation']/90);angle=v['rotation']-turns*90
    if turns:out=np.rot90(out,turns)
    if angle:
        h,w=out.shape[:2];matrix=cv2.getRotationMatrix2D(((w-1)/2,(h-1)/2),angle,1)
        out=cv2.warpAffine(out,matrix,(w,h),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        cw,ch=straight_bounds(w,h,angle)
        # Bilinear samples need a pixel of interior context at the analytical
        # rotated rectangle boundary. Crop it rather than introduce dark edges.
        cw=max(1,cw-margin);ch=max(1,ch-margin);x,y=(w-cw)//2,(h-ch)//2;out=out[y:y+ch,x:x+cw]
    return out
def apply(rgb,data):
    v=checked(data)
    if v==DEFAULTS:return rgb
    out=oriented(rgb,v)
    h,w=out.shape[:2];a,b,c,d=rectangle(w,h,v,original_aspect(rgb.shape,v));return np.ascontiguousarray(out[b:d,a:c])
def original_aspect(shape,data):
    h,w=shape[:2]
    return h/w if (data['quarter']-round(data['rotation']/90))%2 else w/h
