"""Portrait-specific neural blemish detector and repair network from DAMO.

No ModelScope pipeline/network access or TensorFlow dependency is used.
Normalization, 768px detection and mask polarity follow the official pipeline.
"""
import hashlib,threading
import numpy as np
import cv2
import torch
import torch.nn.functional as F
from core import ROOT
from ai_engine import AISession,square_box
from ai_runtime import run_torch,RUNTIME
from vendor.damo.detection_model.detection_unet_in import DetectionUNet
from vendor.damo.inpainting_model.inpainting_unet import RetouchingNet

MODEL_HASH='c9e1388b19d9334c90db08308c86de208f535920ee381ae8a9cb63484a78351a'
LOCK=threading.RLock(); NETWORKS=None;NETWORK_DEVICE=None

def networks(device='cpu'):
    global NETWORKS,NETWORK_DEVICE
    with LOCK:
        if NETWORKS is None:
            path=ROOT/'models/damo_local.pth'
            if hashlib.sha256(path.read_bytes()).hexdigest()!=MODEL_HASH:raise ValueError('DAMO模型校验失败。')
            torch.set_num_threads(4)
            checkpoint=torch.load(path,map_location='cpu',weights_only=True)
            detector=DetectionUNet(3,1,init_weights=False).eval()
            repair=RetouchingNet(4,3,init_weights=False)
            repair.eval()  # Upstream train() override returns None.
            detector.load_state_dict(checkpoint['detection_net']); repair.load_state_dict(checkpoint['inpainting_net'])
            NETWORKS=detector,repair
            NETWORK_DEVICE='cpu'
        if NETWORK_DEVICE!=device:
            try:
                NETWORKS=tuple(model.to(device=device,dtype=torch.float32) for model in NETWORKS);NETWORK_DEVICE=device
            except RuntimeError:
                for model in NETWORKS:model.to('cpu')
                NETWORK_DEVICE='cpu';raise
        return NETWORKS

def release_gpu_networks():
    global NETWORK_DEVICE
    with LOCK:
        if NETWORKS:
            for model in NETWORKS:model.to('cpu')
        NETWORK_DEVICE='cpu'

def detection_tiles(shape,retouch_engine=1):
    height,width=shape[:2]
    if retouch_engine==1 or max(height,width)<900:return []
    edge=min(1024,max(512,round(max(height,width)*.6)));step=max(1,round(edge*.7))
    def positions(length):
        last=max(0,length-edge);values=list(range(0,max(1,last+1),step))
        if values[-1]!=last:values.append(last)
        # Keep both image edges when limiting inference cost on large faces.
        if len(values)>4:values=[values[i] for i in np.linspace(0,len(values)-1,4).round().astype(int)]
        return values
    return [(x,y,min(width,x+edge),min(height,y+edge)) for y in positions(height) for x in positions(width)]

def detection_probability(rgb,box,retouch_engine=1):
    a,b,c,d=box; patch=rgb[b:d,a:c]
    def inference(device):
        detector,_=networks(device)
        image=torch.from_numpy(patch.transpose(2,0,1).copy()).to(device=device,dtype=torch.float32)[None]/127.5-1
        with torch.inference_mode():
            resized=F.interpolate(image,(768,768),mode='bilinear',align_corners=True)
            probability=torch.sigmoid(detector(resized))
            restored=F.interpolate(probability,(d-b,c-a),mode='bilinear',align_corners=False)
        base=restored[0,0].cpu().numpy()
        tiles=detection_tiles(patch.shape,retouch_engine)
        if not tiles:return base
        sums=np.zeros_like(base);weights=np.zeros_like(base)
        for x,y,z,t in tiles:
            tile=image[:,:,y:t,x:z];th,tw=tile.shape[2:]
            with torch.inference_mode():
                prob=torch.sigmoid(detector(F.interpolate(tile,(768,768),mode='bilinear',align_corners=True)))
                prob=F.interpolate(prob,(th,tw),mode='bilinear',align_corners=False)[0,0].cpu().numpy()
            yy=np.minimum(np.arange(th)+1,th-np.arange(th))/max(1,th*.12)
            xx=np.minimum(np.arange(tw)+1,tw-np.arange(tw))/max(1,tw*.12)
            weight=np.minimum(yy,1)[:,None]*np.minimum(xx,1)[None,:]
            sums[y:t,x:z]+=prob*weight;weights[y:t,x:z]+=weight
        local=sums/np.maximum(weights,1e-6)
        return np.maximum(base,.55*base+.45*local).astype(np.float32)
    return run_torch(inference)

