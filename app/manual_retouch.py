"""Replayable, float RGB255 manual strokes; no inference or generated pixels."""
import copy
import cv2
import numpy as np

MODES = ('dodge', 'burn', 'heal', 'clone', 'restore')
RANGES = ('all', 'shadows', 'midtones', 'highlights')
MAX_STROKES = 300
MAX_POINTS = 2000
MAX_TOTAL_POINTS = 20000
DEFAULT_TOOLS = dict(radius=60., hardness=20., opacity=100., flow=35., strength=15., tone='midtones', aligned=True)
EXTRA_TOOLS = dict(spacing=15.,scale=100.,angle=0.,flip_x=False,flip_y=False,healing='texture')
DEFAULT_TOOLS.update(EXTRA_TOOLS)

def validate_tools(values):
    if values is not None and not isinstance(values,dict):raise ValueError('手动修饰笔刷设置无效。')
    out = dict(DEFAULT_TOOLS, **(values or {}))
    for key, lo, hi in (('radius', 1, 1000), ('hardness', 0, 100), ('opacity', 0, 100), ('flow', 1, 100), ('strength', 0, 100),('spacing',1,100),('scale',20,400),('angle',-180,180)):
        v = out[key]
        if type(v) not in (int, float) or not np.isfinite(v) or not lo <= v <= hi:
            raise ValueError('手动修饰笔刷参数无效。')
    if out['tone'] not in RANGES or type(out['aligned']) is not bool:
        raise ValueError('手动修饰取样或明暗范围无效。')
    if any(type(out[k]) is not bool for k in ('flip_x','flip_y')) or out['healing'] not in ('texture','gradient'):
        raise ValueError('取样变换或修复模式无效。')
    return {k: out[k] for k in DEFAULT_TOOLS}

def validate_records(records, shape):
    h, w = shape
    if not isinstance(records, list) or len(records) > MAX_STROKES:
        raise ValueError(f'单图最多 {MAX_STROKES} 笔手动修饰。')
    total = 0
    for rec in records:
        if not isinstance(rec, dict) or rec.get('mode') not in MODES:
            raise ValueError('手动修饰工具无效。')
        if type(rec.get('enabled',True)) is not bool:raise ValueError('手动笔画显示开关无效。')
        tools = validate_tools(rec)
        points = rec.get('points')
        if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
            raise ValueError('手动修饰笔画无效。')
        total += len(points)
        r = tools['radius']
        for xy in points:
            if not isinstance(xy, (list, tuple)) or len(xy) != 2 or any(type(v) not in (int, float) or not np.isfinite(v) for v in xy):
                raise ValueError('手动修饰坐标无效。')
            if not -r <= xy[0] <= w+r or not -r <= xy[1] <= h+r:
                raise ValueError('手动修饰位置超出照片。')
        if rec['mode'] in ('heal', 'clone'):
            source = rec.get('source')
            if not isinstance(source, (list, tuple)) or len(source) != 2 or any(type(v) not in (int, float) or not np.isfinite(v) for v in source):
                raise ValueError('手动修饰取样坐标无效。')
            if not 0 <= source[0] < w or not 0 <= source[1] < h:
                raise ValueError('取样点在照片以外，请重新取样。')
        # Bound the work represented by a hostile or accidentally huge path.
        pts = np.asarray(points, np.float64)
        if len(pts) > 1 and np.linalg.norm(np.diff(pts, axis=0), axis=1).sum() / max(.5, r*tools['spacing']/50) > 100000:
            raise ValueError('单笔路径过长，请分几笔绘制。')
    if total > MAX_TOTAL_POINTS:
        raise ValueError('手动笔画过多，请先保存项目。')
    return records

def dabs(points, radius,spacing=15):
    pts = np.asarray(points, np.float32)
    if len(pts) == 1: return pts
    lengths = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    keep = np.r_[True, lengths > 1e-5]
    pts = pts[keep]
    if len(pts) == 1: return pts
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    at = np.arange(0, arc[-1], max(.5, radius*float(spacing)/50))
    if not len(at) or arc[-1]-at[-1] > .1: at = np.r_[at, arc[-1]]
    return np.column_stack([np.interp(at, arc, pts[:,i]) for i in (0,1)])

