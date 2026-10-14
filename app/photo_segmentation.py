"""Apache-2.0 MediaPipe segmentation plus geometric feature masks.

This does NOT reproduce a 19-class learned face parser. Eyes, brows and lips
are mesh polygons; uncertain semantic pixels remain excluded. No downloads.
"""
import hashlib, threading
import cv2
import numpy as np
from core import ROOT, FEATURES

MODEL_SHA='c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0'
_lock=threading.RLock()
_segmenter=None

def probabilities(rgb, max_side=1024):
    global _segmenter
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import ImageSegmenter, ImageSegmenterOptions, RunningMode
    if rgb.ndim!=3 or rgb.shape[2]!=3 or min(rgb.shape[:2])<1:raise ValueError('分割输入必须是 RGB 照片。')
    h,w=rgb.shape[:2];scale=min(1,max_side/max(h,w))
    small=cv2.resize(rgb,(max(1,round(w*scale)),max(1,round(h*scale)))) if scale<1 else rgb
    small=np.ascontiguousarray(np.clip(small,0,255),dtype=np.uint8)
    ih,iw=small.shape[:2];pad=(-iw)%4
    if pad:small=cv2.copyMakeBorder(small,0,0,0,pad,cv2.BORDER_REPLICATE)
    with _lock:
        if _segmenter is None:
            data=(ROOT/'models/selfie_multiclass_256x256.tflite').read_bytes()
            if hashlib.sha256(data).hexdigest()!=MODEL_SHA:raise ValueError('分割模型校验失败。')
            _segmenter=ImageSegmenter.create_from_options(ImageSegmenterOptions(
                base_options=BaseOptions(model_asset_buffer=data),running_mode=RunningMode.IMAGE,
                output_category_mask=False,output_confidence_masks=True))
        result=_segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB,data=small))
        masks=[]
        for m in result.confidence_masks:
            if not m.is_contiguous():raise RuntimeError('分割结果缓冲区不连续。')
            masks.append(np.squeeze(m.numpy_view())[:ih,:iw].copy())
    if len(masks)!=6:raise ValueError('分割模型类别数不匹配。')
    values=np.stack(masks,axis=-1).astype(np.float32)
    if not np.isfinite(values).all():raise ValueError('分割模型返回无效数值。')
    return values

def parse_face(rgb,box,points=None):
    a,b,c,d=map(int,box);patch=rgb[b:d,a:c]
    if patch.size==0:raise ValueError('面部区域为空。')
    probs=probabilities(patch,512);category=probs.argmax(-1)
    lookup=np.array([0,17,14,1,16,9],np.uint8)
    labels=lookup[category];labels[probs.max(-1)<.6]=0
    if points is None:
        from core import detect_faces
        faces=detect_faces(patch)
        points=faces[0].points+[a,b] if len(faces)==1 else None
    if points is not None:
        pts=(np.asarray(points)-[a,b])*[labels.shape[1]/(c-a),labels.shape[0]/(d-b)]
        if pts.ndim!=2 or len(pts)<468 or not np.isfinite(pts).all():raise ValueError('面部网格无效。')
        # Semantic support vetoes hair, clothes, accessories and background.
        support=np.isin(labels,[1,14])
        def fill(ids,code):
            mask=np.zeros(labels.shape,np.uint8)
            cv2.fillConvexPoly(mask,cv2.convexHull(np.rint(pts[ids]).astype(np.int32)),1)
            labels[(mask>0)&support]=code
        fill(FEATURES[-1],10)
        fill(FEATURES[2],3);fill(FEATURES[3],2)
        fill(FEATURES[0],5);fill(FEATURES[1],4)
        fill(FEATURES[4],12)
        fill([78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95],11)
    safe=cv2.resize(np.isin(labels,[1,10]).astype(np.uint8),(c-a,d-b),interpolation=cv2.INTER_NEAREST)
    safe=cv2.erode(safe,np.ones((3,3),np.uint8))
    hair=cv2.resize((labels==17).astype(np.uint8),(c-a,d-b),interpolation=cv2.INTER_NEAREST)
    from ai_runtime import RUNTIME
    RUNTIME.mark('皮肤与五官分区','CPU','MediaPipe 多类分割 + 网格区域；细边界可手动修正')
    return safe,hair,labels
