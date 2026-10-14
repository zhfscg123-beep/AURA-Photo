"""Offline learned person/sky masks and their background complement."""
import time,threading
import numpy as np
import torch
from torch.nn import functional as F
from ai_runtime import RUNTIME,GPU_LOCK,gpu_error
from ai_scene_models import SkyNetwork

MAX_ALPHA_SIDE=1600
_MODELS={}

def refine_person(image,probability,model):
    """Increase detail for a small person using a contextual second crop."""
    points=(probability[0,0]>.6).nonzero()
    if len(points)<16:return probability,False
    low=points.min(0).values;high=points.max(0).values+1;ph,pw=probability.shape[-2:]
    y0,x0=map(int,low.tolist());y1,x1=map(int,high.tolist())
    if (y1-y0)*(x1-x0)>.55*ph*pw:return probability,False
    h,w=image.shape[-2:];padding=max(y1-y0,x1-x0)*.18
    a=max(0,int((x0-padding)*w/pw));b=max(0,int((y0-padding)*h/ph))
    c=min(w,int((x1+padding)*w/pw+1));d=min(h,int((y1+padding)*h/ph+1))
    if c-a<16 or d-b<16:return probability,False
    patch=image[:,:,b:d,a:c];ratio=min(520/min(d-b,c-a),1152/max(d-b,c-a))
    size=(max(32,round((d-b)*ratio)),max(32,round((c-a)*ratio)))
    mean=image.new_tensor([.485,.456,.406]).reshape(1,3,1,1);std=image.new_tensor([.229,.224,.225]).reshape(1,3,1,1)
    fine=model((F.interpolate(patch,size,mode='bilinear',align_corners=False)-mean)/std)
    # Work at the bounded matte resolution; avoid a native float mask cache.
    scale=min(1,MAX_ALPHA_SIDE/max(h,w));target=(max(1,round(h*scale)),max(1,round(w*scale)))
    full=F.interpolate(probability,target,mode='bilinear',align_corners=False)
    left,top=round(a*target[1]/w),round(b*target[0]/h);right,bottom=round(c*target[1]/w),round(d*target[0]/h)
    value=F.interpolate(fine,(bottom-top,right-left),mode='bilinear',align_corners=False)
    yy=torch.linspace(0,1,bottom-top,device=image.device)[None,None,:,None];xx=torch.linspace(0,1,right-left,device=image.device)[None,None,None,:]
    blend=ramp(torch.minimum(torch.minimum(xx,1-xx),torch.minimum(yy,1-yy))/.08)
    view=full[:,:,top:bottom,left:right];view.copy_(view+(value-view)*blend)
    return full,True

def guided(alpha,guide,radius=4):
    def mean(x):return F.avg_pool2d(x,2*radius+1,stride=1,padding=radius,count_include_pad=False)
    g=mean(guide);p=mean(alpha);variance=mean(guide*guide)-g*g
    a=(mean(guide*alpha)-g*p)/(variance+.001);b=p-a*g
    return (mean(a)*guide+mean(b)).clamp(0,1)

def ramp(x):
    x=x.clamp(0,1);return x*x*(3-2*x)

def refine_boundary(image,probability):
    """Use nearby foreground/background colors only in the silhouette band.

    Semantic confidence alone can include bright sky beside a hand or hat.
    Interior/exterior seeds anchor a local RGB mixture; low-contrast regions
    without trustworthy seeds retain the semantic result. All work stays on
    the inference device and the bounded alpha canvas.
    """
    side=max(probability.shape[-2:]);edge=max(2,min(5,round(3*side/1080)));radius=max(6,min(12,round(8*side/1080)))
    binary=(probability>.5).float()
    foreground_seed=-F.max_pool2d(-binary,edge*2+1,1,edge)
    background_seed=(1-F.max_pool2d(binary,edge*2+1,1,edge))*(probability<.02).float()
    # A single foreground mean mixes black hair with pale fingers and can
    # incorrectly remove the fingers. Match individual local seed colors.
    band=(foreground_seed==0)&(background_seed==0)
    points=band[0,0].nonzero();result=probability.clone()
    if not len(points):return result
    height,width=probability.shape[-2:];pixels=image[0].permute(1,2,0)
    yy,xx=torch.meshgrid(torch.arange(-radius,radius+1,device=image.device),torch.arange(-radius,radius+1,device=image.device),indexing='ij')
    offsets=torch.stack((yy.flatten(),xx.flatten()),1)
    spatial=(offsets.float()**2).sum(1)*1e-5
    fg,bg=foreground_seed[0,0],background_seed[0,0]
    # Sparse bounded batches keep native/large photos from allocating a full
    # H x W x neighborhood color tensor on either CUDA or CPU.
    for start in range(0,len(points),4096):
        p=points[start:start+4096];neighbors=p[:,None,:]+offsets[None,:,:]
        inside=(neighbors[:,:,0]>=0)&(neighbors[:,:,0]<height)&(neighbors[:,:,1]>=0)&(neighbors[:,:,1]<width)
        y=neighbors[:,:,0].clamp(0,height-1);x=neighbors[:,:,1].clamp(0,width-1)
        colors=pixels[y,x];current=pixels[p[:,0],p[:,1]]
        score=((colors-current[:,None,:])**2).sum(2)+spatial[None,:]
        fs,fi=score.masked_fill(~(inside&(fg[y,x]>0)),float('inf')).min(1)
        bs,bi=score.masked_fill(~(inside&(bg[y,x]>0)),float('inf')).min(1)
        rows=torch.arange(len(p),device=image.device)
        foreground=colors[rows,fi];background=colors[rows,bi]
        delta=foreground-background;distance=(delta*delta).sum(1)
        matte=(((current-background)*delta).sum(1)/distance.clamp_min(1e-6)).clamp(0,1)
        residual=((current-(background+matte[:,None]*delta))**2).sum(1)
        valid=torch.isfinite(fs)&torch.isfinite(bs)&(distance>.004)&(residual<.01)
        old=probability[0,0,p[:,0],p[:,1]];confidence=ramp((distance-.004)/.026)
        result[0,0,p[:,0],p[:,1]]=torch.where(valid,old+(matte-old)*confidence,old)
    return result.clamp(0,1)

