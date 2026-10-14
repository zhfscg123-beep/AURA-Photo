"""AI per-person face/body components and editable local adjustment layers."""
import hashlib,copy
import cv2,numpy as np
from core import ROOT,FEATURES,OVAL
BODY_HASH='c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0'
PARTS={'person':'整个人物','skin':'面部皮肤（含鼻部）','body':'身体皮肤（含耳朵）',
       'brows':'眉毛','sclera':'眼睛巩膜','iris':'虹膜和瞳孔','lips':'嘴唇','teeth':'牙齿','hair':'头发','clothes':'衣服'}
LOCAL_DEFAULTS={'exposure':0.,'temperature':0.,'tint':0.,'saturation':0.,'texture':0.,'smooth':0.,'feather':2.,'expand':0.,'opacity':100.}
LOCAL_RANGES={'exposure':(-2.,2.),**{k:(-100.,100.) for k in ('temperature','tint','saturation','texture')},'smooth':(0.,100.),'feather':(0.,100.),'expand':(-100.,100.),'opacity':(0.,100.)}
MAX_LAYERS=32
from local_develop import EXTRA as LOCAL_EXTRA
LOCAL_DEFAULTS.update({k:0 for k,_,_,_ in LOCAL_EXTRA});LOCAL_RANGES.update({k:(lo,hi) for k,_,lo,hi in LOCAL_EXTRA})
LOCAL_DEFAULTS['curve_saturation']=100.
LOCAL_DEFAULTS['strength']=100.;LOCAL_RANGES['strength']=(0.,200.)
LOCAL_DEFAULTS['edge_protect']=0.;LOCAL_RANGES['edge_protect']=(0.,100.)
LAYER_FIELDS=('color_process','gradient','range','components','component_base','color_recipe','color_preparation','filter_link','ai_region')

def soft_edge(mask,width=2):
    return np.clip(cv2.distanceTransform(np.pad(mask.astype(np.uint8),1),cv2.DIST_L2,5)[1:-1,1:-1]/max(1,width),0,1).astype(np.float32)

def skin_blend(f):
    """Smooth photometric falloff, separate from the selectable skin mask.

    Face-scale smooth falloff at the exterior and internal occlusion edges.
    Eye openings remain protected without fading away their surrounding skin.
    This is independent from precise blemish detection and editable masks.
    """
    mask=getattr(f,'beauty_mask',f.mask)
    binary=(mask>0).astype(np.uint8)
    eyes=getattr(f,'beauty_eye_mask',np.zeros(mask.shape,bool))
    key=(2,hashlib.blake2b(mask.tobytes()+eyes.tobytes(),digest_size=12).hexdigest(),float(f.width))
    cached=getattr(f,'_skin_blend_cache',None)
    if cached is not None and cached[0]==key:return cached[1]
    outside=np.pad(binary,1);cv2.floodFill(outside,None,(0,0),2)
    silhouette=(outside!=2)[1:-1,1:-1]
    distance=soft_edge(silhouette,max(3,f.width*.045))
    # Filling holes above used to suppress feathering around isolated hair
    # islands. Those edges then used only the 0.3% selection edge, making a
    # bright/dark seam. Treat them explicitly while excluding the eye veto.
    interior=soft_edge(binary.astype(bool)|eyes,max(2,f.width*.025))
    transition=np.minimum(distance,interior)
    alpha=(transition*transition*(3-2*transition)*mask).astype(np.float32)
    f._skin_blend_cache=(key,alpha)
    return alpha

def visible_skin_at_fringe(session,fi,labels,skin):
    """Recover visible skin mislabelled by a coarse hair boundary, never hair.

    Restrict to the face oval, a short distance from confirmed skin, and a
    locally matching LAB color. Dark strands remain vetoed, not inpainted.
    Only the continuous beauty region consumes this proposal; detection and
    user-created part selections retain the original model masks.
    """
    f=session.faces[fi];a,b,c,d=f.box;p=f.points-[a,b]
    oval=np.zeros(labels.shape,np.uint8);cv2.fillPoly(oval,[p[OVAL].astype(np.int32)],1)
    near=cv2.distanceTransform((~skin).astype(np.uint8),cv2.DIST_L2,5)<=max(2,f.width*.035)
    candidate=(labels==17)&near&(oval>0)&~below_jaw(f,f.box)
    if not candidate.any():return np.zeros(labels.shape,bool)
    src=session.original[b:d,a:c].astype(np.float32)/255
    lab=cv2.cvtColor(src,cv2.COLOR_RGB2LAB);weight=skin.astype(np.float32)
    sigma=max(2,f.width*.025);denominator=cv2.GaussianBlur(weight,(0,0),sigma)
    reference=cv2.GaussianBlur(lab*weight[:,:,None],(0,0),sigma)/np.maximum(denominator[:,:,None],1e-5)
    delta=lab-reference
    # Reject dark or chromatically different pixels even if a strand is thin.
    return candidate&(denominator>.12)&(delta[:,:,0]>-12)&(delta[:,:,0]<18)&(np.linalg.norm(delta[:,:,1:],axis=2)<8)

