"""Calibrated local geometry: one inverse sampling field, no generated background."""
import copy
import cv2,numpy as np
import smart_face
from reshape_settings import KEYS,signature,active


REVISION=21
JAW=[127,234,93,132,58,172,136,150,149,176,148,152,377,400,378,379,365,397,288,361,323,454,356]
SKIN_CLASSES=(1,2,3,4,5,6,10,11,12,13,14)

def _cancel(cancel):
    if cancel is not None and cancel.is_set():raise RuntimeError('已取消面部重塑，照片未改变。')

def _sample(image,points,context=None):
    points=np.asarray(points,dtype=np.float32)
    if context is not None:
        a,b,c,d=context;points=(points-[a,b])*[image.shape[1]/(c-a),image.shape[0]/(d-b)]
    return cv2.remap(image,points[:,0].astype(np.float32)[:,None],points[:,1].astype(np.float32)[:,None],
        cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)[:,0]

def _resample(points,count):
    distances=np.r_[0,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    x=np.linspace(0,distances[-1],count)
    return np.column_stack([np.interp(x,distances,points[:,i]) for i in (0,1)])

def calibrate_contour(original,raw,mesh,context,labels):
    """Calibrate only supported visible skin edges; occluders are fixed anchors.

    Parser masks are independent of acne/beauty safety masks. The neck remains
    skin, so a semantic face/neck seam is never treated as an image boundary.
    """
    raw=np.asarray(raw,np.float64);p=raw.copy();width=np.linalg.norm(p[0]-p[32])
    reference=np.vstack([_resample(mesh[JAW[:12]],17),_resample(mesh[JAW[11:]],17)[1:]])
    before=p[:33].copy();seed=before.copy();turns=[]
    for i in range(1,32):
        first=before[i]-before[i-1];second=before[i+1]-before[i]
        cosine=float(first@second/max(1e-6,np.linalg.norm(first)*np.linalg.norm(second)))
        if cosine<.35:
            replacement=(before[i-1]+before[i+1])/2
            if np.linalg.norm(reference[i]-before[i])<width*.10:replacement=.75*replacement+.25*reference[i]
            seed[i]=replacement;turns.append(i)
    seed[16]=before[16]
    # Thin wisps may be inside the face, but the major hair mass and foreground
    # flowers cannot be pulled as though they were facial skin.
    skin=np.isin(labels,SKIN_CLASSES).astype(np.float32)
    skin=cv2.GaussianBlur(skin,(0,0),.6)
    center=(p[51]+p[16])/2;confidence=np.zeros(33,np.float32);accepted=[];occluded=[]
    for i in range(33):
        lo,hi=max(0,i-1),min(32,i+1);tangent=seed[hi]-seed[lo]
        outward=np.array([tangent[1],-tangent[0]])
        outward/=max(1e-9,np.linalg.norm(outward))
        if outward@(seed[i]-center)<0:outward*=-1
        offsets=np.linspace(-width*.08,width*.08,81)
        line=seed[i]+offsets[:,None]*outward
        response=_sample(skin,line,context)
        inward=_sample(skin,seed[i]-np.linspace(.025,.085,7)[:,None]*width*outward,context)
        support=float(np.mean(inward))
        crossings=np.flatnonzero((response[:-1]>=.5)&(response[1:]<.5))
        valid=[]
        for index in crossings:
            location=line[index]
            local_inside=_sample(skin,location-np.linspace(.015,.045,5)[:,None]*width*outward,context).mean()
            local_outside=_sample(skin,location+np.linspace(.015,.040,5)[:,None]*width*outward,context).mean()
            if local_inside>.80 and local_outside<.22:valid.append(index)
        if support>.68 and valid and i not in (0,16,32):
            index=min(valid,key=lambda j:abs(offsets[j]))
            crossing=(line[index]+line[index+1])/2
            distance=np.linalg.norm(crossing-seed[i])
            if distance<width*.065:
                seed[i]=.15*seed[i]+.85*crossing
                confidence[i]=min(1.,.72+.28*support);accepted.append(i)
        if not confidence[i]:
            # Where face meets neck, there is no outer skin boundary. Retain a
            # conservative structural jaw rather than chase that class seam.
            if support>.85 and 10<=i<=22:confidence[i]=.65
            elif support>.85 and i not in turns:confidence[i]=.35
            else:occluded.append(i)
    p[:33]=seed
    a,b,c,d=context
    hull=np.zeros(labels.shape,np.uint8)
    contour=(p[:33]-[a,b])*[labels.shape[1]/(c-a),labels.shape[0]/(d-b)]
    cv2.fillConvexPoly(hull,cv2.convexHull(np.rint(contour).astype(np.int32)),1)
    protected=(np.isin(labels,[0,6,9,17,18])&hull.astype(bool)).astype(np.uint8)
    protected=cv2.erode(protected,np.ones((3,3),np.uint8))
    ys,xs=np.nonzero(protected)
    anchors=np.empty((0,2))
    if len(xs):
        positions=np.column_stack([xs*(c-a)/labels.shape[1]+a,ys*(d-b)/labels.shape[0]+b])
        step=max(1,len(positions)//64);anchors=positions[::step][:64]
    # Strong bends are bounded by a smooth structural seed, with invisible
    # points explicitly excluded from moving control points.
    return p,confidence,anchors,{'visible_edge_points':accepted,'occluded_or_uncertain_points':occluded,
        'sharp_turns_repaired':turns,'max_calibration_shift_px':float(np.linalg.norm(p[:33]-before,axis=1).max()),
        'protected_occluder_anchors':len(anchors),'uses_beauty_or_acne_mask':False,'neck_class_in_skin':True}

def prepare_geometry(session,fi,cancel=None,backend='auto'):
    _cancel(cancel);face=session.faces[fi];mesh=np.asarray(face.points)
    lo,hi=mesh.min(axis=0),mesh.max(axis=0);bbox=[*lo,*(hi-lo)]
    from core import ROOT
    if backend not in ('auto','mediapipe'):raise ValueError('独立版使用 MediaPipe 网格定位。')
    from mesh_landmarks import controls
    from ai_runtime import RUNTIME
    raw=controls(mesh);pose=None;locator='MediaPipe mesh adapter'
    RUNTIME.mark('面部重塑定位','CPU','复用已有 MediaPipe 网格定位')
    context_labels=getattr(session,'parse_contexts',{}).get(fi)
    if context_labels is None:
        from ai_engine import square_box,parse_skin
        context=square_box(face.box,session.original.shape)
        _,_,labels=parse_skin(session.original,context,points=face.points)
    else:context,labels=context_labels
    points,confidence,anchors,report=calibrate_contour(session.original,raw,mesh,context,labels)
    visible=(~np.isin(labels,[0,6,9,17,18])).astype(np.float32)
    visible=cv2.GaussianBlur(visible,(0,0),.6)
    feature_visibility=np.clip(_sample(visible,points,context),0,1)
    _cancel(cancel)
    return {'revision':REVISION,'points':points,'raw_points':raw,'confidence':confidence,'fixed_anchors':anchors,
        'pose':pose,'locator':locator,'calibration':report,'shape':session.original.shape[:2],'feature_visibility':feature_visibility}

def _kernel(a,b):
    r2=((a[:,None]-b[None])**2).sum(axis=2)
    return r2*np.log(np.maximum(r2,1e-14))

def _fit(controls,displacements):
    n=len(controls);affine=np.column_stack([np.ones(n),controls]);kernel=_kernel(controls,controls)
    kernel.flat[::n+1]+=1e-8
    return np.linalg.solve(np.block([[kernel,affine],[affine.T,np.zeros((3,3))]]),np.vstack([displacements,np.zeros((3,2))]))

def _evaluate(query,controls,weights):
    return _kernel(query,controls)@weights[:-3]+np.column_stack([np.ones(len(query)),query])@weights[-3:]

def target_shape(geometry,values):
    p=geometry['points'];left,right=p[60:68].mean(0),p[68:76].mean(0)
    horizontal=right-left;horizontal/=np.linalg.norm(horizontal)
    vertical=np.array([-horizontal[1],horizontal[0]]);pivot=(left+right)/2
    if (p[16]-pivot)@vertical<0:vertical*=-1
    width=np.linalg.norm(p[0]-p[32]);local=(p-pivot)@np.column_stack([horizontal,vertical])
    depth=max(width*.4,local[16,1]);profile=np.sin(np.linspace(0,np.pi,33))**.65
    lower=np.clip(local[:33,1]/depth,0,1)**.45
    # Person-left is the face's anatomical left (image-right in a frontal face).
    anatomical_left=local[:33,0]>=0
    slim=np.where(anatomical_left,values.get('rs_slim_left',0),values.get('rs_slim_right',0))/100
    jaw=np.where(anatomical_left,values.get('rs_jaw_left',0),values.get('rs_jaw_right',0))/100
    jaw_profile=np.exp(-((np.arange(33)-16)/7.0)**4)
    chin_profile=np.exp(-((np.arange(33)-16)/4.5)**2)
    lateral=local[:33,0]*(-.16*slim*profile*lower+.15*jaw*jaw_profile+.16*values.get('rs_chin_width',0)/100*chin_profile)
    downward=width*.055*values.get('rs_chin_length',0)/100*chin_profile
    visibility=geometry['confidence'].copy();visibility[16]=max(.65,visibility[16])
    delta=(lateral[:,None]*horizontal+downward[:,None]*vertical)*visibility[:,None]
    delta[[0,32]]=0
    magnitude=np.linalg.norm(delta,axis=1);delta*=np.minimum(1,width*.085/np.maximum(magnitude,1e-8))[:,None]
    target=p.copy();target[:33]+=delta
    target=smart_face.targets(p,target,values,horizontal,vertical,pivot,width,
        geometry.get('feature_visibility',np.ones(len(p))),visibility)
    return target,width

def build_field(geometry,values,faces,fi,cancel=None):
    p=geometry['points'];target,width=target_shape(geometry,values);height,image_width=geometry['shape']
    lo=np.floor(p.min(0)-width*.65).astype(int);hi=np.ceil(p.max(0)+width*.65).astype(int)
    x0,y0=np.maximum(lo,[0,0]);x1,y1=np.minimum(hi,[image_width,height]);rw,rh=x1-x0,y1-y0
    origin=np.array([x0,y0]);scale=float(max(rw,rh));perimeter=[]
    for t in np.linspace(0,1,9):perimeter.extend([[x0+t*(rw-1),y0],[x0+t*(rw-1),y1-1],[x0,y0+t*(rh-1)],[x1-1,y0+t*(rh-1)]])
    fixed=np.vstack([np.unique(perimeter,axis=0),geometry['fixed_anchors']])
    others=[]
    for index,face in enumerate(faces):
        if index==fi:continue
        points=face.points[::8];inside=(points[:,0]>x0)&(points[:,0]<x1)&(points[:,1]>y0)&(points[:,1]<y1)
        fixed=np.vstack([fixed,points[inside]])
        if inside.any():others.append(face)
    resolution=min(257,max(48,round(scale))) if geometry.get('pixel_preview',False) else 257
    gw=max(48,round(rw/scale*resolution));gh=max(48,round(rh/scale*resolution))
    xx,yy=np.meshgrid(np.linspace(0,rw-1,gw),np.linspace(0,rh-1,gh));query=np.column_stack([xx.ravel(),yy.ravel()])/scale
    edge=np.minimum.reduce([xx,yy,rw-1-xx,rh-1-yy]);taper=np.clip(edge/max(4,width*.2),0,1)
    taper=taper**3*(10-15*taper+6*taper*taper)
    neighbour_guard=np.zeros((gh,gw),np.uint8)
    for face in others:
        polygon=(face.points-origin)*[(gw-1)/(rw-1),(gh-1)/(rh-1)]
        cv2.fillConvexPoly(neighbour_guard,cv2.convexHull(np.rint(polygon).astype(np.int32)),1)
    if neighbour_guard.any():
        radius=max(1,round(width*.03*(gw-1)/(rw-1)))
        neighbour_guard=cv2.dilate(neighbour_guard,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1)))
        distance=cv2.distanceTransform(1-neighbour_guard,cv2.DIST_L2,5)*scale/257
        factor=np.clip(distance/max(4,width*.13),0,1);factor=factor*factor*(3-2*factor);taper*=factor
    for attempt in range(7):
        _cancel(cancel);effective=.8**attempt;current=p+(target-p)*effective
        controls=(np.vstack([current,fixed])-origin)/scale;displacements=np.vstack([p-current,np.zeros_like(fixed)])/scale
        _,unique=np.unique(np.round(controls,8),axis=0,return_index=True);controls=controls[unique];displacements=displacements[unique]
        weights=_fit(controls,displacements);field=np.empty((len(query),2))
        for start in range(0,len(query),8192):
            _cancel(cancel);field[start:start+8192]=_evaluate(query[start:start+8192],controls,weights)*scale
        field=field.reshape(gh,gw,2).astype(np.float32)*taper[:,:,None].astype(np.float32)
        dx,dy=field[:,:,0],field[:,:,1];sx=(rw-1)/(gw-1);sy=(rh-1)/(gh-1)
        determinant=(1+np.gradient(dx,sx,axis=1))*(1+np.gradient(dy,sy,axis=0))-np.gradient(dx,sy,axis=0)*np.gradient(dy,sx,axis=1)
        if np.isfinite(field).all() and determinant.min()>.40:break
    else:raise ValueError('本图形变范围过密，请降低强度或先调整单侧。')
    return {'key':signature(values),'roi':tuple(map(int,[x0,y0,x1,y1])),'grid':field,'target_points':current,
        'effective_scale':effective,'jacobian_min':float(determinant.min()),'revision':REVISION}

