"""Single-person VIDEO pose-driven body slimming and leg extension.

Continuous inverse maps move clothes with the person. No synthesized vacancy
repair, no previous RGB overlay. Background lines are optional fixed anchors;
unreliable/cropped/bent poses skip the affected control instead of guessing.
"""
import hashlib
from collections import Counter
import cv2,numpy as np
from core import ROOT
from person_masks import POSE_HASH,match_faces
from face_reshape import _fit,_evaluate
from liquify import cell_jacobian

BODY_KEYS=('body_slim','waist_slim','leg_slim','leg_length')

def _sample(mask,points,shape):
    h,w=shape;mh,mw=mask.shape
    q=np.asarray(points,np.float32)*[mw/w,mh/h]
    return cv2.remap(mask,q[:,0].astype(np.float32)[:,None],q[:,1].astype(np.float32)[:,None],cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)[:,0]

def _boundary(mask,center,side,radius,shape):
    t=np.linspace(-radius,radius,max(33,round(radius*2)+1));points=center+t[:,None]*side
    values=_sample(mask,points,shape);inside=values>.55;middle=len(t)//2
    if not inside[middle]:return None
    left=right=middle
    while left>0 and inside[left-1]:left-=1
    while right+1<len(t) and inside[right+1]:right+=1
    if right-left<8 or left==0 or right==len(t)-1:return None
    return np.array([points[left],points[right]])

def body_controls(p,mask,shape,values):
    """Build current-frame source/target pairs, with explicit feature gates."""
    h,w=shape;xy=p[:,:2];confidence=np.min(p[:,2:],axis=1);source=[];target=[];notes=[];features=[]
    def valid(ids,threshold=.65):
        q=xy[ids];return bool(np.all(confidence[ids]>=threshold) and np.all(q[:,0]>=1) and np.all(q[:,0]<w-1) and np.all(q[:,1]>=1) and np.all(q[:,1]<h-1))
    if not valid([11,12,23,24]):return None,'肩胯关键点不足',[]
    shoulders=xy[[11,12]].mean(0);hips=xy[[23,24]].mean(0)
    down=hips-shoulders;torso=float(np.linalg.norm(down));sw=float(np.linalg.norm(xy[11]-xy[12]))
    if torso<24 or sw<20:return None,'人物身体太小',[]
    down/=torso;side=np.array([down[1],-down[0]])
    if down[1]<.75:return None,'姿态不适合当前直立美型',[]
    def put(points,changes):
        for point,delta in zip(points,changes):source.append(point);target.append(point+delta)
    # Keep shoulder line, pelvis centre and arms stable unless explicitly moved.
    fixed=list(xy[[11,12]])+[shoulders,hips]
    for index in (13,14,15,16):
        if valid([index]):fixed.append(xy[index])
    if values['body_slim'] or values['waist_slim']:
        for t in (.20,.40,.60,.78,.93):
            center=shoulders+(hips-shoulders)*t
            border=_boundary(mask,center,side,sw*1.10,shape)
            if border is None:continue
            amount=values['body_slim']/100*.16+values['waist_slim']/100*.20*np.exp(-((t-.63)/.22)**2)
            relative=(border-center)@side;put(border,-relative[:,None]*side*amount)
        if source:features.append('瘦身/瘦腰')
        else:notes.append('躯干边缘不可靠，未瘦身/瘦腰')
    legs_valid=valid([23,24,25,26,27,28],.72)
    if legs_valid:
        lengths=[np.linalg.norm(xy[k]-xy[a]) for a,k in ((23,25),(24,26))]
        lower=[np.linalg.norm(xy[k]-xy[a]) for a,k in ((25,27),(26,28))]
        straight=all(np.dot((xy[k]-xy[a])/max(1,np.linalg.norm(xy[k]-xy[a])),down)>.82 for a,k in ((23,25),(24,26),(25,27),(26,28)))
        separated=np.linalg.norm(xy[25]-xy[26])>sw*.18
        if not straight or not separated:legs_valid=False;notes.append('腿部弯曲/交叉，未瘦腿或拉腿')
    else:notes.append('膝踝被遮挡或裁切，未瘦腿或拉腿')
    leg_amount=values['leg_slim']/100*.16+values['body_slim']/100*.064
    if legs_valid and leg_amount:
        before=len(source)
        for hi,ki,ai,ohi,oki,oai in ((23,25,27,24,26,28),(24,26,28,23,25,27)):
            for a,b,oa,ob in ((hi,ki,ohi,oki),(ki,ai,oki,oai)):
                segment=xy[b]-xy[a];direction=segment/max(1,np.linalg.norm(segment));normal=np.array([direction[1],-direction[0]])
                for t in (.35,.60,.82):
                    center=xy[a]+segment*t;other=xy[oa]+(xy[ob]-xy[oa])*t
                    radius=min(sw*.55,np.linalg.norm(other-center)*.42)
                    if radius<7:continue
                    border=_boundary(mask,center,normal,radius,shape)
                    if border is None:continue
                    relative=(border-center)@normal;put(border,-relative[:,None]*normal*leg_amount)
        if len(source)>before:features.append('瘦腿')
        else:notes.append('两腿边缘不能可靠分离，未瘦腿')
    extension=0.
    if values['leg_length'] and legs_valid:
        if not valid([27,28,29,30,31,32],.72):notes.append('脚部不完整，未拉腿')
        else:
            feet=xy[27:33];leg_length=float(np.mean((xy[[27,28]]-xy[[23,24]])@down))
            margin=min((h-2-feet[:,1].max())/max(down[1],.1),
                       (w-2-feet[:,0].max())/down[0] if down[0]>.01 else (feet[:,0].min()-1)/(-down[0]) if down[0]<-.01 else h)
            desired=leg_length*values['leg_length']/100*.12
            extension=max(0,min(desired,margin*.45))
            if extension<1:notes.append('脚下取景余量不足，未拉腿')
            else:
                # Pelvis fixed; knees move proportionally; shoes move as a unit.
                put(xy[[25,26]],np.tile(down*extension*.48,(2,1)))
                put(feet,np.tile(down*extension,(6,1)));features.append('拉腿')
                if extension<desired*.95:notes.append('拉腿已受脚下余量限制')
    if not source:return None,'；'.join(notes) or '未找到可移动身体边缘',[]
    source=np.asarray(source,float);target=np.asarray(target,float)
    # Preserve the torso and limb axes while their widths change.
    for a,b in ((11,23),(12,24),(23,25),(24,26),(25,27),(26,28)):
        if valid([a,b]):
            for t in (.3,.6):
                point=xy[a]+(xy[b]-xy[a])*t
                if extension and a in (23,24,25,26):
                    ratio=((point-hips)@down)/max(1,float(np.mean((xy[[27,28]]-xy[[23,24]])@down)))
                    source=np.vstack([source,point]);target=np.vstack([target,point+down*extension*np.clip(ratio,0,1)])
                else:fixed.append(point)
    return {'source':source,'target':target,'fixed':np.asarray(fixed),'shoulders':shoulders,'hips':hips,
            'down':down,'width':sw,'torso':torso,'extension':extension,'notes':notes},None,features