def face_beauty_mask(session,fi):
    """Continuous facial treatment, independent of blemish/part selections.

    Fill enclosed feature gaps in the confirmed face, include brows/lips/nose
    and eyelid skin, and retain only the eyeball opening as an internal veto.
    Hair, accessories, exterior background and other people remain excluded.
    This changes neither detection safety nor user-created part layers.
    """
    ensure_face_parts(session,fi)
    f=session.faces[fi];labels=session.part_labels[fi];parts=session.part_regions[fi]
    manual=getattr(session,'beauty_include',{}).get(fi,np.zeros(labels.shape,bool))
    excluded=getattr(session,'beauty_exclude',{}).get(fi,np.zeros(labels.shape,bool))
    key=(22,hashlib.blake2b(labels.tobytes()+parts['eyes'].tobytes()+parts['skin'].tobytes()+manual.tobytes()+excluded.tobytes()+f.points[FEATURES[0]+FEATURES[1]].tobytes(),digest_size=12).hexdigest())
    if getattr(f,'beauty_mask_key',None)==key:return f.beauty_mask
    recovered=visible_skin_at_fringe(session,fi,labels,parts['skin'])
    material=face_surface(f,labels)|recovered
    n,cc=cv2.connectedComponents(material.astype(np.uint8),8)
    touched=np.unique(cc[parts['skin']&material]);touched=touched[touched!=0]
    connected=material&np.isin(cc,touched)
    outside=np.pad(connected.astype(np.uint8),1)
    cv2.floodFill(outside,None,(0,0),2)
    continuous=(outside!=2)[1:-1,1:-1]
    # An enclosed gap may be a real fringe, spectacle or earring. Do not
    # invent skin there. Eye protection uses the complete eyelid opening,
    # including shaded sclera, rather than only bright white pixels.
    eyes=parts['eyes'].astype(np.uint8).copy();a,b,_,_=f.box;p=f.points-[a,b]
    # Feature IDs are not guaranteed to be a simple polygon ordering. Use
    # the eye contour's hull to prevent a diagonal unprotected strip inside
    # the eyeball. This does not expand a general repair feature guard.
    for ids in FEATURES[:2]:cv2.fillConvexPoly(eyes,cv2.convexHull(p[ids].astype(np.int32)),1)
    f.beauty_eye_mask=eyes.astype(bool)
    continuous&=(~np.isin(labels,[6,9,17,18])|recovered)&~f.beauty_eye_mask
    continuous|=manual&~f.beauty_eye_mask
    continuous&=~excluded
    f.beauty_recovered_skin=recovered
    f.beauty_mask=soft_edge(continuous,max(1,f.width*.003))
    f.beauty_mask_key=key
    f.__dict__.pop('_skin_blend_cache',None)
    return f.beauty_mask

def load_beauty_includes(session,extensions):
    """Attach recipe masks to the render session without changing AI selections."""
    session.beauty_include={};session.body_beauty_include={};session.beauty_exclude={};session.body_beauty_exclude={}
    for fi,f in enumerate(session.faces):
        mask=extensions.get('masks',{}).get('beauty-include-'+str(fi))
        if mask is not None:
            a,b,c,d=f.box;session.beauty_include[fi]=mask[b:d,a:c]
        body=extensions.get('masks',{}).get('body-beauty-include-'+str(fi))
        if body is not None:session.body_beauty_include[fi]=body
        excluded=extensions.get('masks',{}).get('beauty-exclude-'+str(fi))
        if excluded is not None:
            a,b,c,d=f.box;session.beauty_exclude[fi]=excluded[b:d,a:c]
        excluded=extensions.get('masks',{}).get('body-beauty-exclude-'+str(fi))
        if excluded is not None:session.body_beauty_exclude[fi]=excluded