def brush_bounds(rec,shape):
    h, w = shape; r = float(rec['radius']); pts = np.asarray(rec['points'])
    # Healing needs unpainted context around the mask, not a tight bounding box.
    reach = r*2+3 if rec['mode'] == 'heal' else r+2
    a,b = np.maximum(0, np.floor(pts.min(axis=0)-reach)).astype(int)
    c,d = np.minimum([w,h], np.ceil(pts.max(axis=0)+reach+1)).astype(int)
    return (a,b,c,d) if a<c and b<d else (0,0,0,0)

def coverage(rec, shape):
    a,b,c,d=brush_bounds(rec,shape);r=float(rec['radius'])
    if a>=c or b>=d:return (0,0,0,0),np.zeros((0,0),np.float32)
    field = np.zeros((d-b,c-a), np.float32)
    hard = float(rec['hardness'])/100; flow = float(rec['flow'])/100
    for x,y in dabs(rec['points'], r,rec.get('spacing',15)):
        x -= a; y -= b
        x0,y0 = max(0,int(np.floor(x-r))), max(0,int(np.floor(y-r)))
        x1,y1 = min(c-a,int(np.ceil(x+r+1))), min(d-b,int(np.ceil(y+r+1)))
        if x0 >= x1 or y0 >= y1: continue
        yy,xx = np.ogrid[y0:y1,x0:x1]
        distance = np.hypot(xx-x,yy-y)/r
        t = np.clip((1-distance)/max(1e-5,1-hard),0,1)
        weight = t*t*(3-2*t)*flow
        dst = field[y0:y1,x0:x1]
        dst += (1-dst)*weight
    return (a,b,c,d), field

def linear(rgb):
    v = np.clip(rgb/255.,0,1)
    return np.where(v <= .04045, v/12.92, ((v+.055)/1.055)**2.4)

def display(rgb):
    v = np.clip(rgb,0,1)
    return (np.where(v <= .0031308, v*12.92, 1.055*v**(1/2.4)-.055)*255).astype(np.float32)

def smooth(rgb,sigma):
    # Large RAW brushes need broad colour context, not a thousands-tap kernel.
    # Downsample only this low-frequency estimate; source texture stays full size.
    h,w=rgb.shape[:2];factor=min(1,12/sigma)
    if factor==1:return cv2.GaussianBlur(rgb,(0,0),sigma)
    small=cv2.resize(rgb,(max(1,round(w*factor)),max(1,round(h*factor))),interpolation=cv2.INTER_AREA)
    return cv2.resize(cv2.GaussianBlur(small,(0,0),sigma*factor),(w,h),interpolation=cv2.INTER_LINEAR)

def source_point(rec,xy):
    """Inverse sample map; 100% / 0 degrees preserves legacy integer copying."""
    if rec.get('scale',100)==100 and rec.get('angle',0)==0 and not rec.get('flip_x',False) and not rec.get('flip_y',False):
        offset=np.asarray(rec['source'],np.float32)-np.asarray(rec['points'][0],np.float32)
        return np.asarray(xy,np.float32)+offset
    delta=np.asarray(xy,np.float32)-np.asarray(rec['points'][0],np.float32)
    angle=np.deg2rad(rec.get('angle',0));co,si=np.cos(angle),np.sin(angle)
    x=(co*delta[...,0]+si*delta[...,1])/(rec.get('scale',100)/100)
    y=(-si*delta[...,0]+co*delta[...,1])/(rec.get('scale',100)/100)
    if rec.get('flip_x',False):x=-x
    if rec.get('flip_y',False):y=-y
    return np.stack((x,y),axis=-1)+np.asarray(rec['source'],np.float32)

