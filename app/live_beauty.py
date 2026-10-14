"""Single-person SDR Live Photo evaluation engine; ordered VIDEO inference."""
from pathlib import Path
from dataclasses import dataclass,asdict
from fractions import Fraction
import json,threading,tempfile,os,hashlib,sys,io
import cv2,numpy as np
from PIL import Image,ImageCms
from live_media import ROOT,read_movie,replace_video,open_cover,extract_motion_photo,pack_motion_photo,children,child,payload

@dataclass(frozen=True)
class LiveRecipe:
    smooth:float=40
    whiten:float=25
    texture:float=50
    temporal:float=.25
    slim:float=0
    jaw:float=0
    chin_width:float=0
    chin_length:float=0
    eye_size:float=0
    nose_width:float=0
    mouth_width:float=0
    redness:float=0
    skin_warmth:float=0
    exposure:float=0
    contrast:float=0
    temperature:float=0
    saturation:float=0
    body_slim:float=0
    waist_slim:float=0
    leg_slim:float=0
    leg_length:float=0
    body_protect_lines:bool=True
    def validate(self):
        for key in ('smooth','whiten','texture'):
            if not 0<=getattr(self,key)<=100:raise ValueError('美颜参数需在0–100之间。')
        if not 0<=self.temporal<=.6:raise ValueError('时序强度需在0–0.6之间。')
        if not 0<=self.slim<=50:raise ValueError('实况瘦脸范围为0–50。')
        from live_body import BODY_KEYS
        for key in BODY_KEYS:
            if not 0<=getattr(self,key)<=50:raise ValueError('实况身体美型范围为0–50：'+key)
        if type(self.body_protect_lines) is not bool:raise ValueError('背景线保护开关无效。')
        for key in ('jaw','chin_width','chin_length','eye_size','nose_width','mouth_width','redness','skin_warmth','contrast','temperature','saturation'):
            if not -50<=getattr(self,key)<=50:raise ValueError('实况参数范围为-50–50：'+key)
        if not -2<=self.exposure<=2:raise ValueError('实况曝光范围为-2–2。')
        if not all(np.isfinite(v) for v in asdict(self).values()):raise ValueError('实况参数不能包含无效数字。')
    def shape_settings(self):
        return {'rs_slim_left':self.slim,'rs_slim_right':self.slim,'rs_jaw_left':self.jaw,'rs_jaw_right':self.jaw,
                'rs_chin_width':self.chin_width,'rs_chin_length':self.chin_length,'fs_eye_left_size':self.eye_size,
                'fs_eye_right_size':self.eye_size,'fs_nose_width':self.nose_width,'fs_mouth_width':self.mouth_width}

def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError('实况处理已取消，原件未修改。')

def rotation(movie):
    p=payload(child(movie.video,b'tkhd'));start=52 if p[0] else 40
    matrix=struct_unpack('>9i',p,start)
    angle=int(round(np.degrees(np.arctan2(matrix[1],matrix[0]))/90))*90%360
    if abs(matrix[0])+abs(matrix[1])!=65536 or matrix[2]!=0 or matrix[5]!=0:raise ValueError('暂不支持非直角视频显示变换。')
    return angle

def struct_unpack(fmt,data,offset):
    import struct
    return struct.unpack_from(fmt,data,offset)