def nostril_mask(rgb,f):
    a,b,c,d=f.box;p=f.points-[a,b];region=np.zeros(f.mask.shape,np.uint8)
    cv2.fillConvexPoly(region,cv2.convexHull(p[FEATURES[-1]]),1)
    # Select deep cavities only near the two landmark nostril rims. Do not
    # exclude the entire lower nose or use general dark spots as nostrils.
    light=cv2.cvtColor(rgb[b:d,a:c],cv2.COLOR_RGB2LAB)[:,:,0].astype(np.float32)
    values=light[region>0]
    result=np.zeros_like(region)
    if values.size<4:return result
    dark=((light<np.median(values)*.57)&(region>0)).astype(np.uint8)
    n,labels,stats,centres=cv2.connectedComponentsWithStats(dark,8)
    rims=[p[[98,97]].mean(0),p[[327,326]].mean(0)]
    for i in range(1,n):
        if min(np.linalg.norm(centres[i]-r) for r in rims)<f.width*.085:result[labels==i]=1
    r=max(1,round(f.width*.003))
    return cv2.dilate(result,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*r+1,2*r+1)))

def face_parts(rgb,f,context,labels):
    x,y,z,t=context;a,b,c,d=f.box
    lab=cv2.resize(labels,(z-x,t-y),interpolation=cv2.INTER_NEAREST)[b-y:d-y,a-x:c-x]
    candidate=f.mask>0
    # Connect semantic cheek pixels to the mesh seed, rather than cutting the
    # outer cheek at the mesh's approximate contour. The jaw separates neck.
    semantic=np.isin(lab,[1,10]);n,cc=cv2.connectedComponents(semantic.astype(np.uint8),8)
    touched=np.unique(cc[candidate&semantic]);touched=touched[touched!=0]
    skin=semantic&face_surface(f,lab)
    # Mesh geometry is a broad candidate, never the final skin edge.
    nostrils=nostril_mask(rgb,f);f.protected[nostrils>0]=255
    # Detection needs a generous feature guard, but a skin selection must not
    # inherit that dilation: it left untreated rings beside brows and lips.
    skin&=nostrils==0
    hair=lab==17
    parts={'skin':skin,'lips':np.isin(lab,[12,13]),'eyes':np.isin(lab,[4,5]),'brows':np.isin(lab,[2,3])}
    eye=np.zeros(lab.shape,np.uint8);iris=np.zeros_like(eye)
    p=f.points-[a,b]
    for ids,ring in ((FEATURES[0],[474,475,476,477]),(FEATURES[1],[469,470,471,472])):
        cv2.fillPoly(eye,[p[ids].astype(np.int32)],1)
        if len(p)>max(ring):cv2.fillConvexPoly(iris,cv2.convexHull(p[ring].astype(np.int32)),1)
    # The face parser often marks only the dark centre as "eye". Refined
    # eyelid landmarks retain the surrounding sclera; semantic hair/brows veto.
    eye=eye.astype(bool)&~np.isin(lab,[17,2,3]);parts['iris']=iris.astype(bool)&eye
    patch=rgb[b:d,a:c];labcolor=cv2.cvtColor(patch,cv2.COLOR_RGB2LAB)
    # Low-chroma, bright pixels inside the eyelids/inner mouth. Dark lashes,
    # pupil and mouth cavity never become white-feature selections.
    chroma=np.linalg.norm(labcolor[:,:,1:].astype(np.float32)-128,axis=2)
    parts['sclera']=eye&~parts['iris']&(labcolor[:,:,0]>60)&(chroma<48)
    parts['eyes']=eye
    inner=np.zeros_like(iris);inner_ids=[78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95]
    cv2.fillPoly(inner,[p[inner_ids].astype(np.int32)],1)
    mouth=(lab==11)&(inner>0);light=labcolor[:,:,0]
    # Separate the mouth's dark cavity and light tooth group instead of selecting
    # only a fixed bright percentile (which cuts off shaded teeth).
    threshold=max(95,float(cv2.threshold(light[mouth].reshape(-1,1),0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[0])) if mouth.any() else 255
    parts['teeth']=mouth&(light>=threshold)&(chroma<32)
    skin&=~eye
    f.mask=soft_edge(skin,max(2,f.width*.008))
    f.parts_revision=19
    return parts,hair,nostrils,lab

def face_surface(f,labels):
    """One semantic boundary shared by facial treatment and body exclusion.

    Landmarks seed the connected face and bound distant skin, but never slice
    confirmed cheek/chin pixels along the approximate jaw polyline. Parser
    neck/ear/hair labels retain their distinct ownership.
    """
    a,b,c,d=f.box;oval=np.zeros(labels.shape,np.uint8)
    cv2.fillPoly(oval,[(f.points[OVAL]-[a,b]).astype(np.int32)],1)
    distance=cv2.distanceTransform(1-oval,cv2.DIST_L2,5)
    near=distance<=max(3,f.width*.18)
    material=np.isin(labels,[1,2,3,4,5,10,11,12,13])&near
    # A few neck-labelled pixels inside the actual oval must not punch a hole.
    material|=(labels==14)&(oval>0)
    _,components=cv2.connectedComponents(material.astype(np.uint8),8)
    touched=np.unique(components[(oval>0)&material]);touched=touched[touched!=0]
    return material&np.isin(components,touched)

def below_jaw(f,box):
    """Landmark jaw boundary in face-axis coordinates (works on tilted faces)."""
    a,b,c,d=box;p=f.points.astype(np.float32)
    down=p[152]-p[10];down/=max(1,np.linalg.norm(down));right=np.array([down[1],-down[0]])
    ids=[234,93,132,58,172,136,150,149,176,148,152,377,400,378,379,365,397,288,361,323,454]
    q=p[ids]-p[152];u=q@right;v=q@down;order=np.argsort(u)
    yy,xx=np.mgrid[b:d,a:c];dx=xx-p[152,0];dy=yy-p[152,1]
    ux=dx*right[0]+dy*right[1];vy=dx*down[0]+dy*down[1]
    boundary=np.interp(ux,u[order],v[order])
    # Outside the measured jaw span, a constant endpoint is not a boundary.
    return (vy>boundary)&(ux>=u.min())&(ux<=u.max())

def face_context(session,fi):
    if not hasattr(session,'parse_contexts'):session.parse_contexts={}
    if fi not in session.parse_contexts:
        from ai_engine import parse_skin,square_box
        f=session.faces[fi];box=square_box(f.box,session.original.shape)
        _,_,labels=parse_skin(session.original,box,session.parser_model,points=f.points)
        session.parse_contexts[fi]=(box,labels)
    if not hasattr(session,'refined_contexts'):session.refined_contexts={}
    if fi in session.refined_contexts:box,labels=session.refined_contexts[fi]
    else:
        box,labels=session.parse_contexts[fi];a,b,c,d=box
        full=cv2.resize(labels,(c-a,d-b),interpolation=cv2.INTER_NEAREST)
        f=session.faces[fi]
        if np.count_nonzero(np.isin(full,[7,8]))<max(8,f.width*f.width*.003):
            # A tighter, independently trained parsing model recovers small ears
            # which the wider head context labelled as hair. Only ear labels
            # near the lateral jaw are merged, never generic skin/background.
            from ai_engine import parse_skin,square_box
            tight=square_box(f.box,session.original.shape,1.0);x,y,z,t=tight
            _,_,second=parse_skin(session.original,tight,points=f.points)
            second=cv2.resize(second,(z-x,t-y),interpolation=cv2.INTER_NEAREST)
            p=f.points.astype(np.float32);down=p[152]-p[10];down/=max(1,np.linalg.norm(down));right=np.array([down[1],-down[0]])
            yy,xx=np.mgrid[y:t,x:z];dx=xx-p[152,0];dy=yy-p[152,1]
            u=dx*right[0]+dy*right[1];v=dx*down[0]+dy*down[1]
            ear=np.isin(second,[7,8])&(np.abs(u)>f.width*.32)&(np.abs(u)<f.width*.9)&(v>-f.width*.9)&(v<f.width*.35)
            x0,y0,x1,y1=max(a,x),max(b,y),min(c,z),min(d,t)
            if x0<x1 and y0<y1:
                use=ear[y0-y:y1-y,x0-x:x1-x];target=full[y0-b:y1-b,x0-a:x1-a]
                target[use]=second[y0-y:y1-y,x0-x:x1-x][use]
        labels=cv2.resize(full,(min(1024,c-a),min(1024,d-b)),interpolation=cv2.INTER_NEAREST)
        session.refined_contexts[fi]=(box,labels)
    a,b,c,d=box
    return box,cv2.resize(labels,(c-a,d-b),interpolation=cv2.INTER_NEAREST)

def ensure_face_parts(session,fi):
    if getattr(session.faces[fi],'parts_revision',None)==19 and all(k in session.part_regions[fi] for k in ('brows','iris','sclera','teeth')):return
    box,labels=face_context(session,fi);f=session.faces[fi]
    parts,hair,nostrils,lab=face_parts(session.original,f,box,labels)
    session.part_regions[fi]=parts;session.part_labels[fi]=lab
    session.semantic_skin[fi]=parts['skin'];session.hair[fi]=hair;session.nostrils[fi]=nostrils
    session.parts_revision=19

def facial_exclusion(f,labels):
    # Ears (7/8) and neck (14) belong to body. Semantic skin below the jaw
    # also belongs to body; eyes/brows/nose/mouth remain excluded.
    return np.isin(labels,[2,3,4,5,6,9,10,11,12,13])|face_surface(f,labels)

def semantic_parts(rgb):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import ImageSegmenter,ImageSegmenterOptions,RunningMode
    path=ROOT/'models/selfie_multiclass_256x256.tflite'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=BODY_HASH:raise ValueError('身体分割模型校验失败。')
    h,w=rgb.shape[:2];ratio=min(1,1024/max(h,w));small=cv2.resize(rgb,(round(w*ratio),round(h*ratio))) if ratio<1 else rgb
    ih,iw=small.shape[:2];padding=(-iw)%4
    if padding:small=cv2.copyMakeBorder(small,0,0,0,padding,cv2.BORDER_REPLICATE)
    options=ImageSegmenterOptions(base_options=BaseOptions(model_asset_buffer=path.read_bytes()),running_mode=RunningMode.IMAGE,output_category_mask=True,output_confidence_masks=True)
    with ImageSegmenter.create_from_options(options) as segmenter:
        result=segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(small)))
        classes=np.squeeze(result.category_mask.numpy_view()).copy()[:ih,:iw]
        confidence=np.zeros((ih,iw),np.float32)
        for i,m in enumerate(result.confidence_masks):
            if not m.is_contiguous():raise RuntimeError('部位分割缓冲区不兼容，已安全停止。')
            values=np.squeeze(m.numpy_view())[:ih,:iw];confidence[classes==i]=values[classes==i]
    from ai_runtime import RUNTIME
    RUNTIME.mark('身体部位分割','CPU')
    classes[confidence<.6]=255
    return cv2.resize(classes,(w,h),interpolation=cv2.INTER_NEAREST)

