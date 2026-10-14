"""Offline DAMO learned blend layer, keyed to the current edited RGB input.

Cache only 512px predicted maps; apply them to original-resolution FP32 pixels.
No whitening, donor colours, image reconstruction, or uint8 output rounding.
"""
from collections import OrderedDict
from pathlib import Path
import hashlib,threading
import numpy as np
import torch
import torch.nn.functional as F
from core import ROOT
from ai_runtime import GPU_LOCK,RUNTIME,gpu_error

MODEL_HASH='760d0c0b95c4e0a692165677fe2b82dbdf8fbbd4a3780ca966599c627b082993'
ENGINE='DAMO分区域祛纹'
_model=None;_device=None;_gpu_failed=False
_cache=OrderedDict();_lock=threading.RLock();BUDGET=64*1024**2
_inferences=0;_hits=0

def _load(device):
    global _model,_device
    if _model is None:
        path=ROOT/'models/damo_blend.pth'
        if not path.is_file():raise FileNotFoundError('缺少本地 DAMO 祛纹匀肤模型：'+str(path))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=MODEL_HASH:raise ValueError('DAMO祛纹匀肤模型校验失败。')
        from vendor.damo.unet_deploy import UNet
        network=UNet(3,3,init_weights=False)
        weights=torch.load(path,map_location='cpu',weights_only=True)
        network.load_state_dict(weights['generator'],strict=True)
        _model=network.eval();_device='cpu'
    if _device!=device:
        _model.to(device=device,dtype=torch.float32);_device=device
    return _model

def cache_info():
    with _lock:return dict(entries=len(_cache),bytes=sum(v.nbytes for v in _cache.values()),inferences=_inferences,hits=_hits)

def clear_cache():
    with _lock:_cache.clear()

def _predict(small):
    global _gpu_failed,_inferences,_device
    key=(MODEL_HASH,hashlib.blake2b(small.numpy().tobytes(),digest_size=20).hexdigest())
    with _lock:
        if key in _cache:
            global _hits
            _hits+=1;result=_cache.pop(key);_cache[key]=result;return result
    with GPU_LOCK:
        # Two renderer requests can arrive while the previous map is computing.
        with _lock:
            if key in _cache:_hits+=1;return _cache[key]
        device='cpu' if _gpu_failed else RUNTIME.device()
        def run(target):
            model=_load(target)
            with torch.inference_mode():return model(small.to(target))[0].permute(1,2,0).cpu().numpy().copy()
        try:result=run(device);RUNTIME.mark(ENGINE,'CUDA' if device=='cuda' else 'CPU')
        except RuntimeError as error:
            if device!='cuda' or not gpu_error(error):raise
            _gpu_failed=True
            if _model is not None:_model.to('cpu');_device='cpu'
            torch.cuda.empty_cache();result=run('cpu');RUNTIME.mark(ENGINE,'CPU','GPU匀肤失败，已重试CPU：'+str(error))
        if not np.isfinite(result).all():raise ValueError('DAMO祛纹模型返回无效混合图层。')
        result=np.clip(result,0,1).astype(np.float32);result.flags.writeable=False
        with _lock:
            _inferences+=1;_cache[key]=result
            while sum(v.nbytes for v in _cache.values())>BUDGET:_cache.popitem(last=False)
    return result

def blend_map(rgb):
    """Current float RGB255 crop -> native-sized neutral-0.5 blend map."""
    source=np.asarray(rgb,dtype=np.float32)
    if source.ndim!=3 or source.shape[2]!=3 or not np.isfinite(source).all():raise ValueError('DAMO祛纹输入图像无效。')
    tensor=torch.from_numpy(np.ascontiguousarray(source.transpose(2,0,1)))[None]/127.5-1
    small=F.interpolate(tensor,(512,512),mode='bilinear',align_corners=False)
    predicted=_predict(small)
    field=F.interpolate(torch.from_numpy(predicted.copy().transpose(2,0,1))[None],source.shape[:2],mode='bilinear',align_corners=False)[0].permute(1,2,0).numpy()
    # Match the reviewed upstream 500px/20px diffuse border, without Python loops.
    coordinates=np.arange(500,dtype=np.float32)
    edge=np.minimum(np.where(coordinates<=20,coordinates/20,1),np.where(coordinates>480,(500-coordinates)/20,1))
    mask=np.minimum(edge[:,None],edge[None,:]).clip(0,1)
    fade=F.interpolate(torch.from_numpy(mask)[None,None],source.shape[:2],mode='bilinear',align_corners=False)[0,0].numpy()
    return ((field-.5)*fade[:,:,None]+.5).astype(np.float32)

def compose(source,field,opacity):
    """Upstream learned blend formula, with protected spatial opacity and FP32."""
    source=np.asarray(source,dtype=np.float32);opacity=np.clip(opacity,0,1).astype(np.float32)
    if field.shape!=source.shape or opacity.shape!=source.shape[:2]:raise ValueError('DAMO祛纹图层范围不一致。')
    result=source.copy();active=opacity>0
    if not active.any():return result
    normal=np.clip(source/255,0,1)
    delta=(2*field-1)*normal*(1-normal)*255
    result[active]=np.clip(source+delta*opacity[:,:,None],0,255)[active]
    return result
