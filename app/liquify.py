"""Manual liquify: composed inverse displacement, compact brushes, no inpainting.

Field coordinates are original image pixels on a regular endpoint-aligned grid.
RGB is never fed back into the next stroke. Only the inverse map accumulates.
"""
import io,zipfile
import cv2,numpy as np

MAX_GRID=1537
TOOLS=('push','bloat','pucker','restore','freeze','thaw','twirl','smooth','push_left')

def grid_shape(shape):
    h,w=map(int,shape);step=max(1,(max(h,w)-1)/(MAX_GRID-1))
    return max(2,int(np.ceil((h-1)/step))+1),max(2,int(np.ceil((w-1)/step))+1)

def create(shape):
    shape=tuple(map(int,shape));gh,gw=grid_shape(shape)
    return {'shape':shape,'flow':np.zeros((gh,gw,2),np.float32),'freeze':np.zeros((gh,gw),np.float32)}

def active(state):return state is not None and bool(np.any(state['flow']))

def snapshot(state):
    if state is None:return None
    mask=np.any(state['flow']!=0,axis=2)|(state['freeze']!=0)
    y,x=np.nonzero(mask)
    bounds=(int(x.min()),int(y.min()),int(x.max())+1,int(y.max())+1) if x.size else (0,0,0,0)
    a,b,c,d=bounds
    return {'shape':tuple(state['shape']),'bounds':bounds,'flow':state['flow'][b:d,a:c].copy(),'freeze':state['freeze'][b:d,a:c].copy()}

def restore(record,shape):
    if record is None:return None
    if tuple(record['shape'])!=tuple(shape):raise ValueError('液化坐标与照片尺寸不一致。')
    state=create(shape);a,b,c,d=map(int,record['bounds']);gh,gw=state['freeze'].shape
    f=np.asarray(record['flow']);p=np.asarray(record['freeze'])
    if not (0<=a<=c<=gw and 0<=b<=d<=gh) or f.shape!=(d-b,c-a,2) or p.shape!=(d-b,c-a):raise ValueError('液化网格尺寸无效。')
    if f.dtype!=np.float32 or p.dtype!=np.float32 or not np.isfinite(f).all() or not np.isfinite(p).all():raise ValueError('液化网格数据无效。')
    if np.max(np.abs(f),initial=0)>max(shape) or np.min(p,initial=0)<0 or np.max(p,initial=0)>1:raise ValueError('液化位移或保护范围无效。')
    state['flow'][b:d,a:c]=f;state['freeze'][b:d,a:c]=p
    if jacobian(state).min()<.18:raise ValueError('液化网格发生折叠，已拒绝载入。')
    return state

def equal(a,b):
    if a is None or b is None:
        other=b if a is None else a
        return other is None or other['bounds']==(0,0,0,0)
    return a['shape']==b['shape'] and a['bounds']==b['bounds'] and all(np.array_equal(a[k],b[k]) for k in ('flow','freeze'))

def nbytes(record):return 0 if record is None else record['flow'].nbytes+record['freeze'].nbytes

def spacing(state):
    h,w=state['shape'];gh,gw=state['freeze'].shape
    return (w-1)/(gw-1),(h-1)/(gh-1)

def jacobian(state):
    sx,sy=spacing(state);return cell_jacobian(state['flow'],sx,sy)

def cell_jacobian(f,sx,sy):
    # Bilinear-map determinants are affine within each cell, so their extrema
    # lie at the four corners. Centred finite differences can miss a fold.
    top=(f[:-1,1:]-f[:-1,:-1])/sx;bottom=(f[1:,1:]-f[1:,:-1])/sx
    left=(f[1:,:-1]-f[:-1,:-1])/sy;right=(f[1:,1:]-f[:-1,1:])/sy
    return np.minimum.reduce([(1+dx[:,:,0])*(1+dy[:,:,1])-dx[:,:,1]*dy[:,:,0]
        for dx,dy in ((top,left),(top,right),(bottom,left),(bottom,right))])