def ready(cache,settings):
    return all(not active(values) or fi in cache and cache[fi].get('field',{}).get('revision')==REVISION and cache[fi].get('field',{}).get('key')==signature(values)
        for fi,values in enumerate(settings))

def prepare(session,settings,cache=None,progress=None,cancel=None,force_person=None):
    output=dict(cache or {})
    for fi,values in enumerate(settings):
        if not active(values) and fi!=force_person:continue
        _cancel(cancel);entry=dict(output.get(fi,{}))
        if entry.get('geometry',{}).get('revision')!=REVISION or fi==force_person:
            if progress:progress(f'正在校准人像 {fi+1} 的可见轮廓与遮挡…')
            entry['geometry']=prepare_geometry(session,fi,cancel)
        if active(values) and (fi==force_person or entry.get('field',{}).get('key')!=signature(values) or entry.get('field',{}).get('revision')!=REVISION):
            if progress:progress(f'正在生成人像 {fi+1} 的连续形变…')
            entry['field']=build_field(entry['geometry'],values,session.faces,fi,cancel)
        elif not active(values):entry.pop('field',None)
        output[fi]=entry
    # Review simultaneous people's fields before committing a cache. Limit
    # their combined displacement if the overlap would fold the image.
    for attempt in range(8):
        _cancel(cancel);plan=_dense_plan(output,settings)
        if plan is None:break
        _,mx,my=plan
        determinant=np.gradient(mx,axis=1)*np.gradient(my,axis=0)-np.gradient(mx,axis=0)*np.gradient(my,axis=1)
        if np.isfinite(determinant).all() and determinant.min()>.35:break
        for fi,values in enumerate(settings):
            if not active(values):continue
            entry=dict(output[fi]);field=dict(entry['field']);field['grid']=field['grid']*.8
            p=entry['geometry']['points'];field['target_points']=p+(field['target_points']-p)*.8
            field['effective_scale']*=.8;entry['field']=field;output[fi]=entry
    else:raise ValueError('相邻人物的形变过密，请降低强度。')
    _cancel(cancel)
    return output

