"""Offline pose-instance ownership, linked to the existing face IDs.

Semantic skin alone has no person identity. Keep ambiguous pixels unassigned;
never allocate a disconnected hand using distance to the nearest face.
"""
import hashlib
import cv2,numpy as np
from core import ROOT

POSE_HASH='5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1'

def pose_instances(rgb,confidence=.5):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import PoseLandmarker,PoseLandmarkerOptions,RunningMode
    data=(ROOT/'models/pose_landmarker_full.task').read_bytes()
    if hashlib.sha256(data).hexdigest()!=POSE_HASH:raise ValueError('人物轮廓模型校验失败。')
    h,w=rgb.shape[:2];scale=min(1,1280/max(h,w))
    image=cv2.resize(rgb,(round(w*scale),round(h*scale))) if scale<1 else rgb
    ih,iw=image.shape[:2]
    # MediaPipe 1.0.1 has a native float-mask crash for widths not divisible by
    # four (upstream issue #6331). Pad before inference, never read a strided
    # float mask, and map the padded coordinates back to the original image.
    padding=(-iw)%4
    if padding:image=cv2.copyMakeBorder(image,0,0,0,padding,cv2.BORDER_REPLICATE)
    options=PoseLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=data),
        running_mode=RunningMode.IMAGE,num_poses=8,min_pose_detection_confidence=confidence,
        min_pose_presence_confidence=confidence,output_segmentation_masks=True)
    with PoseLandmarker.create_from_options(options) as detector:
        result=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(image)))
        masks=[]
        for m in result.segmentation_masks or []:
            if not m.is_contiguous():raise RuntimeError('人物轮廓缓冲区不兼容，已安全停止生成。')
            masks.append(np.squeeze(m.numpy_view())[:ih,:iw].copy().astype(np.float32))
        points=[np.array([[p.x*(iw+padding)*w/iw,p.y*h,p.visibility,p.presence] for p in pose],np.float32) for pose in result.pose_landmarks]
    from ai_runtime import RUNTIME
    RUNTIME.mark('人物身体归属','CPU')
    return points,masks

def match_faces(faces,poses):
    """Mutual unique match of nose/eye/mouth geometry, not box proximity."""
    costs=np.full((len(faces),len(poses)),np.inf,np.float32)
    for fi,f in enumerate(faces):
        p=f.points.astype(np.float32)
        expected=np.array([p[1],(p[33]+p[133])/2,(p[263]+p[362])/2,p[61],p[291]])
        for pi,pose in enumerate(poses):
            actual=pose[[0,5,2,10,9]]
            reliable=(actual[:,2]>.5)&(actual[:,3]>.5)
            if reliable.sum()<3:continue
            costs[fi,pi]=np.median(np.linalg.norm(actual[reliable,:2]-expected[reliable],axis=1))/max(1,f.width)
    pairs={}
    for fi,row in enumerate(costs):
        if not len(row):continue
        pi=int(np.argmin(row));cost=float(row[pi])
        alternatives=np.delete(row,pi)
        rivals=np.delete(costs[:,pi],fi)
        if cost>.38 or (alternatives.size and alternatives.min()-cost<.15) or (rivals.size and rivals.min()-cost<.15):continue
        pairs[pi]=fi
    return pairs,costs