def body_skin(rgb):return semantic_parts(rgb)==2

def part_mask(session,fi,part):
    if part in ('body','person','hair','clothes'):
        if not 0<=fi<len(session.faces):return np.zeros(session.original.shape[:2],bool)
        from person_masks import ensure_body_owners
        ensure_body_owners(session)
        if part=='body':return session.body_owner==fi+1
        own=session.person_owner==fi+1
        if part=='person':
            # The confirmed head parser supplements gaps in a coarse pose
            # silhouette. No competing person's pixels may be claimed.
            a,b,c,d=session.faces[fi].box
            head=(session.part_labels[fi]>0)&(session.part_labels[fi]!=18)
            eligible=np.isin(session.person_owner[b:d,a:c],[0,fi+1])
            own[b:d,a:c]|=head&eligible
            return own
        return own&(session.person_semantics=={'hair':1,'clothes':4}[part])
    out=np.zeros(session.original.shape[:2],bool)
    if fi<len(session.faces):
        ensure_face_parts(session,fi)
        a,b,c,d=session.faces[fi].box;out[b:d,a:c]=session.part_regions[fi][part]
    return out

def validate_layers(layers,shape):
    if not isinstance(layers,list) or len(layers)>MAX_LAYERS:raise ValueError(f'单图最多{MAX_LAYERS}个部位蒙版。')
    for layer in layers:
        from local_develop import checked
        checked(layer)
        if 'id' in layer and (not isinstance(layer['id'],str) or len(layer['id'])>100):raise ValueError('蒙版标识无效。')
        if not isinstance(layer.get('name'),str) or len(layer['name'])>100:raise ValueError('蒙版名称无效。')
        if np.asarray(layer['mask']).shape!=tuple(shape):raise ValueError('部位蒙版尺寸无效。')
        if layer.get('mask_alpha') is not None:
            ah,aw=layer['mask_alpha'].shape
            if abs(aw/ah-shape[1]/shape[0])>max(.01,2/ah):raise ValueError('AI 柔边蒙版比例与照片不一致。')
        if type(layer.get('enabled',True)) is not bool:raise ValueError('蒙版开关无效。')
        if 'feature_key' in layer:
            from feature_catalog import TYPE_LABELS
            if layer['feature_key'] not in TYPE_LABELS or type(layer.get('person_index')) is not int or not 0<=layer['person_index']<20:raise ValueError('细节蒙版人物或类型无效。')
        for k,(lo,hi) in LOCAL_RANGES.items():
            v=layer.get('parameters',{}).get(k,0)
            if type(v) not in (int,float) or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('部位蒙版参数无效。')
        layer['parameters']=dict(LOCAL_DEFAULTS,**layer.get('parameters',{}))
    return layers