def build_body_field(rgb,mask,control,face=None,protect_lines=True):
    h,w=rgb.shape[:2];sw=control['width'];source=control['source'];target=control['target']
    lo=np.floor(np.minimum(source,target).min(0)-sw*.85).astype(int)
    hi=np.ceil(np.maximum(source,target).max(0)+sw*.85).astype(int)
    a,b=np.maximum(lo,[0,0]);c,d=np.minimum(hi,[w,h]);rw,rh=c-a,d-b
    if min(rw,rh)<16:return None
    origin=np.array([a,b]);scale=float(max(rw,rh));fixed=list(control['fixed'])
    for t in np.linspace(0,1,11):fixed.extend([[a+t*(rw-1),b],[a+t*(rw-1),d-1],[a,b+t*(rh-1)],[c-1,b+t*(rh-1)]])
    if face is not None:fixed.extend(face.points[::12])
    anchors=0
    if protect_lines:
        roi=rgb[b:d,a:c];ratio=min(1,640/max(rw,rh));small=cv2.resize(roi,(round(rw*ratio),round(rh*ratio)))
        edges=cv2.Canny(cv2.cvtColor(np.clip(small,0,255).astype(np.uint8),cv2.COLOR_RGB2GRAY),70,160)
        lines=cv2.HoughLinesP(edges,1,np.pi/180,40,minLineLength=max(30,round(sw*.5*ratio)),maxLineGap=8)
        for line in [] if lines is None else lines[:24]:
            x,y,z,t=np.asarray(line).reshape(-1)[:4];points=np.linspace([x/ratio+a,y/ratio+b],[z/ratio+a,t/ratio+b],6)
            # Never turn clothing seams into background constraints.
            for point,prob in zip(points,_sample(mask,points,(h,w))):
                if prob<.12:fixed.append(point);anchors+=1
    fixed=np.unique(np.round(np.asarray(fixed,float),2),axis=0)
    inside=(fixed[:,0]>=a)&(fixed[:,0]<c)&(fixed[:,1]>=b)&(fixed[:,1]<d);fixed=fixed[inside]
    gw=max(48,round(rw/scale*193));gh=max(48,round(rh/scale*193))
    xx,yy=np.meshgrid(np.linspace(0,rw-1,gw),np.linspace(0,rh-1,gh));query=np.column_stack([xx.ravel(),yy.ravel()])/scale
    edge=np.minimum.reduce([xx,yy,rw-1-xx,rh-1-yy]);fade=np.clip(edge/max(5,sw*.14),0,1);fade=fade**3*(10-15*fade+6*fade*fade)
    global_points=np.column_stack([xx.ravel()+a,yy.ravel()+b])
    # Everything above the shoulder line (head/face) is fixed; a broad neck
    # transition avoids applying torso width corrections to facial geometry.
    level=((global_points-control['shoulders'])@control['down']).reshape(gh,gw)
    neck=np.clip(level/max(6,control['torso']*.16),0,1);neck=neck*neck*(3-2*neck);fade*=neck
    if face is not None:
        freeze=np.zeros((gh,gw),np.uint8)
        points=(face.points-origin)*[(gw-1)/(rw-1),(gh-1)/(rh-1)]
        cv2.fillConvexPoly(freeze,cv2.convexHull(np.rint(points).astype(np.int32)),1)
        if freeze.any():
            dist=cv2.distanceTransform(1-freeze,cv2.DIST_L2,5)*scale/193
            fade*=np.clip(dist/max(5,face.width*.10),0,1)
    for attempt in range(9):
        strength=.8**attempt;current=source+(target-source)*strength
        coordinates=(np.vstack([current,fixed])-origin)/scale;delta=np.vstack([source-current,np.zeros_like(fixed)])/scale
        _,unique=np.unique(np.round(coordinates,7),axis=0,return_index=True);coordinates=coordinates[unique];delta=delta[unique]
        try:weights=_fit(coordinates,delta)
        except np.linalg.LinAlgError:continue
        field=np.empty((len(query),2),np.float32)
        for start in range(0,len(query),4096):field[start:start+4096]=_evaluate(query[start:start+4096],coordinates,weights)*scale
        field=(field.reshape(gh,gw,2)*fade[:,:,None]).astype(np.float32)
        minimum=float(cell_jacobian(field,(rw-1)/(gw-1),(rh-1)/(gh-1)).min())
        if np.isfinite(field).all() and minimum>.50:break
    else:return None
    return {'roi':tuple(map(int,[a,b,c,d])),'grid':field,'jacobian_min':minimum,'effective_scale':strength,
            'line_anchors':anchors,'extension_pixels':control['extension']*strength}

