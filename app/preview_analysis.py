"""Resident IMAGE detectors for arbitrary seek and short preview segments."""
import hashlib,cv2,numpy as np
from core import ROOT,MODEL,face_mask
from person_masks import POSE_HASH,match_faces
from video_tracks import silhouette,finish

class PreviewAnalyzer:
    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import FaceLandmarker,FaceLandmarkerOptions,PoseLandmarker,PoseLandmarkerOptions,RunningMode
        data=(ROOT/'models/pose_landmarker_full.task').read_bytes()
        if hashlib.sha256(data).hexdigest()!=POSE_HASH:raise ValueError('人体定位模型校验失败。')
        self.mp=mp
        self.pose=PoseLandmarker.create_from_options(PoseLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=data),running_mode=RunningMode.IMAGE,num_poses=2,min_pose_detection_confidence=.55,min_pose_presence_confidence=.65,output_segmentation_masks=True))
        try:self.face=FaceLandmarker.create_from_options(FaceLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=MODEL.read_bytes()),running_mode=RunningMode.IMAGE,num_faces=1,min_face_detection_confidence=.5,min_face_presence_confidence=.5))
        except Exception:self.pose.close();raise
        self.calls=0
    def close(self):self.face.close();self.pose.close()
    def image(self,rgb):return self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=np.ascontiguousarray(rgb))
    def analyze(self,rgb,timestamp,shot=0):
        self.calls+=1;h,w=rgb.shape[:2];scale=min(1,960/max(h,w));iw,ih=round(w*scale),round(h*scale)
        small=cv2.resize(rgb,(iw,ih)) if scale<1 else rgb;pad=(-iw)%4
        pose_rgb=cv2.copyMakeBorder(small,0,0,0,pad,cv2.BORDER_REPLICATE) if pad else small
        result=self.pose.detect(self.image(pose_rgb));p=None;profile=None
        if len(result.pose_landmarks)==1 and result.segmentation_masks:
            p=np.array([[q.x*(iw+pad)*w/iw,q.y*h,q.visibility,q.presence] for q in result.pose_landmarks[0]],np.float32)
            mask=result.segmentation_masks[0]
            if not mask.is_contiguous():raise RuntimeError('人体范围缓冲区不兼容。')
            mask=np.squeeze(mask.numpy_view()).copy().astype(np.float32)[:ih,:iw];profile=silhouette(p,mask,(h,w))
        face=self.face.detect(self.image(small));points=None;kind='missing'
        if face.face_landmarks:
            points=np.array([[q.x,q.y] for q in face.face_landmarks[0]],np.float32);kind='video'
        if points is None and p is not None:
            xy=p[:11,:2];good=np.min(p[:11,2:],axis=1)>.65
            if good.sum()>=5:
                xy=xy[good];center=(xy.min(0)+xy.max(0))/2
                width=max(np.linalg.norm(p[11,:2]-p[12,:2])*.65,np.ptp(xy[:,0])*1.9,np.ptp(xy[:,1])*2.4,48.)
                for factor in (1.,1.4):
                    a,b=np.maximum(np.floor(center-width*factor/2).astype(int),[0,0]);c,d=np.minimum(np.ceil(center+width*factor/2).astype(int),[w,h])
                    if min(c-a,d-b)<20:continue
                    face=self.face.detect(self.image(rgb[b:d,a:c]))
                    if not face.face_landmarks:continue
                    candidate=np.array([[(q.x*(c-a)+a)/w,(q.y*(d-b)+b)/h] for q in face.face_landmarks[0]],np.float32)
                    if match_faces([face_mask(candidate,rgb.shape)],[p])[0]:points=candidate;kind='image_retry';break
        return {'shot':shot,'time':float(timestamp),'face':points,'face_kind':kind,'pose':p,'profile':profile,'profile_kind':'measured'}
    def segment(self,frames,times,cancel,progress):
        rows=[];prev=None;shot=-1
        for i,(rgb,t) in enumerate(zip(frames,times)):
            if cancel.is_set():raise InterruptedError('预览准备已取消。')
            sample=cv2.resize(rgb,(96,170)).astype(float)
            if prev is None or np.mean(np.abs(sample-prev))>30:shot+=1
            prev=sample;rows.append(self.analyze(rgb,t,shot))
            if progress:progress('准备当前片段轨迹',i+1,len(frames))
        return finish(rows,frames[0].shape[:2])[0]