def stroke(state,start,end,radius,strength,tool,density=None,dose=None,reverse=False):
    if tool not in TOOLS:raise ValueError('未知液化工具。')
    radius=max(5,float(radius));strength=float(np.clip(strength,0,100))/100
    distance=float(np.linalg.norm(np.subtract(end,start)))
    steps=max(1,int(np.ceil(distance/max(1,radius*.10))))
    changed=False
    previous=np.asarray(start,np.float32)
    for i in range(1,steps+1):
        point=np.asarray(start,np.float32)+(np.asarray(end,np.float32)-np.asarray(start,np.float32))*i/steps
        amount=1 if dose is None else max(0,float(dose))/steps
        changed=stamp(state,point,point-previous,radius,strength,tool,density,amount,reverse) or changed;previous=point
    return changed

def stamp(state,point,delta,radius,strength,tool,density=None,dose=1,reverse=False):
    sx,sy=spacing(state);h,w=state['shape'];gh,gw=state['freeze'].shape
    # Guard cells cover interpolation and all finite differences at the edge.
    a=max(0,int(np.floor((point[0]-radius)/sx))-2);c=min(gw,int(np.ceil((point[0]+radius)/sx))+3)
    b=max(0,int(np.floor((point[1]-radius)/sy))-2);d=min(gh,int(np.ceil((point[1]+radius)/sy))+3)
    if a>=c or b>=d or strength<=0:return False
    y,x=np.mgrid[b:d,a:c].astype(np.float32);px=x*sx;py=y*sy
    dx=px-point[0];dy=py-point[1];r2=(dx*dx+dy*dy)/(radius*radius)
    kernel=np.maximum(0,1-r2)**3
    if density is not None:
        inner=float(np.clip(density,0,100))*.009
        fade=np.clip((1-np.sqrt(r2))/max(.1,1-inner),0,1)
        kernel=fade*fade*(3-2*fade)
    if tool in ('freeze','thaw'):
        if density is None:kernel=np.clip((1-np.sqrt(r2))/.20,0,1)
        old=state['freeze'][b:d,a:c];new=old+(1-old)*kernel*strength if tool=='freeze' else old*(1-kernel*strength)
        if np.array_equal(old,new):return False
        old[:]=new;return True
    # Pin frame boundary, and leave protected pixels at their current mapping.
    taper=np.clip(np.minimum.reduce((px,py,w-1-px,h-1-py))/max(2,min(radius*.15,30)),0,1)
    kernel*=taper*(1-state['freeze'][b:d,a:c])
    old=state['flow'][b:d,a:c].copy()
    qx=px.copy();qy=py.copy()
    if tool=='push':qx-=delta[0]*kernel*strength;qy-=delta[1]*kernel*strength
    elif tool=='push_left':
        # Screen coordinates: an upward drag moves content left. Sampling uses
        # the opposite direction; Alt reverses the tangent displacement.
        direction=-1 if reverse else 1
        qx-=delta[1]*kernel*strength*direction;qy+=delta[0]*kernel*strength*direction
    elif tool in ('bloat','pucker'):
        sign=-1 if tool=='bloat' else 1
        qx+=sign*dx*kernel*strength*.055*dose;qy+=sign*dy*kernel*strength*.055*dose
    elif tool=='twirl':
        angle=kernel*strength*.055*dose*(-1 if reverse else 1)
        co,si=np.cos(angle),np.sin(angle)
        qx=point[0]+co*dx+si*dy;qy=point[1]-si*dx+co*dy
    softened=None
    if tool=='smooth':softened=cv2.GaussianBlur(old,(0,0),max(.5,radius*.15/max(sx,sy)))
    for attempt in range(7):
        amount=.5**attempt
        if tool=='restore':new=old*(1-np.clip(kernel[:,:,None]*strength*amount*dose,0,1))
        elif tool=='smooth':new=old+(softened-old)*np.clip(kernel[:,:,None]*strength*amount*dose,0,1)
        else:
            qxx=px+(qx-px)*amount;qyy=py+(qy-py)*amount
            # Read complete OLD flow; no write occurs until candidate passes.
            sampled=cv2.remap(state['flow'],qxx/sx,qyy/sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
            new=sampled+np.stack((qxx-px,qyy-py),axis=2)
        new[kernel==0]=old[kernel==0]
        state['flow'][b:d,a:c]=new
        local=state['flow'][max(0,b-1):min(gh,d+1),max(0,a-1):min(gw,c+1)]
        if min(local.shape[:2])>=2:
            det=cell_jacobian(local,sx,sy)
            safe=np.isfinite(new).all() and det.min()>=.25
        else:safe=True
        state['flow'][b:d,a:c]=old
        if safe:
            if np.array_equal(new,old):return False
            state['flow'][b:d,a:c]=new;return True
    return False

def maps(state,bounds):
    a,b,c,d=bounds;sx,sy=spacing(state)
    y,x=np.mgrid[b:d,a:c].astype(np.float32)
    delta=cv2.remap(state['flow'],x/sx,y/sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    return x+delta[:,:,0],y+delta[:,:,1],delta

def crop(image,state,bounds):
    a,b,c,d=bounds
    if not active(state):return image[b:d,a:c].copy()
    x,y,delta=maps(state,bounds)
    result=cv2.remap(image,x,y,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
    unchanged=np.all(delta==0,axis=2);result[unchanged]=image[b:d,a:c][unchanged]
    return result

def apply(image,state):
    if not active(state):return image
    h,w=image.shape[:2];sx,sy=spacing(state);ys,xs=np.nonzero(np.any(state['flow']!=0,axis=2))
    a=max(0,int((xs.min()-1)*sx));c=min(w,int(np.ceil((xs.max()+1)*sx))+1)
    b=max(0,int((ys.min()-1)*sy));d=min(h,int(np.ceil((ys.max()+1)*sy))+1)
    result=image.copy()
    # Bounded strips avoid allocating multiple full RAW coordinate arrays.
    for top in range(b,d,256):result[top:min(d,top+256),a:c]=crop(image,state,(a,top,c,min(d,top+256)))
    return result

def freeze_crop(state,bounds):
    a,b,c,d=bounds;sx,sy=spacing(state);y,x=np.mgrid[b:d,a:c].astype(np.float32)
    return cv2.remap(state['freeze'],x/sx,y/sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)

def encode(record):
    buffer=io.BytesIO();np.savez_compressed(buffer,shape=np.asarray(record['shape'],np.int32),bounds=np.asarray(record['bounds'],np.int32),flow=record['flow'],freeze=record['freeze']);return buffer.getvalue()

def decode(data,shape):
    buffer=io.BytesIO(data)
    with zipfile.ZipFile(buffer) as archive:
        limits={'shape.npy':512,'bounds.npy':512,'flow.npy':MAX_GRID*MAX_GRID*8+512,'freeze.npy':MAX_GRID*MAX_GRID*4+512}
        if len(archive.infolist())!=4 or any(item.filename not in limits or item.file_size>limits[item.filename] for item in archive.infolist()):raise ValueError('液化项目数据过大或无效。')
    buffer.seek(0)
    with np.load(buffer,allow_pickle=False) as arrays:
        if arrays['shape'].dtype!=np.int32 or arrays['shape'].shape!=(2,) or arrays['bounds'].dtype!=np.int32 or arrays['bounds'].shape!=(4,):raise ValueError('液化项目坐标无效。')
        record={'shape':tuple(map(int,arrays['shape'])),'bounds':tuple(map(int,arrays['bounds'])),'flow':arrays['flow'].copy(),'freeze':arrays['freeze'].copy()}
    return restore(record,shape)
