"""Offline, shot-bounded face and visible body tracking; never invent RGB.

Short face gaps are interpolated only between confirmed same-person meshes.
Body widths describe the visible silhouette (including clothes), not anatomy
hidden under a dress. Bidirectional smoothing is for export, not a live camera.
"""
from pathlib import Path
import json
import cv2,numpy as np
from live_body import LiveBody
from core import MODEL,face_mask
from person_masks import match_faces

def needed(recipe):
    from live_body import BODY_KEYS
    return any(getattr(recipe,k) for k in BODY_KEYS+('smooth','whiten','slim','jaw','chin_width','chin_length','eye_size','nose_width','mouth_width','redness','skin_warmth')) or recipe.texture!=50

def silhouette(p,mask,shape):
    h,w=shape;s=p[[11,12],:2].mean(0);hip=p[[23,24],:2].mean(0);axis=hip-s;t=np.linalg.norm(axis)
    if t<20:return None
    down=axis/t;side=np.array([down[1],-down[0]]);sw=np.linalg.norm(p[11,:2]-p[12,:2])
    y,x=np.nonzero(mask>.55)
    if len(x)<100 or sw<16:return None
    q=np.column_stack(((x+.5)*w/mask.shape[1],(y+.5)*h/mask.shape[0]))-s
    u=q@side;v=q@down;valid=(v>t*.12)&(np.abs(u)<sw*2)
    u=u[valid];v=v[valid]
    if len(v)<80:return None
    end=float(np.percentile(v,99.8));length=end-t
    if length<t*.35:return None
    levels=np.r_[np.array([.2,.35,.5,.65,.8,.95])*t,t+np.array([.2,.4,.6,.8,.95])*length]
    bounds=[]
    for level in levels:
        select=np.abs(v-level)<max(4,t*.045);values=u[select]
        bounds.append(np.percentile(values,[2,98]) if len(values)>5 else [np.nan,np.nan])
    return {'origin':s,'hip':hip,'width':float(sw),'torso':float(t),'length':float(length),'bounds':np.asarray(bounds,np.float32)}

def _smooth(a,radius=5):
    # Symmetric local median removes segmentation spikes, then a short Gaussian
    # preserves motions while avoiding a causal tracking delay at 60fps.
    a=np.asarray(a,np.float32);out=a.copy();n=len(a)
    for i in range(n):out[i]=np.median(a[max(0,i-radius):min(n,i+radius+1)],axis=0)
    kernel=2*min(3,radius)+1
    return cv2.GaussianBlur(out.reshape(n,-1),(1,kernel),min(1.2,max(.6,radius/3)),borderType=cv2.BORDER_REPLICATE).reshape(a.shape)