def recover_instances(rgb,faces):
    """Global pass plus confirmed single-person crops for missed instances.

    BlazePose's full-image detector can return just one subject despite a
    multi-pose request. A crop must still match that face's actual keypoints.
    Cropping does not itself assign pixels or bypass the ownership test.
    """
    poses,masks=pose_instances(rgb);pairs,_=match_faces(faces,poses)
    h,w=rgb.shape[:2];scale=min(1,1280/max(h,w));mh,mw=round(h*scale),round(w*scale)
    masks=[cv2.resize(m,(mw,mh)) for m in masks]
    for fi,f in enumerate(faces):
        if fi in pairs.values():continue
        cx,cy=f.points[1];fw=f.width
        a,b,c,d=max(0,int(cx-fw*4)),max(0,int(cy-fw*5)),min(w,int(cx+fw*4)),min(h,int(cy+fw*13))
        for other in faces:
            if other is f:continue
            ox,oy=other.points[1]
            if abs(oy-cy)<fw*2:
                if ox<cx:a=max(a,int((cx+ox)/2))
                else:c=min(c,int((cx+ox)/2))
        if c-a<20 or d-b<20:continue
        # Proposal recall can be lower on the confirmed-face crop; accepting
        # ownership STILL requires the same unique landmark match and mask
        # confidence/competition thresholds. No nearest-face assignment.
        cp,cm=pose_instances(rgb[b:d,a:c],confidence=.25)
        for p in cp:p[:,:2]+=[a,b]
        confirmed,_=match_faces(faces,cp)
        for pi,matched in confirmed.items():
            if matched!=fi:continue
            prob=np.zeros((mh,mw),np.float32)
            x,y,z,t=round(a*mw/w),round(b*mh/h),round(c*mw/w),round(d*mh/h)
            prob[y:t,x:z]=cv2.resize(cm[pi],(z-x,t-y))
            poses.append(cp[pi]);masks.append(prob)
        pairs,_=match_faces(faces,poses)
    return poses,masks

def assign_skin(skin,masks,pairs):
    """Compete ALL detected people, including those with unmatched faces.

    A high probability and clear advantage are both required. This prevents an
    unrecognised person's arm from being donated to a recognised neighbour.
    """
    owner=np.zeros(skin.shape,np.uint8)
    if not masks or not pairs:return owner
    h,w=skin.shape;mh,mw=masks[0].shape
    probs=np.stack([cv2.resize(m,(mw,mh)) for m in masks])
    winner=probs.argmax(0);best=np.max(probs,axis=0)
    second=np.partition(probs,-2,axis=0)[-2] if len(masks)>1 else np.zeros_like(best)
    valid=(best>.65)&((best-second)>.18)
    small=np.zeros((mh,mw),np.uint8)
    for pi,fi in pairs.items():small[(winner==pi)&valid]=fi+1
    owner[:]=cv2.resize(small,(w,h),interpolation=cv2.INTER_NEAREST)
    owner[~skin]=0
    return owner

def ensure_body_owners(session,need_pose=False):
    if getattr(session,'body_owner',None) is not None and getattr(session,'body_revision',None)==18 and (not need_pose or hasattr(session,'person_landmarks')):
        # Upgrade a failed old pose result once. Reuse its semantic/head masks;
        # current-version caches (including failures) never retry on sliders.
        if getattr(session,'ownership_revision',None)!=19:
            if session.faces and session.body_assignment.get('poses',0)==0:
                poses,masks=recover_instances(session.original,session.faces)
                pairs,costs=match_faces(session.faces,poses)
                session.body_owner=assign_skin(session.body_region,masks,pairs)
                session.person_owner=assign_skin(np.ones(session.body_region.shape,bool),masks,pairs)
                session.person_landmarks={fi:poses[pi] for pi,fi in pairs.items()}
                session.body_assignment.update(poses=len(poses),matched_people=sorted(fi+1 for fi in pairs.values()),
                    face_pose_costs=[[float(v) if np.isfinite(v) else None for v in row] for row in costs],
                    pose_proposal_confidence=.25,ownership_revision=19)
                session.head_skin_revision=None
            session.ownership_revision=19
        recover_head_skin_owners(session);return
    from region_masks import semantic_parts,face_context,ensure_face_parts,face_parts
    session.person_semantics=semantic_parts(session.original)
    session.body_region=session.person_semantics==2
    poses,masks=recover_instances(session.original,session.faces)
    pairs,costs=match_faces(session.faces,poses)
    if len(poses)>1:
        # Give each body a comparable share of the 256px semantic input; a
        # wide group photo otherwise loses small wrists/neck skin altogether.
        h,w=session.original.shape[:2]
        for mask in masks:
            ys,xs=np.where(mask>.65)
            if not xs.size:continue
            mh,mw=mask.shape;pad=max(4,round(.08*max(xs.max()-xs.min(),ys.max()-ys.min())))
            a,b=max(0,int((xs.min()-pad)*w/mw)),max(0,int((ys.min()-pad)*h/mh))
            c,d=min(w,int((xs.max()+pad+1)*w/mw)),min(h,int((ys.max()+pad+1)*h/mh))
            parsed=semantic_parts(session.original[b:d,a:c]);region=session.person_semantics[b:d,a:c]
            update=parsed!=255;region[update]=parsed[update];session.body_region[b:d,a:c]|=parsed==2
    session.body_owner=assign_skin(session.body_region,masks,pairs)
    session.person_owner=assign_skin(np.ones(session.body_region.shape,bool),masks,pairs)
    session.person_landmarks={fi:poses[pi] for pi,fi in pairs.items()}
    # Refresh local part labels, then recover neck/ears through ONE rule below.
    # Global pose ownership and local head ownership are independent evidence;
    # neither a missing pose nor a second refinement gate vetoes a confirmed neck.
    for fi,f in enumerate(session.faces):
        ensure_face_parts(session,fi);box,labels=face_context(session,fi);a,b,c,d=box
        parts,hair,nostrils,local=face_parts(session.original,f,box,labels)
        session.part_regions[fi]=parts;session.part_labels[fi]=local
        session.semantic_skin[fi]=parts['skin'];session.hair[fi]=hair;session.nostrils[fi]=nostrils
        own=session.person_owner[b:d,a:c]
        x,y,z,t=f.box;local=session.part_labels[fi]
        # Propagate recovered ear labels to local scopes too, so body treatment
        # does not subsequently veto them with an obsolete face-skin label.
        local[:]=labels[y-b:t-b,x-a:z-a]
        # Supplement hair/clothes inside this confirmed person's parser crop.
        sem=session.person_semantics[b:d,a:c]
        for code,target in ((17,1),(16,4)):
            use=(labels==code)&(own==fi+1);sem[use]=target
    session.body_revision=18
    session.body_assignment={'poses':len(poses),'matched_people':sorted(fi+1 for fi in pairs.values()),
        'unassigned_skin_pixels':int(np.count_nonzero(session.body_region&(session.body_owner==0))),
        'face_pose_costs':[[float(v) if np.isfinite(v) else None for v in row] for row in costs]}
    session.body_assignment.update(revision=18)
    session.ownership_revision=19
    session.body_assignment.update(ownership_revision=19,pose_proposal_confidence=.25)
    session.head_skin_revision=None
    recover_head_skin_owners(session)

