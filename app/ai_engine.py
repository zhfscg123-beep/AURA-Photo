"""Local trained acne detection, skin parsing and selected-mask neural inpainting.

Model source/provenance/licenses/hashes are recorded in models-manifest.json.
No networking, remote-code execution, PyTorch pickle loading or cloud calls.
"""
from pathlib import Path
import hashlib, ast, threading
import numpy as np
import cv2
import onnxruntime as ort
from core import ROOT, Session
from ai_runtime import AcceleratedSession,RUNTIME

HASHES={
 'lama_fp32.onnx':'1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6',
}

class Models:
    def __init__(self):self.sessions={}; self.lock=threading.Lock()
    def get(self,name):
        with self.lock:
            if name not in self.sessions:
                path=ROOT/'models'/name
                if not path.exists():raise FileNotFoundError('缺少本地 AI 模型：'+name)
                if hashlib.sha256(path.read_bytes()).hexdigest()!=HASHES[name]:raise ValueError('模型文件校验失败：'+name)
                engine={'lama_fp32.onnx':'背景补全'}[name]
                self.sessions[name]=AcceleratedSession(path,engine)
            return self.sessions[name]

MODELS=Models()

def square_box(box,shape,multiplier=1.55):
    a,b,c,d=box; side=max(c-a,d-b)*multiplier; cx,cy=(a+c)/2,(b+d)/2
    h,w=shape[:2]
    return max(0,int(cx-side/2)),max(0,int(cy-side/2)),min(w,int(cx+side/2)),min(h,int(cy+side/2))

def parse_skin(rgb,box,model=None,points=None):
    from photo_segmentation import parse_face
    return parse_face(rgb,box,points)


class AISession(Session):
    def __init__(self,rgb,confidence=.18,progress=None):
        super().__init__(rgb,auto_scan=False,cache_smoothing=False)
        self.raw_detections=[]; self.rejected=[]; self.semantic_skin=[]; self.hair=[]
        self.confidence=confidence; self.ai_auto_mask=np.zeros(rgb.shape[:2],np.uint8)
        self.scan_ai(confidence,progress)
    def scan_ai(self,confidence=.35,progress=None):
        raise NotImplementedError('请使用 PortraitAISession 的 DAMO 检测实现。')
    def update_auto_mask(self):
        mask=np.zeros(self.original.shape[:2],np.uint8)
        for spot in self.spots:
            if not spot['enabled']:continue
            f=self.faces[spot['face']]; a,b,c,d=f.box; local=np.zeros(f.mask.shape,np.uint8)
            x,y,w,h=spot['box']; centre=(round(x+w/2)-a,round(y+h/2)-b)
            cv2.ellipse(local,centre,(max(2,round(w*.56)),max(2,round(h*.56))),0,0,360,255,-1)
            local[f.mask<.75]=0
            mask[b:d,a:c]|=local
        self.ai_auto_mask=mask
        return mask
    def render_smooth(self,strength=0):
        # Bypass the former color-rule/Telea repair path entirely.
        return super().render(strength,0)

def inpaint_selected(rgb,mask,progress=None,cancel=None,precision=False):
    """512px tiles with overlapping context; only selected pixels are composited."""
    if mask.shape!=rgb.shape[:2]:raise ValueError('修复选区尺寸不匹配。')
    selected=(mask>0).astype(np.uint8)
    if not np.any(selected):return rgb.copy(),{'tiles':0,'changed_pixels':0,'model':'LaMa ONNX'}
    h,w=selected.shape
    # 320px target cores with 96px context each side. Native pixels aren't resized.
    tiles=[]
    for y in range(0,h,320):
        for x in range(0,w,320):
            if np.any(selected[y:min(h,y+320),x:min(w,x+320)]):tiles.append((x,y))
    if len(tiles)>96:raise ValueError('选区过大，请分批修复；每批最多96个局部区域。')
    session=MODELS.get('lama_fp32.onnx'); output=rgb.astype(np.float32).copy() if precision else rgb.copy()
    for n,(x,y) in enumerate(tiles):
        if cancel and cancel.is_set():raise RuntimeError('已取消 AI 修复；照片未改变。')
        if progress:progress(f'AI 局部修复 {n+1}/{len(tiles)}…')
        # Center on the selected core; reflect pad provides edge image context.
        xa,ya=x-96,y-96; xb,yb=xa+512,ya+512
        l,t,r,b=max(0,-xa),max(0,-ya),max(0,xb-w),max(0,yb-h)
        crop=rgb[max(0,ya):min(h,yb),max(0,xa):min(w,xb)]
        cm=selected[max(0,ya):min(h,yb),max(0,xa):min(w,xb)]
        image=cv2.copyMakeBorder(crop,t,b,l,r,cv2.BORDER_REFLECT_101)
        pm=cv2.copyMakeBorder(cm,t,b,l,r,cv2.BORDER_CONSTANT,value=0)
        feeds={'image':(image.astype(np.float32)/255).transpose(2,0,1)[None].copy(),'mask':pm.astype(np.float32)[None,None]}
        prediction=session.run(None,feeds)[0][0].transpose(1,2,0)
        if not np.all(np.isfinite(prediction)):raise ValueError('AI 模型返回非有限像素，未应用修复。')
        # Carve's exported graph already returns RGB in [0,255], although input
        # is [0,1]. Multiplying again creates white seams in completed regions.
        prediction=np.clip(prediction,0,255).astype(np.float32) if precision else np.clip(np.rint(prediction),0,255).astype(np.uint8)
        x1,y1=min(x+320,w),min(y+320,h)
        target=output[y:y1,x:x1]; generated=prediction[96:96+y1-y,96:96+x1-x]
        region=selected[y:y1,x:x1]>0; target[region]=generated[region]
    return output,{'tiles':len(tiles),'changed_pixels':int(np.count_nonzero(np.any(output!=rgb,axis=2))),'model':'LaMa ONNX','device':'CUDA + CPU' if 'CUDAExecutionProvider' in session.get_providers() else 'CPU'}

def blend_repair(original,smoothed,generated,mask,strength=100):
    if generated is None:return smoothed.copy()
    binary=(mask>0).astype(np.uint8)
    alpha=np.clip(cv2.distanceTransform(binary,cv2.DIST_L2,5)/1.5,0,1)*np.clip(strength,0,100)/100
    # Both neural modification and feather are strictly inside the accepted mask.
    difference=generated.astype(np.float32)-original.astype(np.float32)
    return np.clip(np.rint(smoothed.astype(np.float32)+difference*alpha[:,:,None]),0,255).astype(np.uint8)