def analyze(source,recipe,size=None,video_index=0,cancel=None,progress=None):
    import av,mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import FaceLandmarker,FaceLandmarkerOptions,RunningMode
    from live_beauty import orient,rotation,check_cancel
    from live_media import read_movie
    pose=LiveBody(recipe)
    options=lambda mode:FaceLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=MODEL.read_bytes()),running_mode=mode,num_faces=1,min_face_detection_confidence=.5,min_face_presence_confidence=.5,min_tracking_confidence=.6)
    detector=FaceLandmarker.create_from_options(options(RunningMode.VIDEO));retry=FaceLandmarker.create_from_options(options(RunningMode.IMAGE));global_detector=FaceLandmarker.create_from_options(options(RunningMode.VIDEO))
    rows=[];previous=None;shot=-1;angle=rotation(read_movie(source,video_index));last_stamp=-1
    try:
        with av.open(str(source)) as c:
            total=c.streams.video[video_index].frames
            for i,frame in enumerate(c.decode(video=video_index)):
                check_cancel(cancel);rgb=orient(frame.to_ndarray(format='rgb24'),angle)
                if size is not None:rgb=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA)
                h,w=rgb.shape[:2];small=cv2.resize(rgb,(96,170));cut=previous is None or float(np.mean(np.abs(small.astype(float)-previous)))>30
                if cut:
                    shot+=1;pose.clear()
                    if previous is not None:
                        detector.close();detector=FaceLandmarker.create_from_options(options(RunningMode.VIDEO))
                        global_detector.close();global_detector=FaceLandmarker.create_from_options(options(RunningMode.VIDEO))
                previous=small.astype(float);stamp=max(last_stamp+1,round(frame.time*1000));last_stamp=stamp
                found=pose.locate(rgb,stamp);points=None;kind='missing';profile=None;p=None
                factor=min(1,960/max(h,w));global_image=cv2.resize(rgb,(round(w*factor),round(h*factor))) if factor<1 else rgb
                global_result=global_detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(global_image)),stamp)
                if global_result.face_landmarks:
                    candidate=np.array([[q.x,q.y] for q in global_result.face_landmarks[0]],np.float32)
                    if found is None or match_faces([face_mask(candidate,rgb.shape)],[found[0]])[0]:points=candidate;kind='video'
                if found is not None:
                    p,mask=found;profile=silhouette(p,mask,(h,w));box=pose.head_crop(rgb,stamp)
                    if points is None and box is not None:
                        a,b,z,d=box;result=detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(rgb[b:d,a:z])),stamp)
                        if result.face_landmarks:
                            candidate=np.array([[(q.x*(z-a)+a)/w,(q.y*(d-b)+b)/h] for q in result.face_landmarks[0]],np.float32)
                            if match_faces([face_mask(candidate,rgb.shape)],[p])[0]:points=candidate;kind='video'
                        if points is None:
                            # Independent IMAGE retry recovers tracking failures;
                            # every result still must match this body's geometry.
                            cx,cy=(a+z)/2,(b+d)/2
                            for factor in (1.,1.4):
                                half=max(z-a,d-b)*factor/2;x0,y0=max(0,int(cx-half)),max(0,int(cy-half));x1,y1=min(w,int(cx+half)),min(h,int(cy+half))
                                result=retry.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(rgb[y0:y1,x0:x1])))
                                if not result.face_landmarks:continue
                                candidate=np.array([[(q.x*(x1-x0)+x0)/w,(q.y*(y1-y0)+y0)/h] for q in result.face_landmarks[0]],np.float32)
                                if match_faces([face_mask(candidate,rgb.shape)],[p])[0]:points=candidate;kind='image_retry';break
                rows.append({'shot':shot,'time':frame.time,'face':points,'face_kind':kind,'pose':p,'profile':profile})
                if progress and i%120==0:progress('分析视频轨迹',i+1,total,None)
    finally:detector.close();retry.close();global_detector.close();pose.close()
    return finish(rows,(h,w))