def _fields(cache,settings):
    if not ready(cache,settings):return []
    return [cache[fi]['field'] for fi,values in enumerate(settings) if active(values)]

def _dense_plan(cache,settings,bounds=None):
    fields=_fields(cache,settings)
    if not fields:return None
    if bounds is None:
        bounds=(min(f['roi'][0] for f in fields),min(f['roi'][1] for f in fields),
                max(f['roi'][2] for f in fields),max(f['roi'][3] for f in fields))
    a,b,c,d=map(int,bounds);xx,yy=np.meshgrid(np.arange(a,c,dtype=np.float32),np.arange(b,d,dtype=np.float32))
    mx,my=xx.copy(),yy.copy()
    for field in fields:
        x,y,z,t=field['roi'];x0,y0,x1,y1=max(a,x),max(b,y),min(c,z),min(d,t)
        if x0>=x1 or y0>=y1:continue
        grid=field['grid'];gh,gw=grid.shape[:2]
        qx=(xx[y0-b:y1-b,x0-a:x1-a]-x)*(gw-1)/(z-x-1)
        qy=(yy[y0-b:y1-b,x0-a:x1-a]-y)*(gh-1)/(t-y-1)
        delta=cv2.remap(grid,qx.astype(np.float32),qy.astype(np.float32),cv2.INTER_LINEAR)
        mx[y0-b:y1-b,x0-a:x1-a]+=delta[:,:,0];my[y0-b:y1-b,x0-a:x1-a]+=delta[:,:,1]
    return (a,b,c,d),mx,my