class PortraitAISession(AISession):
    def __init__(self,rgb,confidence=.35,progress=None,retouch_engine=2,protect_dark_points=False):
        if type(retouch_engine) is not int or retouch_engine not in (1,2):raise ValueError('皮肤引擎版本无效。')
        if type(protect_dark_points) is not bool:raise ValueError('深色点保护开关无效。')
        self.protect_dark_points=protect_dark_points
        self.retouch_engine=retouch_engine;self.detail_protection=[]
        self.probabilities=[]
        self.repair_safe=[]; self.component_masks=[]
        self.part_regions=[];self.part_labels=[];self.nostrils=[];self.body_region=None;self.body_owner=None;self.body_assignment={}
        self.parse_contexts={};self.parts_revision=17
        self.parser_model='mediapipe-multiclass-mesh'
        super().__init__(rgb,confidence,progress)
    def scan_ai(self,confidence=.35,progress=None):
        # DAMO is the production detector; common parsing utilities are retained.
        from ai_engine import parse_skin
        if not self.semantic_skin:
            for fi,f in enumerate(self.faces):
                if progress:progress('AI 正在分割皮肤、头发和五官…')
                context=square_box(f.box,self.original.shape)
                skin,hair,labels=parse_skin(self.original,context,self.parser_model,points=f.points)
                self.parse_contexts[fi]=(context,labels)
                from region_masks import face_parts
                parts,hair,nostrils,local_labels=face_parts(self.original,f,context,labels)
                skin=parts['skin'];self.part_regions.append(parts);self.part_labels.append(local_labels);self.nostrils.append(nostrils)
                self.semantic_skin.append(skin);self.hair.append(hair)
                safe=(skin>0)&(f.protected==0)&(f.mask>.5)
                self.repair_safe.append(safe)
        if self.retouch_engine==2 and not self.detail_protection:
            from skin_detail_protection import build
            self.detail_protection=[build(self,i) for i in range(len(self.faces))]
        if self.retouch_engine==2:
            for guard in self.detail_protection:
                guard['automatic']=~guard['features']&(~guard['marks'] if self.protect_dark_points else True)
            self.repair_safe=[(skin>0)&(f.protected==0)&(f.mask>.5)&guard['automatic']
                              for f,skin,guard in zip(self.faces,self.semantic_skin,self.detail_protection)]
            self.detail_candidates={}
        if not self.probabilities:
            for f in self.faces:
                if progress:progress('人像美肤模型正在检测痘点与局部瑕疵…')
                context=square_box(f.box,self.original.shape,1.08)
                prob=detection_probability(self.original,context,self.retouch_engine)
                a,b,c,d=f.box;x,y,_,_=context
                self.probabilities.append(prob[b-y:d-y,a-x:c-x])
        self.confidence=confidence;self.spots=[];self.raw_detections=[];self.rejected=[]
        self.ai_auto_mask=np.zeros(self.original.shape[:2],np.uint8)
        self.component_masks=[]
        for fi,(f,prob) in enumerate(zip(self.faces,self.probabilities)):
            a,b,c,d=f.box
            binary=((prob>=confidence)&self.repair_safe[fi]).astype(np.uint8)
            count,labels,stats,centres=cv2.connectedComponentsWithStats(binary,8)
            for idx in range(1,count):
                x,y,w,h,area=stats[idx]; cx,cy=centres[idx]
                score=float(prob[labels==idx].max())
                det={'box':[float(x+a),float(y+b),float(w),float(h)],'confidence':score,'face':fi}
                self.raw_detections.append(det)
                if area<1 or area>max(50,f.width*f.width*.015) or max(w,h)>f.width*.18:
                    self.rejected.append(dict(det,reason='region too large for a point blemish'));continue
                self.spots.append(dict(x=round(cx+a),y=round(cy+b),r=max(2,round(max(w,h)/2)),box=det['box'],confidence=score,face=fi,enabled=True,manual=False))
                component=(labels==idx).astype(np.uint8)
                component=cv2.dilate(component,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)))
                component[~self.repair_safe[fi]]=0
                self.component_masks.append(component)
            # Generate accepted masks with a small dilation to cover a blemish edge.
        self.update_auto_mask()
        return self.spots

    def update_auto_mask(self):
        mask=np.zeros(self.original.shape[:2],np.uint8)
        for spot,component in zip(self.spots,self.component_masks):
            if not spot['enabled']:continue
            a,b,c,d=self.faces[spot['face']].box
            mask[b:d,a:c]|=component*255
        self.ai_auto_mask=mask
        return mask