def gradient_heal(target,sampled,mask):
    # Only the bounded brush ROI is solved. Keep float data and never quantize
    # a RAW brush to uint8; destination boundary defines the repaired colour.
    if min(target.shape[:2])<4:return sampled
    from vendor.pie.poisson import blend_dst_numpy
    h,w=target.shape[:2]
    if max(h,w)>768:
        factor=768/max(h,w);size=(max(4,round(w*factor)),max(4,round(h*factor)))
        small_target=cv2.resize(target,size,interpolation=cv2.INTER_AREA)
        small_source=cv2.resize(sampled,size,interpolation=cv2.INTER_AREA)
        small_mask=cv2.resize(mask,size,interpolation=cv2.INTER_AREA)
        coarse=blend_dst_numpy(small_target,small_source,small_mask.copy(),np.array([0,0]),False,channels_dim=2)
        # Solve broad tone on a bounded grid; restore original source detail.
        result=cv2.resize(coarse,(w,h),interpolation=cv2.INTER_LINEAR)+sampled-cv2.resize(small_source,(w,h),interpolation=cv2.INTER_LINEAR)
    else:
        result=blend_dst_numpy(target,sampled,mask.copy(),np.array([0,0]),False,channels_dim=2)
    if not np.isfinite(result).all():raise ValueError('修复融合产生无效数值，请降低笔刷大小。')
    return result.astype(np.float32)

def apply(rgb, records, enabled=True, checked=True, restore_rgb=None,copy_output=True,source_rgb=None):
    if not enabled or not records: return rgb
    if checked: validate_records(records, rgb.shape[:2])
    out = rgb.astype(np.float32, copy=True) if copy_output else rgb
    if out.dtype!=np.float32:raise ValueError('手动修饰需要浮点图像。')
    h,w = out.shape[:2]
    for rec in records:
        if not rec.get('enabled',True):continue
        box, cov = coverage(rec, (h,w)); a,b,c,d = box
        alpha = cov*float(rec['opacity'])/100
        if not alpha.size or not np.any(alpha): continue
        target = out[b:d,a:c].copy(); mode = rec['mode']
        if mode in ('dodge','burn'):
            luminance = (target/255.) @ np.array([.2126,.7152,.0722],np.float32)
            tone = rec['tone']
            influence = (1-luminance)**2 if tone=='shadows' else luminance**2 if tone=='highlights' else 4*luminance*(1-luminance) if tone=='midtones' else 1
            exposure = alpha*influence*float(rec['strength'])/100
            lin = linear(target); gain = 2**(exposure if mode=='dodge' else -exposure)
            if mode=='dodge':
                # One gain for RGB preserves linear channel ratios. Headroom
                # limits avoid creating clipped coloured edges on bright skin.
                gain = np.minimum(gain, 1/np.maximum(lin.max(axis=2),1e-6))
            edited = display(lin*gain[:,:,None])
            changed = alpha>0
            out[b:d,a:c][changed] = edited[changed]
            continue
        if mode=='restore': edited = (rgb if restore_rgb is None else restore_rgb)[b:d,a:c]
        else:
            yy,xx = np.mgrid[b:d,a:c].astype(np.float32)
            sampled_points=source_point(rec,np.stack((xx,yy),axis=2)).astype(np.float32)
            sx,sy=sampled_points[:,:,0],sampled_points[:,:,1]
            sampled = cv2.remap(out if source_rgb is None else source_rgb,sx,sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
            alpha *= (sx>=0)&(sx<=w-1)&(sy>=0)&(sy<=h-1)
            edited = sampled
            if mode=='heal' and rec.get('healing','texture')=='gradient':
                valid=(sx>=0)&(sx<=w-1)&(sy>=0)&(sy<=h-1)
                edited=gradient_heal(target,sampled,((cov>.03)&valid).astype(np.float32))
            elif mode=='heal':
                sigma = max(1,float(rec['radius'])*.8)
                clean = (cov<.03).astype(np.float32)
                denominator = smooth(clean,sigma)
                surround = smooth(target*clean[:,:,None],sigma)/np.maximum(denominator[:,:,None],1e-5)
                fallback = smooth(target,sigma)
                surround[denominator<.01] = fallback[denominator<.01]
                texture = sampled-smooth(sampled,max(1,float(rec['radius'])*.35))
                edited = np.clip(surround+texture,0,255)
        changed = alpha>0
        out[b:d,a:c][changed] = np.clip(target+(edited-target)*alpha[:,:,None],0,255)[changed]
    return np.clip(out,0,255) if copy_output else out

def scaled(record, factor):
    rec = copy.deepcopy(record)
    rec['points'] = [[x*factor,y*factor] for x,y in rec['points']]
    rec['radius'] = max(.5,rec['radius']*factor)
    if 'source' in rec: rec['source'] = [v*factor for v in rec['source']]
    return rec