def orient(rgb,angle):return np.ascontiguousarray(np.rot90(rgb,-angle//90)) if angle else np.ascontiguousarray(rgb)

def resize_video(rgb,size):
    if os.environ.get('AURA_RENDER_BACKEND','cuda').lower()!='cpu':
        try:
            from gpu_render import resize_pixels
            return resize_pixels(rgb,size)
        except Exception as error:
            from gpu_render import record_cpu_recovery
            record_cpu_recovery('视频帧重采样',error)
    return cv2.resize(rgb,size,interpolation=cv2.INTER_AREA)

def prepare_video_frame(rgb,tracked):
    """Parameter-independent face segmentation and filters for cached preview."""
    from core import face_mask
    from ai_engine import parse_skin,square_box
    points=tracked.get('face')
    if points is None:return {'geometry':None}
    f=face_mask(points,rgb.shape);a,b,c,d=f.box
    if c<=a or d<=b or f.width<24:return {'geometry':None}
    context=square_box(f.box,rgb.shape);skin,hair,labels=parse_skin(rgb,context);x,y,_,_=context
    from video_skin import masks,SKIN_REVISION
    weights=masks(rgb,f,context,labels)
    source=rgb[b:d,a:c].astype(np.float32)
    from gpu_render import execute_pixel,surface_filters,record_cpu_recovery
    try:fine,low=execute_pixel(surface_filters,source,f.width,host_result=True)
    except Exception as error:
        record_cpu_recovery('视频基础滤波缓存',error);fine=cv2.GaussianBlur(source,(0,0),max(.65,f.width*.0035));low=cv2.bilateralFilter(fine,0,22,max(2,f.width*.015))
    return {'geometry':(f,context,labels),'soft':weights['tone'],'weights':weights,'fine':fine,'low':low,'skin_revision':SKIN_REVISION}

class VideoBeautifier:
    def __init__(self,recipe,tracking=True):
        recipe.validate();self.recipe=recipe
        self.detector=None
        if tracking:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import FaceLandmarker,FaceLandmarkerOptions,RunningMode
            from core import MODEL
            self.mp=mp;self.detector=FaceLandmarker.create_from_options(FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_buffer=MODEL.read_bytes()),running_mode=RunningMode.VIDEO,
                num_faces=1,min_face_detection_confidence=.5,min_face_presence_confidence=.5,min_tracking_confidence=.6))
        self.previous=None;self.previous_delta=None;self.previous_mask=None;self.previous_center=None
        self.timestamp=-1;self.frames=0;self.faces=0;self.resets=0
        self.render_trace={};self.render_frames={'CUDA':0,'CPU':0}
        self.flow=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
        from live_shape import LiveShape
        self.shape=LiveShape()
        from live_body import BODY_KEYS,LiveBody,BodyRenderStats
        try:self.body=(LiveBody(recipe) if any(getattr(recipe,k) for k in BODY_KEYS) else None) if tracking else BodyRenderStats()
        except Exception:
            if self.detector is not None:self.detector.close()
            raise
        self.crop_detector=None;self.crop_face_frames=0
    def close(self):
        if self.detector is not None:self.detector.close()
        self.previous=None;self.previous_delta=None;self.previous_mask=None;self.shape.clear()
        if self.body is not None:self.body.close()
        if self.crop_detector is not None:self.crop_detector.close()
    def process(self,rgb,timestamp_ms,tracked=None,prepared=None):
        import os
        reason='explicit CPU override'
        if os.environ.get('AURA_RENDER_BACKEND','cuda').lower()!='cpu':
            try:
                from gpu_video import process
                result=process(self,rgb,timestamp_ms,tracked,prepared)
                self.render_frames['CUDA']+=1
                return result
            except Exception as error:
                from gpu_render import record_cpu_recovery
                record_cpu_recovery('视频/实况像素渲染',error)
                reason=str(error)
                self.previous=None;self.previous_delta=None;self.previous_mask=None;self.previous_center=None
        result=self.process_cpu(rgb,timestamp_ms,tracked,prepared)
        self.render_frames['CPU']+=1;self.render_trace={'backend':'CPU','reason':reason}
        return result
    def process_cpu(self,rgb,timestamp_ms,tracked=None,prepared=None):
        stamp=max(self.timestamp+1,int(round(timestamp_ms)));self.timestamp=stamp
        h,w=rgb.shape[:2];ratio=min(1,960/max(h,w));small=cv2.resize(rgb,(round(w*ratio),round(h*ratio))) if ratio<1 else rgb
        if tracked is None:
            if self.detector is None:raise ValueError('缓存预览必须提供已定位轨迹。')
            result=self.detector.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=np.ascontiguousarray(small)),stamp)
        else:
            from types import SimpleNamespace
            result=SimpleNamespace(face_landmarks=[])
            if self.body is not None:
                self.body.detected_stamp=stamp;self.body.detected=None
        fallback_points=tracked.get('face') if tracked is not None else None
        if tracked is None and not result.face_landmarks and self.body is not None:
            box=self.body.head_crop(rgb,stamp)
            if box is not None:
                if self.crop_detector is None:
                    from mediapipe.tasks.python import BaseOptions
                    from mediapipe.tasks.python.vision import FaceLandmarker,FaceLandmarkerOptions,RunningMode
                    from core import MODEL
                    self.crop_detector=FaceLandmarker.create_from_options(FaceLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=MODEL.read_bytes()),running_mode=RunningMode.VIDEO,num_faces=1,min_face_detection_confidence=.6,min_face_presence_confidence=.6,min_tracking_confidence=.6))
                a,b,c,d=box;crop=np.ascontiguousarray(rgb[b:d,a:c])
                local=self.crop_detector.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=crop),stamp)
                if local.face_landmarks:
                    candidate=np.array([[(p.x*(c-a)+a)/w,(p.y*(d-b)+b)/h] for p in local.face_landmarks[0]],np.float32)
                    from core import face_mask
                    from person_masks import match_faces
                    if match_faces([face_mask(candidate,rgb.shape)],[self.body.detected[0]])[0]:
                        fallback_points=candidate;self.crop_face_frames+=1
        mask=np.zeros((h,w),np.float32);edited=rgb.astype(np.float32);center=None;geometry=None
        if result.face_landmarks or fallback_points is not None:
            from core import face_mask
            from ai_engine import parse_skin,square_box
            points=fallback_points if fallback_points is not None else np.array([[p.x,p.y] for p in result.face_landmarks[0]],np.float32)
            f=face_mask(points,rgb.shape);a,b,c,d=f.box;center=points.mean(axis=0)
            if c>a and d>b and f.width>=24:
                from video_skin import masks,retouch,SKIN_REVISION
                if prepared is not None and prepared.get('geometry') is not None and prepared.get('skin_revision')!=SKIN_REVISION:prepared=prepare_video_frame(rgb,{'face':points})
                if prepared is None:
                    context=square_box(f.box,rgb.shape)
                    skin,hair,labels=parse_skin(rgb,context)
                    weights=masks(rgb,f,context,labels);soft=weights['tone']
                elif prepared['geometry'] is None:context=None;labels=None;soft=np.zeros((d-b,c-a),np.float32)
                else:f,context,labels=prepared['geometry'];weights=prepared['weights'];soft=weights['tone']
                mask[b:d,a:c]=soft
                geometry=(f,context,labels) if context is not None else None
                source=edited[b:d,a:c]
                if prepared is not None and prepared['geometry'] is not None:fine,low=prepared['fine'],prepared['low']
                else:fine=cv2.GaussianBlur(source,(0,0),max(.65,f.width*.0035));low=cv2.bilateralFilter(fine,0,22,max(2,f.width*.015))
                if context is not None:edited[b:d,a:c]=retouch(source,fine,low,weights,self.recipe);self.faces+=1
        delta=edited-rgb
        # Estimate backward and forward flow at bounded resolution. Stabilize
        # only correction deltas with bidirectional/photometric/skin gating.
        gray=cv2.cvtColor(small,cv2.COLOR_RGB2GRAY);reset=False
        if self.previous is not None and self.previous.shape==gray.shape and self.recipe.temporal>0 and center is not None and self.previous_center is not None:
            jump=np.linalg.norm(center-self.previous_center)>.15
            cut=float(np.mean(np.abs(gray.astype(np.float32)-self.previous.astype(np.float32))))>35
            if not jump and not cut:
                backward=self.flow.calc(gray,self.previous,None);forward=self.flow.calc(self.previous,gray,None)
                sy,sx=np.indices(gray.shape,dtype=np.float32);bx=sx+backward[:,:,0];by=sy+backward[:,:,1]
                consistency=np.linalg.norm(backward+cv2.remap(forward,bx,by,cv2.INTER_LINEAR),axis=2)<1.5
                oldgray=cv2.remap(self.previous,bx,by,cv2.INTER_LINEAR)
                photo=np.abs(oldgray.astype(np.float32)-gray.astype(np.float32))<15
                valid=(bx>=0)&(by>=0)&(bx<gray.shape[1]-1)&(by<gray.shape[0]-1)&consistency&photo
                full=cv2.resize(backward,(w,h));full[:,:,0]*=w/gray.shape[1];full[:,:,1]*=h/gray.shape[0]
                yy,xx=np.indices((h,w),dtype=np.float32);mx=xx+full[:,:,0];my=yy+full[:,:,1]
                olddelta=cv2.remap(self.previous_delta,mx,my,cv2.INTER_LINEAR)
                oldmask=cv2.remap(self.previous_mask,mx,my,cv2.INTER_LINEAR)
                blend=cv2.resize(valid.astype(np.float32),(w,h),interpolation=cv2.INTER_NEAREST)*np.minimum(mask,oldmask)*self.recipe.temporal
                delta=delta+(olddelta-delta)*blend[:,:,None]
            else:self.resets+=1;reset=True
        self.previous=gray.copy();self.previous_delta=delta.copy();self.previous_mask=mask.copy();self.previous_center=center
        self.frames+=1;output=rgb.astype(np.float32)+delta
        if geometry is not None:output=self.shape.apply(output,*geometry,self.recipe.shape_settings(),reset=reset)
        else:self.shape.clear()
        if self.body is not None and tracked is None:output=self.body.process(rgb,output,stamp,geometry[0] if geometry is not None else None,reset=reset)
        elif self.body is not None:
            from video_body_field import apply
            output,field=apply(output,tracked,self.recipe);self.body.last_field=field;self.body.last_applied=field is not None
            if field is not None:
                self.body.frames+=1;self.body.pose_frames+=int(tracked.get('pose') is not None)
                self.body.minimum_jacobian=min(self.body.minimum_jacobian,field['jacobian_min'])
                if field['effective_scale']<1:self.body.reduced_frames+=1
                for name in field['features']:self.body.features[name]+=1
            elif any(getattr(self.recipe,k) for k in ('body_slim','waist_slim','leg_slim','leg_length')):self.body.skipped['可见身体轮廓不足']+=1
        if any(getattr(self.recipe,k) for k in ('exposure','contrast','temperature','saturation')):
            from creative_color import apply
            output=apply(output,{'values':{k:getattr(self.recipe,k) for k in ('exposure','contrast','temperature','saturation')}})
        return np.clip(np.rint(output),0,255).astype(np.uint8),mask