def inpaint_portrait(rgb,mask,progress=None,cancel=None,precision=False,retouch_engine=2):
    if type(retouch_engine) is not int or retouch_engine not in (1,2):raise ValueError('皮肤引擎版本无效。')
    if retouch_engine==1:return _inpaint_legacy(rgb,mask,progress,cancel,precision)
    if mask.shape!=rgb.shape[:2]:raise ValueError('选区与照片尺寸不匹配。')
    from portrait_patch_blend import repair
    def predict(patch,matte):
        def inference(device):
            _,network=networks(device)
            image=torch.from_numpy(patch.transpose(2,0,1).copy()).to(device=device,dtype=torch.float32)[None]/127.5-1
            keep=torch.from_numpy((1-matte).astype(np.float32)).to(device)[None,None]
            with torch.inference_mode():prediction=network(image*keep,keep)
            if not torch.isfinite(prediction).all():raise ValueError('AI 输出像素无效，未应用结果。')
            return prediction[0].permute(1,2,0).cpu().numpy()
        return np.clip((run_torch(inference)+1)*127.5,0,255)
    result,info=repair(rgb,mask,predict,progress,cancel,precision)
    info.update(model='DAMO portrait repair',retouch_engine=2,device=RUNTIME.used.get('祛痘检测/修复','CPU'))
    return result,info

def _inpaint_legacy(rgb,mask,progress=None,cancel=None,precision=False):
    # Use dedicated skin repair; leave LaMa available as a comparison/fallback engine.
    if mask.shape!=rgb.shape[:2]:raise ValueError('选区与照片尺寸不匹配。')
    selected=(mask>0).astype(np.uint8); h,w=selected.shape
    if not np.any(selected):return rgb.astype(np.float32) if precision else rgb.copy(),{'tiles':0,'model':'DAMO portrait repair','changed_pixels':0}
    tiles=[(x,y) for y in range(0,h,448) for x in range(0,w,448) if np.any(selected[y:min(h,y+448),x:min(w,x+448)])]
    if len(tiles)>96:raise ValueError('选区过大，请分批修复。')
    out=rgb.astype(np.float32) if precision else rgb.copy()
    for n,(x,y) in enumerate(tiles):
        if cancel and cancel.is_set():raise RuntimeError('已取消，未应用修复。')
        if progress:progress(f'AI 皮肤修复 {n+1}/{len(tiles)}…')
        xa,ya=x-32,y-32;xb,yb=xa+512,ya+512
        left,top,right,bottom=max(0,-xa),max(0,-ya),max(0,xb-w),max(0,yb-h)
        patch=cv2.copyMakeBorder(rgb[max(0,ya):min(h,yb),max(0,xa):min(w,xb)],top,bottom,left,right,cv2.BORDER_REFLECT_101)
        pm=cv2.copyMakeBorder(selected[max(0,ya):min(h,yb),max(0,xa):min(w,xb)],top,bottom,left,right,cv2.BORDER_CONSTANT,value=0)
        def inference(device):
            _,repair=networks(device)
            image=torch.from_numpy(patch.transpose(2,0,1).copy()).to(device=device,dtype=torch.float32)[None]/127.5-1
            keep=torch.from_numpy((1-pm).astype(np.float32)).to(device)[None,None]
            with torch.inference_mode():prediction=repair(image*keep,keep)
            if not torch.isfinite(prediction).all():raise ValueError('AI 输出像素无效，未应用结果。')
            return prediction[0].permute(1,2,0).cpu().numpy()
        generated=np.clip((run_torch(inference)+1)*127.5,0,255)
        if not precision:generated=np.rint(generated).astype(np.uint8)
        x1,y1=min(x+448,w),min(y+448,h)
        target=out[y:y1,x:x1]; region=selected[y:y1,x:x1]>0
        target[region]=generated[32:32+y1-y,32:32+x1-x][region]
    return out,{'tiles':len(tiles),'changed_pixels':int(np.count_nonzero(np.any(out!=rgb,axis=2))),'model':'DAMO portrait repair','device':RUNTIME.used.get('祛痘检测/修复','CPU')}