def finish(rows,shape):
    h,w=shape;shot=-1
    for shot in sorted({r['shot'] for r in rows}):
        indices=[i for i,r in enumerate(rows) if r['shot']==shot];local=[rows[i] for i in indices];n=len(local)
        valid=[i for i,r in enumerate(local) if r['face'] is not None]
        for i,r in enumerate(local):
            if r['face'] is not None:continue
            left=[j for j in valid if j<i];right=[j for j in valid if j>i]
            if not left or not right:continue
            a,b=left[-1],right[0];dt=local[b]['time']-local[a]['time']
            if dt>.3 or r['pose'] is None:continue
            alpha=(r['time']-local[a]['time'])/dt;candidate=local[a]['face']*(1-alpha)+local[b]['face']*alpha
            if match_faces([face_mask(candidate,(h,w,3))],[r['pose']])[0]:r['face']=candidate;r['face_kind']='interpolated'
        # Smooth observed body measurements only within this shot.
        for r in local:
            if r['profile'] is None:continue
            r['profile_kind']='measured'
        good=[i for i,r in enumerate(local) if r['profile'] is not None]
        absent=[i for i,r in enumerate(local) if r['profile'] is None]
        if not good:continue
        for key in ('origin','hip','width','torso','length','bounds'):
            values=np.stack([local[i]['profile'][key] for i in good]);flat=values.reshape(len(good),-1)
            interpolated=np.empty((n,flat.shape[1]),np.float32)
            for k in range(flat.shape[1]):
                finite=np.isfinite(flat[:,k]);selected=np.asarray(good)[finite]
                if not len(selected):
                    # Visible envelope lacks a row, use adjacent measured rows,
                    # bounded by this shot's median shoulder width.
                    if key=='bounds':
                        for row,j in enumerate(good):
                            observed=local[j]['profile']['bounds'][:,k%2];known=np.where(np.isfinite(observed))[0]
                            if not len(known):raise ValueError('该镜头没有可确认的身体边缘，不能构造身体形变。')
                            flat[row,k]=np.interp(k//2,known,observed[known])
                    else:raise ValueError('该镜头缺少可靠身体定位，不能构造身体形变。')
                    finite[:]=True;selected=np.asarray(good)
                interpolated[:,k]=np.interp(np.arange(n),selected,flat[finite,k])
            step=np.median(np.diff([r['time'] for r in local])) if n>1 else 1/60
            smooth=_smooth(interpolated,radius=max(1,min(5,round(.08/max(.001,step))))).reshape((n,)+values.shape[1:])
            for i,r in enumerate(local):
                if r['profile'] is None:r['profile']={};r['profile_kind']='interpolated'
                r['profile'][key]=smooth[i]
        for r in local:
            profile=r['profile'];profile['width']=float(profile['width']);profile['torso']=float(profile['torso']);profile['length']=float(profile['length'])
        for i in absent:
            near=min(abs(local[i]['time']-local[j]['time']) for j in good)
            left=[j for j in good if j<i];right=[j for j in good if j>i]
            gap=local[right[0]]['time']-local[left[-1]]['time'] if left and right else near*2
            if near>.15 or gap>.3:local[i]['profile']=None;local[i]['profile_kind']='missing'
    return rows,{'frames':len(rows),'shots':shot+1,'face_direct':sum(r['face_kind']=='video' for r in rows),'face_image_retry':sum(r['face_kind']=='image_retry' for r in rows),'face_interpolated':sum(r['face_kind']=='interpolated' for r in rows),'face_missing':sum(r['face'] is None for r in rows),'body_profile_missing':sum(r['profile'] is None for r in rows),'body_profile_interpolated':sum(r.get('profile_kind')=='interpolated' for r in rows)}

def save(path,rows,report):
    arrays={'face':np.stack([r['face'] if r['face'] is not None else np.full((478,2),np.nan) for r in rows]),
            'pose':np.stack([r['pose'] if r['pose'] is not None else np.full((33,4),np.nan) for r in rows])}
    for key,shape in [('origin',(2,)),('hip',(2,)),('width',()),('torso',()),('length',()),('bounds',(11,2))]:
        arrays[key]=np.stack([r['profile'][key] if r['profile'] is not None else np.full(shape,np.nan) for r in rows])
    metadata=[{k:r.get(k) for k in ('shot','time','face_kind','profile_kind')} for r in rows]
    arrays['metadata']=np.array(json.dumps({'frames':metadata,'report':report},ensure_ascii=False))
    np.savez_compressed(path,**arrays)

def load(path):
    with np.load(path,allow_pickle=False) as data:
        meta=json.loads(str(data['metadata']));rows=[]
        arrays={k:data[k] for k in ('face','pose','origin','hip','width','torso','length','bounds')}
        for i,r in enumerate(meta['frames']):
            r['face']=arrays['face'][i] if np.isfinite(arrays['face'][i]).all() else None
            r['pose']=arrays['pose'][i] if np.isfinite(arrays['pose'][i]).all() else None
            r['profile']={k:arrays[k][i] for k in ('origin','hip','width','torso','length','bounds')} if np.isfinite(arrays['width'][i]) else None
            rows.append(r)
    return rows,meta['report']

def still(engine,rgb,timestamp=0):
    """Same visible-envelope geometry for cover preview and exported cover."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import FaceLandmarker,FaceLandmarkerOptions,RunningMode
    h,w=rgb.shape[:2];scale=min(1,960/max(h,w));small=cv2.resize(rgb,(round(w*scale),round(h*scale))) if scale<1 else rgb
    result=engine.detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(small)),timestamp)
    points=np.array([[q.x,q.y] for q in result.face_landmarks[0]],np.float32) if result.face_landmarks else None
    owned=engine.body is None;locator=LiveBody(engine.recipe) if owned else engine.body
    try:
        found=locator.locate(rgb,timestamp);box=locator.head_crop(rgb,timestamp) if found is not None else None
    finally:
        if owned:locator.close()
    profile=None;p=None
    if found is not None:
        p,mask=found;profile=silhouette(p,mask,(h,w))
        if points is None and box is not None:
            a,b,c,d=box
            with FaceLandmarker.create_from_options(FaceLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=MODEL.read_bytes()),running_mode=RunningMode.IMAGE,num_faces=1,min_face_detection_confidence=.5,min_face_presence_confidence=.5)) as detector:
                result=detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(rgb[b:d,a:c])))
                if result.face_landmarks:
                    candidate=np.array([[(q.x*(c-a)+a)/w,(q.y*(d-b)+b)/h] for q in result.face_landmarks[0]],np.float32)
                    if match_faces([face_mask(candidate,rgb.shape)],[p])[0]:points=candidate
    if profile is not None:
        bounds=profile['bounds'];good=np.isfinite(bounds).all(axis=1)
        if good.any():
            for k in range(2):bounds[:,k]=np.interp(np.arange(len(bounds)),np.where(good)[0],bounds[good,k])
        else:profile=None
    return {'face':points,'pose':p,'profile':profile,'shot':0,'face_kind':'still','profile_kind':'measured'}
