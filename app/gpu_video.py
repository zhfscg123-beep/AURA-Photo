"""GPU pixel processing for existing video/live-photo engines.

Face/pose detection, compact motion analysis and small coordinate fitting retain
their existing CPU-compatible APIs. Full image filters, temporal compositing,
body/face resampling and color processing use resident CUDA arrays.
"""
import functools
import numpy as np
from gpu_backend import cupy,CV,upload,download,FrameStats,is_device
from gpu_render import variant,DOMAIN_LOCK,record_cpu_recovery
_installed=False


def install_device_dispatch():
    global _installed
    if _installed:return
    import face_reshape,live_body
    for module,name in ((face_reshape,'apply'),(live_body,'apply_body_field')):
        original=getattr(module,name)
        @functools.wraps(original)
        def wrapper(*args,_fn=original,**kwargs):
            return variant(_fn)(*args,**kwargs) if any(is_device(x) for x in args) else _fn(*args,**kwargs)
        setattr(module,name,wrapper)
    _installed=True


def process(engine,rgb,timestamp_ms,tracked=None,prepared=None):
    from types import SimpleNamespace
    from core import face_mask
    from ai_engine import parse_skin,square_box
    from video_skin import masks,retouch,SKIN_REVISION
    from live_beauty import prepare_video_frame
    import video_body_field,creative_color
    cp=cupy();install_device_dispatch()
    with DOMAIN_LOCK,FrameStats() as trace:
        stamp=max(engine.timestamp+1,int(round(timestamp_ms)));engine.timestamp=stamp
        h,w=rgb.shape[:2];ratio=min(1,960/max(h,w));device=upload(rgb)
        small=CV.resize(device,(round(w*ratio),round(h*ratio)),interpolation=CV.cv.INTER_LINEAR) if ratio<1 else device
        small_host=download(small,'compact face/motion analysis input')
        if tracked is None:
            if engine.detector is None:raise ValueError('缓存预览必须提供已定位轨迹。')
            result=engine.detector.detect_for_video(engine.mp.Image(image_format=engine.mp.ImageFormat.SRGB,data=np.ascontiguousarray(small_host)),stamp)
        else:
            result=SimpleNamespace(face_landmarks=[])
            if engine.body is not None:engine.body.detected_stamp=stamp;engine.body.detected=None
        fallback=tracked.get('face') if tracked is not None else None
        if tracked is None and not result.face_landmarks and engine.body is not None:
            box=engine.body.head_crop(rgb,stamp)
            if box is not None:
                if engine.crop_detector is None:
                    from mediapipe.tasks.python import BaseOptions
                    from mediapipe.tasks.python.vision import FaceLandmarker,FaceLandmarkerOptions,RunningMode
                    from core import MODEL
                    engine.crop_detector=FaceLandmarker.create_from_options(FaceLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=MODEL.read_bytes()),running_mode=RunningMode.VIDEO,num_faces=1,min_face_detection_confidence=.6,min_face_presence_confidence=.6,min_tracking_confidence=.6))
                a,b,c,d=box;crop=np.ascontiguousarray(rgb[b:d,a:c]);found=engine.crop_detector.detect_for_video(engine.mp.Image(image_format=engine.mp.ImageFormat.SRGB,data=crop),stamp)
                if found.face_landmarks:
                    candidate=np.array([[(p.x*(c-a)+a)/w,(p.y*(d-b)+b)/h] for p in found.face_landmarks[0]],np.float32)
                    from person_masks import match_faces
                    if match_faces([face_mask(candidate,rgb.shape)],[engine.body.detected[0]])[0]:fallback=candidate;engine.crop_face_frames+=1
        mask=cp.zeros((h,w),cp.float32);edited=device.astype(cp.float32);center=None;geometry=None
        if result.face_landmarks or fallback is not None:
            points=fallback if fallback is not None else np.array([[p.x,p.y] for p in result.face_landmarks[0]],np.float32)
            f=face_mask(points,rgb.shape);a,b,c,d=f.box;center=points.mean(axis=0)
            if c>a and d>b and f.width>=24:
                if prepared is not None and prepared.get('geometry') is not None and prepared.get('skin_revision')!=SKIN_REVISION:prepared=prepare_video_frame(rgb,{'face':points})
                if prepared is None:
                    context=square_box(f.box,rgb.shape);skin,hair,labels=parse_skin(rgb,context)
                    weights=masks(rgb,f,context,labels);soft=weights['tone']
                elif prepared['geometry'] is None:context=None;labels=None;soft=np.zeros((d-b,c-a),np.float32)
                else:f,context,labels=prepared['geometry'];weights=prepared['weights'];soft=weights['tone']
                mask[b:d,a:c]=upload(soft);geometry=(f,context,labels) if context is not None else None
                source=edited[b:d,a:c]
                if prepared is not None and prepared['geometry'] is not None:fine,low=upload(prepared['fine']),upload(prepared['low'])
                else:
                    fine=CV.GaussianBlur(source,(0,0),max(.65,f.width*.0035));low=CV.bilateralFilter(fine,0,22,max(2,f.width*.015))
                if context is not None:edited[b:d,a:c]=variant(retouch)(source,fine,low,weights,engine.recipe);engine.faces+=1
        delta=edited-device;gray=CV.cvtColor(small,CV.cv.COLOR_RGB2GRAY);gray_host=download(gray,'compact optical flow analysis');reset=False
        if engine.previous is not None and engine.previous.shape==gray_host.shape and engine.recipe.temporal>0 and center is not None and engine.previous_center is not None:
            jump=np.linalg.norm(center-engine.previous_center)>.15;cut=float(np.mean(np.abs(gray_host.astype(np.float32)-engine.previous.astype(np.float32))))>35
            if not jump and not cut:
                backward=upload(engine.flow.calc(gray_host,engine.previous,None));forward=upload(engine.flow.calc(engine.previous,gray_host,None))
                sy,sx=cp.indices(gray.shape,dtype=cp.float32);bx=sx+backward[:,:,0];by=sy+backward[:,:,1]
                consistency=cp.linalg.norm(backward+CV.remap(forward,bx,by,CV.cv.INTER_LINEAR),axis=2)<1.5
                oldgray=CV.remap(upload(engine.previous),bx,by,CV.cv.INTER_LINEAR);photo=cp.abs(oldgray.astype(cp.float32)-gray.astype(cp.float32))<15
                valid=(bx>=0)&(by>=0)&(bx<gray.shape[1]-1)&(by<gray.shape[0]-1)&consistency&photo
                full=CV.resize(backward,(w,h),interpolation=CV.cv.INTER_LINEAR);full[:,:,0]*=w/gray.shape[1];full[:,:,1]*=h/gray.shape[0]
                yy,xx=cp.indices((h,w),dtype=cp.float32);mx=xx+full[:,:,0];my=yy+full[:,:,1]
                olddelta=CV.remap(upload(engine.previous_delta),mx,my,CV.cv.INTER_LINEAR);oldmask=CV.remap(upload(engine.previous_mask),mx,my,CV.cv.INTER_LINEAR)
                blend=CV.resize(valid.astype(cp.float32),(w,h),interpolation=CV.cv.INTER_NEAREST)*cp.minimum(mask,oldmask)*engine.recipe.temporal
                delta+=(olddelta-delta)*blend[:,:,None]
            else:engine.resets+=1;reset=True
        engine.previous=gray_host.copy();engine.previous_delta=delta.copy();engine.previous_mask=mask.copy();engine.previous_center=center
        engine.frames+=1;output=device.astype(cp.float32)+delta
        if geometry is not None:output=engine.shape.apply(output,*geometry,engine.recipe.shape_settings(),reset=reset)
        else:engine.shape.clear()
        if engine.body is not None and tracked is None:output=engine.body.process(rgb,output,stamp,geometry[0] if geometry is not None else None,reset=reset)
        elif engine.body is not None:
            output,field=variant(video_body_field.apply)(output,tracked,engine.recipe);engine.body.last_field=field;engine.body.last_applied=field is not None
            if field is not None:
                engine.body.frames+=1;engine.body.pose_frames+=int(tracked.get('pose') is not None);engine.body.minimum_jacobian=min(engine.body.minimum_jacobian,field['jacobian_min'])
                if field['effective_scale']<1:engine.body.reduced_frames+=1
                for name in field['features']:engine.body.features[name]+=1
            elif any(getattr(engine.recipe,k) for k in ('body_slim','waist_slim','leg_slim','leg_length')):engine.body.skipped['可见身体轮廓不足']+=1
        if any(getattr(engine.recipe,k) for k in ('exposure','contrast','temperature','saturation')):
            output=variant(creative_color.apply)(output,{'values':{k:getattr(engine.recipe,k) for k in ('exposure','contrast','temperature','saturation')}})
        result=download(cp.clip(cp.rint(output),0,255).astype(cp.uint8),'video frame encoder/presentation')
        mask_host=download(mask,'video mask metadata')
    trace['backend']='CUDA';engine.render_trace=trace
    return result,mask_host