def decode_info(path,video_index=0):
    import av
    with av.open(str(path)) as c:
        if not 0<=video_index<len(c.streams.video):raise ValueError('视频轨道不可读取。')
        s=c.streams.video[video_index]
        if int(s.codec_context.color_trc) in (16,18):raise ValueError('测试版尚未接入HDR色彩管理，请使用SDR实况原件。')
        return dict(width=s.width,height=s.height,rate=s.average_rate or Fraction(30),time_base=s.time_base,
                    duration=float(s.duration*s.time_base) if s.duration else None,
                    trc=int(s.codec_context.color_trc),space=int(s.codec_context.colorspace),primaries=int(s.codec_context.color_primaries),range=int(s.codec_context.color_range))

def video_pts(path,video_index=0):
    import av
    with av.open(str(path)) as c:return [Fraction(f.pts)*f.time_base for f in c.decode(video=video_index)]

def encode_beauty(source,target,recipe,cancel,progress,video_index=0):
    import av
    movie=read_movie(source,video_index);info=decode_info(source,video_index);angle=rotation(movie)
    width,height=info['width'],info['height']
    if width%2 or height%2:raise ValueError('测试版暂不支持奇数尺寸视频。')
    if info['duration'] is not None and info['duration']>15.1:raise ValueError('实况测试版最多处理15秒；普通视频请使用视频开发测试入口。')
    from video_tracks import needed
    tracks=None;track_report=None
    if needed(recipe):
        from video_tracks import analyze
        tracks,track_report=analyze(source,recipe,video_index=video_index,cancel=cancel,progress=progress)
    engine=VideoBeautifier(recipe);pts=[];detections=[];first=None
    try:
        with av.open(str(source)) as src,av.open(str(target),'w',format='mov',options={'movie_timescale':str(movie.movie_scale),'video_track_timescale':str(movie.video_scale)}) as dst:
            out=dst.add_stream('libx264',rate=info['rate']);out.width=width;out.height=height;out.pix_fmt='yuv420p'
            out.time_base=out.codec_context.time_base=Fraction(1,movie.video_scale)
            out.options={'crf':'17','preset':'medium','bf':'0'}
            for attr,key in [('color_trc','trc'),('colorspace','space'),('color_primaries','primaries')]:
                setattr(out.codec_context,attr,info[key])
            # RGB conversion creates a new limited-range video; do not tag it as
            # full-range just because the input camera used full-range YUV.
            out.codec_context.color_range=1
            stream=src.streams.video[video_index]
            for i,frame in enumerate(src.decode(stream)):
                check_cancel(cancel)
                if frame.pts is None:raise ValueError('视频帧缺少时间戳。')
                t=Fraction(frame.pts)*frame.time_base
                if pts and t<=pts[-1]:raise ValueError('视频时间戳不递增。')
                if first is None:first=t
                pts.append(t)
                if t-first>15 or i>=1800:raise ValueError('测试版最多处理15秒实况短视频。')
                rgb=frame.to_ndarray(format='rgb24');view=orient(rgb,angle)
                tracked=tracks[i] if tracks is not None else None
                if tracked is not None and (i==0 or tracked['shot']!=tracks[i-1]['shot']):engine.previous=None;engine.previous_center=None;engine.shape.clear()
                beautified,mask=engine.process(view,float((t-first)*1000),tracked=tracked);detections.append(bool(mask.any()))
                encoded=av.VideoFrame.from_ndarray(orient(beautified,(-angle)%360),format='rgb24')
                encoded.pts=round(t*movie.video_scale);encoded.time_base=out.codec_context.time_base
                if frame.duration:encoded.duration=round(frame.duration*frame.time_base*movie.video_scale)
                for packet in out.encode(encoded):dst.mux(packet)
                if progress:progress(f'视频轨道{video_index+1}美颜',i+1,stream.frames or 0,beautified if i%6==0 else None)
            for packet in out.encode():dst.mux(packet)
        if not pts:raise ValueError('视频中没有可解码的帧。')
        encoded_pts=video_pts(target)
        if pts!=encoded_pts:raise ValueError('编码改变了视频帧数或时间戳，禁止导出实况。')
        return {'frames':len(pts),'face_frames':sum(detections),'tracking_resets':engine.resets,'duration_pts':float(pts[-1]-pts[0]),
                'pts_sha256':hashlib.sha256(str(pts).encode()).hexdigest(),'pts_preserved':True,'recipe':asdict(recipe),'running_mode':'VIDEO','num_faces':1,
                'video_index':video_index,'track_analysis':track_report,'crop_face_frames':engine.crop_face_frames,'shape_frames':engine.shape.frames,'shape_min_jacobian':engine.shape.minimum_jacobian,'shape_reduced_frames':engine.shape.reduced_frames,
                'render_backend':engine.render_trace,'render_frames':dict(engine.render_frames),
                **(engine.body.report() if engine.body is not None else {'body_frames':0,'pose_frames':0,'body_feature_frames':{},'body_skip_reasons':{}})}
    finally:engine.close()

