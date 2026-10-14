"""GPU-registrable preview composition. Preview overlays never enter recipes."""
import numpy as np
import cv2
import color_science as cs
from develop_engine import point_weight

def source_coordinates(points,shape,optics,flow,body,face_fields):
    if len(points)>30000:return np.concatenate([source_coordinates(points[i:i+30000],shape,optics,flow,body,face_fields) for i in range(0,len(points),30000)])
    from develop_optics import inverse_points
    from liquify_guides import sample_grid
    from photo_body import inverse_points as body_inverse
    q=inverse_points(points,shape,optics)
    if flow is not None:q=q+sample_grid(flow,q,(0,0,shape[1],shape[0]))
    if body is not None:q=body_inverse(q,body)
    delta=np.zeros_like(q)
    for field in face_fields:delta+=sample_grid(field['grid'],q,field['roi'])
    return q+delta

def mapped_source(source,bounds,size,optics,flow,body,face_fields):
    a,b,c,d=bounds;w,h=size
    xx,yy=np.meshgrid(a+(np.arange(w,dtype=np.float32)+.5)*(c-a)/w-.5,b+(np.arange(h,dtype=np.float32)+.5)*(d-b)/h-.5)
    q=source_coordinates(np.stack([xx,yy],2).reshape(-1,2),source.shape,optics,flow,body,face_fields).reshape(h,w,2)
    return cv2.remap(source,q[:,:,0],q[:,:,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)

def compose_mapped(after,before,original,float_after,bounds,size,mode,clipping,point_source,point_record,optics,flow,body,face_fields,point_data=None,point_document=None,proof=None):
    if proof is not None:
        from develop_output import preview as display
        if mode in ('before','split','side','wipe-before'):before=display(before,proof)
        if mode in ('original','wipe-original'):original=display(original,proof)
    if mode in ('before','split','side','wipe-before') and before.shape[:2]!=after.shape[:2]:before=cv2.resize(before,(after.shape[1],after.shape[0]),interpolation=cv2.INTER_LINEAR)
    if mode in ('original','wipe-original') and original.shape[:2]!=after.shape[:2]:original=cv2.resize(original,(after.shape[1],after.shape[0]),interpolation=cv2.INTER_LINEAR)
    mapped=None
    exact=point_data is not None
    if point_source is not None and point_record is not None:
        if exact:
            from develop_engine import point_mask
            point_source=point_mask(point_source,point_data,point_record,point_document)
        mapped=mapped_source(point_source,bounds,size,optics,flow,body,face_fields)
    return preview(after,before,original,float_after,bounds,size,mode,clipping,mapped,point_record,True,exact)

def drag_preview(source,skin,original,scene,data,layers,output):
    from types import SimpleNamespace
    from creative_color import apply
    from local_develop import apply as local_apply
    from develop_output import preview as display
    height,width=source.shape[:2];factor=min(1,1400/max(height,width));size=(max(2,round(width*factor)),max(2,round(height*factor)))
    small=cv2.resize(source,size,interpolation=cv2.INTER_AREA);skin=cv2.resize(skin,size,interpolation=cv2.INTER_AREA)
    document=SimpleNamespace(rgb=cv2.resize(original,size,interpolation=cv2.INTER_AREA),scene=None if scene is None else cv2.resize(scene,size,interpolation=cv2.INTER_AREA))
    edited=apply(small,data,skin,document);local=[]
    for layer in layers:
        item=dict(layer,mask=cv2.resize(layer['mask'].astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0,parameters=dict(layer['parameters']))
        item['parameters']['feather']*=factor;item['parameters']['expand']*=factor;local.append(item)
    if local:edited=local_apply(edited,local,small)
    return display(edited,output)

def filter_previews(source,skin,original,scene,recipes,output,amount=1.):
    """Preset thumbnails use the same color engine, profile and CUDA domain."""
    from types import SimpleNamespace
    from creative_color import apply
    from develop_output import preview as display
    height,width=source.shape[:2];factor=min(1,480/max(height,width));size=(max(2,round(width*factor)),max(2,round(height*factor)))
    rgb=cv2.resize(source,size,interpolation=cv2.INTER_AREA);mask=cv2.resize(skin,size,interpolation=cv2.INTER_AREA)
    document=SimpleNamespace(rgb=cv2.resize(original,size,interpolation=cv2.INTER_AREA),scene=None if scene is None else cv2.resize(scene,size,interpolation=cv2.INTER_AREA))
    images=[]
    for data in recipes:
        if data is None:
            images.append(np.full((size[1],size[0],3),235,np.uint8));continue
        rendered=apply(rgb,data,mask,document);rendered=rgb+(rendered-rgb)*amount
        images.append(display(rendered,output))
    return np.stack(images,axis=0)

def thumbnail_inputs(source,skin,original,scene,max_side=480):
    """Downsample on the worker before uploading thumbnail inputs to CUDA."""
    h,w=source.shape[:2];factor=min(1,max_side/max(h,w));size=(max(2,round(w*factor)),max(2,round(h*factor)))
    def resized(array):
        return None if array is None else cv2.resize(array,size,interpolation=cv2.INTER_AREA)
    return resized(source),resized(skin),resized(original),resized(scene)

def drag_display(frame,original,bounds,size,shape,optics,flow,body,face_fields,localcut):
    a,b,c,d=bounds;w,h=size;ph,pw=frame.shape[:2];height,width=shape[:2]
    xx,yy=np.meshgrid(a+(np.arange(w,dtype=np.float32)+.5)*(c-a)/w-.5,b+(np.arange(h,dtype=np.float32)+.5)*(d-b)/h-.5)
    q=source_coordinates(np.stack([xx,yy],2).reshape(-1,2),shape,optics,flow,body,face_fields).reshape(h,w,2)
    pixels=cv2.remap(frame,(q[:,:,0]+.5)*pw/width-.5,(q[:,:,1]+.5)*ph/height-.5,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
    cut=int(round(localcut*w/max(1,c-a)))
    if cut:pixels[:,:cut]=cv2.remap(original,xx[:,:cut],yy[:,:cut],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
    return pixels

def preview(after,before,original,float_after,bounds,size,mode,clipping,point_source=None,point_record=None,mapped=False,mask_pixels=False):
    a,b,c,d=bounds;width,height=size
    current=cv2.resize(after[b:d,a:c],size,interpolation=cv2.INTER_LINEAR)
    if clipping:
        values=cv2.resize(float_after[b:d,a:c],size,interpolation=cv2.INTER_LINEAR)
        current[values.max(2)>=255]=np.array([245,58,65],np.uint8);current[values.max(2)<=0]=np.array([58,96,245],np.uint8)
    if point_record is not None and point_source is not None:
        sample=point_source if mapped else cv2.resize(point_source[b:d,a:c],size,interpolation=cv2.INTER_LINEAR)
        alpha=sample[:,:,0]/255*.6 if mask_pixels else point_weight(cs.oklab(cs.decode(sample/255)),point_record)*.6
        current=np.clip(current*(1-alpha[:,:,None])+np.array([175,106,236],np.float32)*alpha[:,:,None],0,255).astype(np.uint8)
    if mode=='before':current=cv2.resize(before[b:d,a:c],size,interpolation=cv2.INTER_LINEAR)
    elif mode=='original':current=cv2.resize(original[b:d,a:c],size,interpolation=cv2.INTER_LINEAR)
    elif mode in ('wipe-before','wipe-original'):
        reference=original if mode=='wipe-original' else before
        left=cv2.resize(reference[b:d,a:c],size,interpolation=cv2.INTER_LINEAR)
        return np.stack([left,current],axis=0)
    elif mode=='split':
        old=cv2.resize(before[b:d,a:c],size,interpolation=cv2.INTER_LINEAR);current[:,:width//2]=old[:,:width//2]
    elif mode=='side':
        half=max(1,width//2);scale=min(max(1,half-8)/max(1,c-a),height/max(1,d-b));iw=max(1,round((c-a)*scale));ih=max(1,round((d-b)*scale))
        old=cv2.resize(before[b:d,a:c],(iw,ih),interpolation=cv2.INTER_LINEAR);new=cv2.resize(current,(iw,ih),interpolation=cv2.INTER_LINEAR)
        result=np.empty((height,width,3),np.uint8);result[:]=np.array([233,237,242],np.uint8);y=(height-ih)//2;x=(half-iw)//2
        result[y:y+ih,x:x+iw]=old;result[y:y+ih,half+x:half+x+iw]=new;current=result
    return current