def packed_layers(layers):
    return [dict(name=l['name'],enabled=l.get('enabled',True),parameters=dict(l['parameters']),mask=np.packbits(l['mask']),**({'mask_alpha':l['mask_alpha'].copy()} if 'mask_alpha' in l else {}),**({'id':l['id']} if 'id' in l else {}),**({k:l[k] for k in ('feature_key','person_index')} if 'feature_key' in l else {}),**{k:copy.deepcopy(l[k]) for k in LAYER_FIELDS if k in l}) for l in layers]
def unpacked_layers(layers,shape):
    # Restored editable recipes/components must not alias undo snapshots or
    # cached projects: appending a brush stroke otherwise mutates history.
    return [dict(copy.deepcopy(l),mask=np.unpackbits(l['mask'],count=int(np.prod(shape))).reshape(shape).astype(bool)) for l in layers]
def equal_layers(a,b):
    return len(a)==len(b) and all(x['name']==y['name'] and x['enabled']==y['enabled'] and x['parameters']==y['parameters'] and x.get('id')==y.get('id') and x.get('feature_key')==y.get('feature_key') and x.get('person_index')==y.get('person_index') and all(x.get(k)==y.get(k) for k in LAYER_FIELDS) and np.array_equal(x.get('mask_alpha'),y.get('mask_alpha')) and np.array_equal(x['mask'],y['mask']) for x,y in zip(a,b))