def recover_head_skin_owners(session):
    """Attach parser-confirmed neck/ear skin to its confirmed face, not pose.

    A missing full-body pose must not veto a locally confirmed neck. Candidate
    components must meet the jaw/ear anatomy and competing local candidates
    are left unassigned. Disconnected hands are never assigned by proximity.
    Existing body/person assignments and user layers are not overwritten.
    """
    if getattr(session,'head_skin_revision',None)==20:return
    from region_masks import face_context,below_jaw,facial_exclusion
    h,w=session.original.shape[:2];votes=np.zeros((h,w),np.uint8);proposals=[]
    for fi,f in enumerate(session.faces):
        box,labels=face_context(session,fi);a,b,c,d=box
        body=session.body_owner[b:d,a:c]
        body[np.isin(labels,[9,15,16,17,18])&(body==fi+1)]=0
        x,y,z,t=f.box;local=labels[y-b:t-b,x-a:z-a]
        body=session.body_owner[y:t,x:z]
        body[facial_exclusion(f,local)&(body==fi+1)]=0
        p=f.points.astype(np.float32);down=p[152]-p[10];down/=max(1,np.linalg.norm(down));side=np.array([down[1],-down[0]])
        yy,xx=np.mgrid[b:d,a:c];dx=xx-p[152,0];dy=yy-p[152,1]
        u=dx*side[0]+dy*side[1];v=dx*down[0]+dy*down[1]
        neck=((labels==14)|((labels==1)&below_jaw(f,box)&(v>-f.width*.25)))&(np.abs(u)<f.width*.75)&(v>-f.width*.7)&(v<f.width*2)
        count,cc=cv2.connectedComponents(neck.astype(np.uint8),8)
        anchor=neck&(np.abs(u)<f.width*.4)&(v<f.width*.32)
        touched=np.unique(cc[anchor]);touched=touched[touched!=0]
        neck&=np.isin(cc,touched)
        ear=np.isin(labels,[7,8])&(np.abs(u)>f.width*.25)&(np.abs(u)<f.width*.95)&(v>-f.width*1.4)&(v<f.width*.18)
        # Fuse complementary skin evidence, rather than intersecting two
        # low-resolution masks and keeping their holes. A global skin
        # component must touch this parser-confirmed neck, stay below its jaw
        # and inside the near-head anatomy. No detached hand is selected.
        r=f.width*3
        x,y,z,t=max(0,int(p[152,0]-r)),max(0,int(p[152,1]-r)),min(w,int(p[152,0]+r+1)),min(h,int(p[152,1]+r+1))
        gy,gx=np.mgrid[y:t,x:z];gdx=gx-p[152,0];gdy=gy-p[152,1]
        gu=gdx*side[0]+gdy*side[1];gv=gdx*down[0]+gdy*down[1]
        global_neck=(session.person_semantics[y:t,x:z]==2)&below_jaw(f,(x,y,z,t))&(np.abs(gu)<f.width*1.1)&(gv<f.width*3)
        seed=np.zeros(global_neck.shape,bool);candidate=np.zeros_like(seed)
        x0,y0,x1,y1=max(a,x),max(b,y),min(c,z),min(d,t)
        local=labels[y0-b:y1-b,x0-a:x1-a]
        # The fine parser protects clothing, main hair and accessories where
        # the coarse global skin mask bleeds across their edges.
        global_neck[y0-y:y1-y,x0-x:x1-x][np.isin(local,[9,15,16,17,18])]=False
        seed[y0-y:y1-y,x0-x:x1-x]=neck[y0-b:y1-b,x0-a:x1-a]
        candidate[y0-y:y1-y,x0-x:x1-x]=(neck|ear)[y0-b:y1-b,x0-a:x1-a]
        connected=global_neck|seed
        _,cc=cv2.connectedComponents(connected.astype(np.uint8),8)
        touched=np.unique(cc[seed]);touched=touched[touched!=0]
        candidate|=global_neck&np.isin(cc,touched)
        # Use exactly the face treatment boundary, including semantic cheek
        # and chin beyond the landmark jaw, rather than reassigning them here.
        fa,fb,fc,fd=f.box;fx0,fy0,fx1,fy1=max(fa,x),max(fb,y),min(fc,z),min(fd,t)
        if fx0<fx1 and fy0<fy1:
            exclude=facial_exclusion(f,session.part_labels[fi])
            candidate[fy0-y:fy1-y,fx0-x:fx1-x]&=~exclude[fy0-fb:fy1-fb,fx0-fa:fx1-fa]
        box=(x,y,z,t);a,b,c,d=box
        # Another confirmed face is never this person's neck, even when the
        # wide parser context sees more than one head.
        for fj,other in enumerate(session.faces):
            if fj==fi:continue
            x,y,z,t=other.box;x0,y0,x1,y1=max(a,x),max(b,y),min(c,z),min(d,t)
            if x0<x1 and y0<y1:
                candidate[y0-b:y1-b,x0-a:x1-a][other.mask[y0-y:y1-y,x0-x:x1-x]>0]=False
        own=session.person_owner[b:d,a:c];body=session.body_owner[b:d,a:c]
        candidate&=np.isin(own,[0,fi+1])&np.isin(body,[0,fi+1])
        proposals.append((fi,box,candidate));votes[b:d,a:c]+=candidate
    counts={}
    for fi,box,candidate in proposals:
        a,b,c,d=box;eligible=candidate&(votes[b:d,a:c]==1);body=session.body_owner[b:d,a:c]
        counts[fi+1]=int(np.count_nonzero(eligible&(body==0)))
        body[eligible]=fi+1;session.person_owner[b:d,a:c][eligible]=fi+1
        session.body_region[b:d,a:c]|=eligible;session.person_semantics[b:d,a:c][eligible]=2
    session.head_skin_revision=20
    # Retire counters from the older two-gate refinement; they are no longer
    # measurements of the canonical fused result.
    session.body_assignment.pop('ear_pixels',None)
    session.body_assignment.pop('neck_ear_recovered_pixels',None)
    session.body_assignment.update(head_skin_recovered_pixels=counts,head_skin_revision=20,
        unassigned_skin_pixels=int(np.count_nonzero(session.body_region&(session.body_owner==0))))
