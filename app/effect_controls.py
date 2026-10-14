"""Stage-wise reversible opacity and erase masks; geometry remains separate."""
import cv2,numpy as np
TITLES={'mobile_cache':'手机修补缓存','repair':'自动祛瑕','skin':'基础肤质 · 脸与身体','wrinkles':'分区域祛纹',
        'details':'面部细节','face_color':'面部肤色','volume':'光影丰盈',
        'body':'身体专项','local':'部位蒙版调色','patches':'迁移与仿制','manual':'手动修饰','color':'全局调色与追色','light':'人像柔光','clothes':'衣物整理','makeup':'轻妆与发色','background':'背景精修','creative':'调色与创作'}

def settings(data,key):
    value=data.get('effects',{}).get(key,{})
    enabled=value.get('enabled',True);opacity=value.get('opacity',100.)
    if type(enabled) is not bool or type(opacity) not in (int,float) or not np.isfinite(opacity) or not 0<=opacity<=100:raise ValueError('效果开关或强度无效。')
    return enabled,float(opacity)/100

def before(rgb,data,key):
    enabled,opacity=settings(data,key);mask=data.get('masks',{}).get('erase-'+key)
    return rgb.copy() if not enabled or opacity!=1 or mask is not None and np.any(mask) else None

def blend(source,target,data,key):
    if source is None:return target
    enabled,opacity=settings(data,key)
    if not enabled or opacity==0:return source
    result=source+(target-source)*opacity
    mask=data.get('masks',{}).get('erase-'+key)
    if mask is not None and np.any(mask):
        found=cv2.findNonZero(mask.astype(np.uint8));x,y,w,h=cv2.boundingRect(found);pad=12
        a,b=max(0,x-pad),max(0,y-pad);c,d=min(result.shape[1],x+w+pad),min(result.shape[0],y+h+pad)
        feather=cv2.GaussianBlur(mask[b:d,a:c].astype(np.float32),(0,0),2)
        result[b:d,a:c]=source[b:d,a:c]+(result[b:d,a:c]-source[b:d,a:c])*(1-feather[:,:,None])
    return result.astype(np.float32)

def paint(mask,start,end,radius,erase):
    radius=max(1,min(500,int(radius)));start=np.rint(start).astype(int);end=np.rint(end).astype(int)
    a,b=np.maximum(np.minimum(start,end)-radius-2,0);c,d=np.minimum(np.maximum(start,end)+radius+3,[mask.shape[1],mask.shape[0]])
    if a>=c or b>=d:return
    line=np.zeros((d-b,c-a),np.uint8);p=tuple(start-[a,b]);q=tuple(end-[a,b])
    cv2.line(line,p,q,1,2*radius,cv2.LINE_8);cv2.circle(line,p,radius,1,-1);cv2.circle(line,q,radius,1,-1);mask[b:d,a:c][line>0]=erase