def apply_layers(rgb,layers):
    out=rgb
    for layer in layers:
        if layer.get('color_process',1)==2:continue
        values=layer['parameters'];mask=layer['mask']
        if not layer.get('enabled',True) or not any(values.get(k,0) for k in ('exposure','temperature','tint','saturation','texture','smooth')):continue
        from smart_selection import refine
        mask=refine(mask,values.get('expand',0))
        compound=bool(layer.get('components') or layer.get('gradient') or layer.get('range',{}).get('kind','none')!='none')
        if compound:
            from local_develop import alpha as component_alpha
            weights=component_alpha(layer,rgb,prepared=mask)
            mask=weights>0
        if not mask.any():continue
        points=cv2.findNonZero(mask.astype(np.uint8));a,b,w,h=cv2.boundingRect(points)
        src=out[b:b+h,a:a+w].astype(np.float32);alpha=soft_edge(mask[b:b+h,a:a+w],values.get('feather',2))
        if compound:alpha=weights[b:b+h,a:a+w]
        elif values.get('opacity',100)!=100:alpha*=values['opacity']/100
        edited=src.copy();low=None
        if values['smooth'] or values['texture']:
            low=cv2.GaussianBlur(src,(0,0),1.2)
            gain=1+values['texture']/100*.45-values['smooth']/100*.6
            edited=low+(src-low)*gain
        if values['exposure']:edited*=2**values['exposure']
        if any(values[k] for k in ('temperature','tint','saturation')):
            lab=cv2.cvtColor(np.clip(edited/255,0,1).astype(np.float32),cv2.COLOR_RGB2LAB)
            lab[:,:,1]+=values['tint']*.035;lab[:,:,2]+=values['temperature']*.06
            lab[:,:,1:]*=1+values['saturation']/100*.6
            edited=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
        if out is rgb:out=rgb.copy()
        target=out[b:b+h,a:a+w];selected=alpha>0
        target[selected]=np.clip((src+(edited-src)*alpha[:,:,None])[selected],0,255)
    return out