def apply(rgb,settings,cache):
    plan=_dense_plan(cache,settings)
    if plan is None:return rgb,False
    (a,b,c,d),mx,my=plan
    # Validate the combined field too: separate positive maps do not guarantee
    # that overlapping people's fields can safely be added.
    determinant=np.gradient(mx,axis=1)*np.gradient(my,axis=0)-np.gradient(mx,axis=0)*np.gradient(my,axis=1)
    minimum=float(determinant.min())
    if not np.isfinite(minimum) or minimum<=.25:raise ValueError('多人物形变发生过度压缩，请降低相邻人物的强度。')
    output=rgb.copy();output[b:d,a:c]=cv2.remap(rgb,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
    return output,True

def display_mask(mask,cache,settings,bounds):
    plan=_dense_plan(cache,settings,bounds)
    a,b,c,d=bounds
    if plan is None:return mask[b:d,a:c]
    _,mx,my=plan
    return cv2.remap(mask.astype(np.uint8),mx,my,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)>0

def notices(cache,settings):
    messages=[]
    for fi,values in enumerate(settings):
        if not active(values) or fi not in cache:continue
        geometry=cache[fi].get('geometry',{});report=geometry.get('calibration',{})
        if report.get('occluded_or_uncertain_points'):messages.append(f'人像 {fi+1} 遮挡处已保守限制形变')
        if cache[fi].get('field',{}).get('effective_scale',1)<1:messages.append(f'人像 {fi+1} 已限制强度以保护边缘')
    return messages