def process_live(image_path,video_path,output_dir,recipe=LiveRecipe(),cancel=None,progress=None):
    recipe.validate();image_path=Path(image_path).resolve();output_dir=Path(output_dir).resolve()
    if output_dir.exists():raise FileExistsError('请使用新的输出文件夹，测试版不覆盖已有内容。')
    parent=output_dir.parent;parent.mkdir(parents=True,exist_ok=True)
    # All transient files live next to the requested output, never by originals.
    with tempfile.TemporaryDirectory(prefix='.aura-live-',dir=parent) as scratch:
        work=Path(scratch).resolve()
        if work.parent!=parent:raise ValueError('工作目录校验失败。')
        stage=work/'result';stage.mkdir();source_video=Path(video_path).resolve() if video_path else work/'source.mp4'
        platform='apple' if video_path else 'android';stamp=-1
        if not video_path:stamp=extract_motion_photo(image_path,source_video)
        original=read_movie(source_video)
        cover,exif,identifier,info=open_cover(image_path)
        if platform=='apple':
            if not identifier or not original.identifier or identifier.lower()!=original.identifier.lower():
                raise ValueError('照片与MOV关联标识不一致或缺失；不能仅按文件名配对。')
            meta=[t for k,t in children(original.moov) if k==b'trak' and b'com.apple.quicktime.still-image-time' in t]
            if not meta:raise ValueError('MOV缺少实况封面定时轨道，不能作为有效配对实况导出。')
        check_cancel(cancel)
        if progress:progress('检查原件',0,1,None)
        reports=[];encoded=[]
        for index in range(len(original.videos)):
            target=work/f'beauty-{index}.mov';reports.append(encode_beauty(source_video,target,recipe,cancel,progress,index));encoded.append(target)
        report=dict(reports[0]);report['video_track_reports']=reports
        check_cancel(cancel)
        final_video=stage/('AURA_LIVE.MOV' if platform=='apple' else 'video.mp4')
        report['container']=replace_video(source_video,encoded,final_video)
        for index in range(len(original.videos)):
            if video_pts(source_video,index)!=video_pts(final_video,index):raise ValueError('封装后的视频时间轴发生变化。')
        check_cancel(cancel)
        # Use the same VIDEO model and locked recipe, retaining full cover size.
        engine=VideoBeautifier(recipe)
        try:
            cover_rgb=np.asarray(cover);track=None
            from video_tracks import needed,still
            if needed(recipe):
                track=still(engine,cover_rgb)
            rgb,mask=engine.process(cover_rgb,0,tracked=track)
            cover_body=engine.body.report() if engine.body is not None else {'body_frames':0}
        finally:engine.close()
        final_cover=stage/'AURA_LIVE.JPG';srgb=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.fromarray(rgb).save(final_cover,quality=97,subsampling=0,exif=exif,icc_profile=srgb)
        if platform=='apple' and open_cover(final_cover)[2]!=identifier:raise ValueError('封面关联信息未保留。')
        if platform=='android':
            motion=stage/'AURA_MOTIONMP.JPG';pack_motion_photo(final_cover,final_video,motion,stamp)
            extracted=work/'verify.mp4';verified_stamp=extract_motion_photo(motion,extracted)
            if extracted.read_bytes()!=final_video.read_bytes() or verified_stamp!=stamp:raise ValueError('安卓实况封装校验失败。')
            final_cover.unlink();final_video.unlink() # only owned temporary stage resources
        report.update(platform=platform,cover_face_detected=bool(mask.any()),cover_body=cover_body,cover_size=list(rgb.shape[1::-1]),source_image=str(image_path),source_video=str(source_video) if video_path else 'embedded',
                      output_color='SDR sRGB cover; tagged video',phone_roundtrip_verified=False,
                      warnings=(['未在封面识别人脸，封面不施加面部美颜。'] if not mask.any() else [])+(['主视频未识别人脸，不施加面部美颜。'] if not report['face_frames'] else []),
                      enabled_features=['磨皮','美白','纹理','肤色红润/冷暖','瘦脸/下颌/下巴','眼睛/鼻子/嘴巴','全局基础调色','自动瘦身/瘦腰/瘦腿/拉腿'],
                      limitations=['单人；视频身体形变基于可见衣物/下半身轮廓，不推测被挡住的真实腿型；无可靠范围时不应用，背景仍可能弯曲','身体美肤、AI祛痘、祛纹、手动液化笔画尚未接入','短时插值仅在同镜头内使用；完全遮挡皮肤不涂到遮挡物上，手机相册导入仍需原机验证','输出SDR；安卓统一导出标准JPEG MotionPhoto，不保留厂商私有尾部协议'])
        (stage/'测试报告.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        (stage/'使用说明.txt').write_text('Apple输出为同名JPG与MOV；安卓输入JPEG/HEIC，统一输出标准JPEG MotionPhoto。\n所有视频轨道都处理并核对PTS；原音频和辅助定时数据保持。\n支持单人美肤、肤色、轻度塑形、身体美型与基础调色。无脸帧不施加面部效果，身体姿态不可靠时跳过对应美型。\n瘦腿/拉腿需要可靠完整腿部，拉腿还需要完整脚部和取景余量；背景仍可能弯曲。真实人体运动及手机相册回传仍需验证。\n输出SDR，原件未修改。\n',encoding='utf8')
        check_cancel(cancel);os.rename(stage,output_dir)
        if progress:progress('完成',1,1,None)
        return report

def main():
    import argparse
    p=argparse.ArgumentParser(description='AURA 实况照片美颜测试版')
    p.add_argument('--image',required=True);p.add_argument('--video');p.add_argument('--output',required=True)
    p.add_argument('--smooth',type=float,default=40);p.add_argument('--whiten',type=float,default=25);p.add_argument('--texture',type=float,default=50)
    for name in ('slim','jaw','chin_width','chin_length','eye_size','nose_width','mouth_width','redness','skin_warmth','exposure','contrast','temperature','saturation'):p.add_argument('--'+name.replace('_','-'),type=float,default=0)
    args=p.parse_args();recipe=LiveRecipe(**{k:getattr(args,k) for k in LiveRecipe.__dataclass_fields__ if hasattr(args,k)})
    process_live(args.image,args.video,args.output,recipe,progress=lambda s,n,t,f:print(f'{s} {n}/{t}',flush=True))

if __name__=='__main__':main()