def generate(rgb,progress=lambda text:None,cancel=None):
    start=time.monotonic();h,w=rgb.shape[:2]
    if rgb.ndim!=3 or rgb.shape[2]!=3 or not np.isfinite(rgb).all():raise ValueError('AI 分区照片格式无效。')
    source=np.clip(rgb,0,255).astype(np.uint8)
    def cancelled():
        if cancel is not None and cancel.is_set():raise RuntimeError('已取消 AI 分区，保留原有蒙版。')
    def run(device):
        progress('AI 正在识别人物与天空 · '+('GPU' if device=='cuda' else 'CPU'));cancelled()
        if device not in _MODELS:_MODELS[device]=SkyNetwork().eval().to(device)
        sky_model=_MODELS[device]
        with torch.inference_mode():
            image=torch.from_numpy(source).to(device=device,dtype=torch.float32).permute(2,0,1)[None]/255
            mean=torch.tensor([.485,.456,.406],device=device).reshape(1,3,1,1);std=torch.tensor([.229,.224,.225],device=device).reshape(1,3,1,1)
            sky=sky_model((F.interpolate(image,(384,384),mode='bilinear',align_corners=False)-mean)/std);cancelled()
            from photo_segmentation import probabilities
            scores=probabilities(source)
            alpha=np.clip(1-scores[:,:,0],0,1)
            person=torch.from_numpy(alpha.copy()).to(device)[None,None]
            refined=False;cancelled()
            scale=min(1,MAX_ALPHA_SIDE/max(h,w));size=(max(1,round(h*scale)),max(1,round(w*scale)))
            bounded_image=F.interpolate(image,size,mode='bilinear',align_corners=False)
            guide=(bounded_image*torch.tensor([.2126,.7152,.0722],device=device).reshape(1,3,1,1)).sum(1,keepdim=True)
            person=guided(F.interpolate(person,size,mode='bilinear',align_corners=False),guide)
            sky=guided(F.interpolate(sky,size,mode='bilinear',align_corners=False),guide)
            person=refine_boundary(bounded_image,ramp((person-.10)/.80));cancelled()
            sky=ramp((sky-.08)/.84)*(1-person)
            if float(person.max())<.55:person.zero_()
            if float(sky.max())<.55:sky.zero_()
            background=(1-person-sky).clamp(0,1);cancelled()
            result={key:torch.round(value[0,0]*255).to(torch.uint8).cpu().numpy().copy() for key,value in [('person',person),('sky',sky),('background',background)]}
        return result,refined
    with GPU_LOCK:
        device=RUNTIME.device();reason=None
        try:result,refined=run(device)
        except RuntimeError as error:
            if device!='cuda' or not gpu_error(error):raise
            _MODELS.pop('cuda',None);torch.cuda.empty_cache();reason='GPU 分区失败，已使用 CPU：'+str(error).splitlines()[0][:160];device='cpu';result,refined=run(device)
        RUNTIME.mark('人物/天空分区蒙版','CUDA' if device=='cuda' else 'CPU',reason)
    return result,dict(backend='CUDA' if device=='cuda' else 'CPU',fallback_reason=reason,seconds=round(time.monotonic()-start,3),person_crop_refinement=refined,person_color_boundary_refinement=True,alpha_shape=list(next(iter(result.values())).shape),coverage={key:round(float(value.mean()/255),5) for key,value in result.items()},models=['sky-U2Net-small','MediaPipe-selfie-multiclass','person-edge-refinement-v1','person-color-boundary-v2'])