def apply_body_field(rgb,field):
    a,b,c,d=field['roi'];gh,gw=field['grid'].shape[:2]
    yy,xx=np.indices((d-b,c-a),dtype=np.float32);gx=xx*(gw-1)/(c-a-1);gy=yy*(gh-1)/(d-b-1)
    displacement=cv2.remap(field['grid'],gx,gy,cv2.INTER_LINEAR)
    mx=(xx+a+displacement[:,:,0]).astype(np.float32);my=(yy+b+displacement[:,:,1]).astype(np.float32)
    out=rgb.copy();out[b:d,a:c]=cv2.remap(rgb,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
    return out

class BodyRenderStats:
    """Geometry-only renderer state: no detector or model initialization."""
    def __init__(self):
        self.frames=0;self.pose_frames=0;self.reduced_frames=0;self.minimum_jacobian=1.;self.features=Counter();self.skipped=Counter();self.last_applied=False;self.last_field=None
    def close(self):self.last_field=None
    def report(self):
        return {'body_frames':self.frames,'pose_frames':self.pose_frames,'body_reduced_frames':self.reduced_frames,'body_min_jacobian':self.minimum_jacobian,'body_feature_frames':dict(self.features),'body_skip_reasons':dict(self.skipped)}

class LiveBody:
    def __init__(self,recipe):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import PoseLandmarker,PoseLandmarkerOptions,RunningMode
        data=(ROOT/'models/pose_landmarker_full.task').read_bytes()
        if hashlib.sha256(data).hexdigest()!=POSE_HASH:raise ValueError('人体定位模型校验失败。')
        self.mp=mp;self.recipe=recipe
        self.detector=PoseLandmarker.create_from_options(PoseLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=data),
            running_mode=RunningMode.VIDEO,num_poses=2,min_pose_detection_confidence=.55,min_pose_presence_confidence=.65,
            min_tracking_confidence=.65,output_segmentation_masks=True))
        self.canonical=None;self.previous_center=None;self.previous_scale=None;self.confidence=None;self.detected_stamp=None;self.detected=None
        self.frames=0;self.pose_frames=0;self.reduced_frames=0;self.minimum_jacobian=1.;self.features=Counter();self.skipped=Counter();self.last_applied=False;self.last_field=None
    def close(self):self.detector.close();self.clear()
    def clear(self):self.canonical=None;self.previous_center=None;self.previous_scale=None;self.confidence=None;self.last_field=None
    def locate(self,source,timestamp):
        if self.detected_stamp==int(timestamp):return self.detected
        h,w=source.shape[:2];ratio=min(1,960/max(h,w));iw,ih=round(w*ratio),round(h*ratio)
        image=cv2.resize(source,(iw,ih)) if ratio<1 else source
        padding=(-iw)%4
        if padding:image=cv2.copyMakeBorder(image,0,0,0,padding,cv2.BORDER_REPLICATE)
        result=self.detector.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=np.ascontiguousarray(image)),int(timestamp))
        self.detected_stamp=int(timestamp);self.detected=None
        if len(result.pose_landmarks)==1 and result.segmentation_masks:
            p=np.array([[x.x*(iw+padding)*w/iw,x.y*h,x.visibility,x.presence] for x in result.pose_landmarks[0]],float)
            m=result.segmentation_masks[0]
            if not m.is_contiguous():raise RuntimeError('人体范围缓冲区不兼容，已停止处理。')
            mask=np.squeeze(m.numpy_view()).copy().astype(np.float32)[:ih,:iw]
            self.detected=p,mask
        return self.detected
    def head_crop(self,source,timestamp):
        found=self.locate(source,timestamp)
        if found is None:return None
        p,_=found;h,w=source.shape[:2];good=np.min(p[:11,2:],axis=1)>.72
        if good.sum()<7:return None
        xy=p[:11,:2][good];center=(xy.min(0)+xy.max(0))/2
        width=max(float(np.linalg.norm(p[11,:2]-p[12,:2]))*.65,float(np.ptp(xy[:,0]))*1.9,float(np.ptp(xy[:,1]))*2.4,48.)
        if width>min(h,w)*.45 or np.any(center<[0,0]) or np.any(center>[w,h]):return None
        a,b=np.maximum(np.floor(center-width*.5).astype(int),[0,0]);c,d=np.minimum(np.ceil(center+width*.5).astype(int),[w,h])
        if min(c-a,d-b)<40:return None
        return tuple(map(int,(a,b,c,d)))
    def process(self,source,rgb,timestamp,face=None,reset=False):
        self.last_applied=False;h,w=source.shape[:2];found=self.locate(source,timestamp)
        if found is None:self.skipped['多人或未找到完整身体']+=1;self.clear();return rgb
        p,mask=found;p=p.copy()
        if face is not None and not match_faces([face],[p])[0]:
            self.skipped['人脸与身体归属不确定']+=1;self.clear();return rgb
        self.pose_frames+=1
        shoulders=p[[11,12],:2].mean(0);hips=p[[23,24],:2].mean(0);axis=hips-shoulders;scale=max(1.,float(np.linalg.norm(axis)))
        down=axis/scale;side=np.array([down[1],-down[0]]);basis=np.column_stack([side,down]);canonical=(p[:,:2]-hips)@basis/scale
        jump=reset or self.previous_center is None or np.linalg.norm(hips-self.previous_center)>max(h,w)*.12 or not .6<scale/max(1,self.previous_scale)<1.6
        if not jump and self.canonical is not None:
            speed=np.linalg.norm(canonical-self.canonical,axis=1);weight=np.where(speed>.025,1.,.78)[:,None]
            canonical=self.canonical+(canonical-self.canonical)*weight
        self.canonical=canonical.copy();self.previous_center=hips.copy();self.previous_scale=scale
        p[:,:2]=canonical@basis.T*scale+hips
        confidence=np.min(p[:,2:],axis=1)
        if not jump and self.confidence is not None:confidence=np.minimum(confidence,self.confidence+(confidence-self.confidence)*.35)
        self.confidence=confidence.copy();p[:,2]=p[:,3]=confidence
        values={k:getattr(self.recipe,k) for k in BODY_KEYS};control,reason,features=body_controls(p,mask,(h,w),values)
        if control is None:self.skipped[reason]+=1;self.last_field=None;return rgb
        field=build_body_field(source,mask,control,face,self.recipe.body_protect_lines)
        if field is None:self.skipped['形变过密，已跳过身体美型']+=1;self.last_field=None;return rgb
        self.last_field=field;self.minimum_jacobian=min(self.minimum_jacobian,field['jacobian_min'])
        if field['effective_scale']<1:self.reduced_frames+=1
        for f in features:self.features[f]+=1
        for note in control['notes']:self.skipped[note]+=1
        self.frames+=1;self.last_applied=True
        return apply_body_field(rgb,field)
    def report(self):
        return {'body_frames':self.frames,'pose_frames':self.pose_frames,'body_reduced_frames':self.reduced_frames,
                'body_min_jacobian':self.minimum_jacobian,'body_feature_frames':dict(self.features),'body_skip_reasons':dict(self.skipped)}
