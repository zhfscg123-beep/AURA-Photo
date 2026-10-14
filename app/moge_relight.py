"""Pinned offline MoGe-2 Small geometry, consistency protection and CPU fallback."""
import sys,json,hashlib
import numpy as np,torch
from ai_runtime import ROOT,RUNTIME,GPU_LOCK,gpu_error
MODEL_SHA256='79a16621928c2bf0ed04659218c55c01075e950507f40bb3332fb4c873d3e1dc'
CACHE_ID=('moge-2-small-normal',MODEL_SHA256,2)
_models={};_checked=False;_failed_gpu=False

def dependencies():
    for folder in (ROOT/'vendor',ROOT/'moge-deps'):
        if not folder.is_dir():raise RuntimeError('缺少 MoGe-2 Small 补光组件，请使用完整安装包。')
        if str(folder) not in sys.path:sys.path.insert(0,str(folder))

def verify():
    global _checked
    if _checked:return
    data=json.loads((ROOT/'models/relight/provenance.json').read_text(encoding='utf8'))
    if data.get('backend')!='moge-2-small-normal':raise ValueError('补光模型清单版本不匹配。')
    for item in data['files']:
        path=(ROOT/item['file']).resolve()
        if not path.is_relative_to(ROOT):raise ValueError('补光模型路径无效。')
        digest=hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(8*1024**2),b''):digest.update(block)
        if digest.hexdigest()!=item['sha256']:raise ValueError('MoGe-2 Small 文件校验失败：'+item['file'])
    _checked=True

def _load(target):
    if 'moge' not in _models:
        from moge.model.v2 import MoGeModel
        checkpoint=torch.load(ROOT/'models/relight/moge-small/model.pt',map_location='cpu',weights_only=True)
        model=MoGeModel(**checkpoint['model_config']);model.load_state_dict(checkpoint['model'],strict=True)
        _models['moge']=model.eval()
    return _models['moge'].to(target)

def adapt(depth,normal,valid,mirror_normal,mirror_valid):
    """Reliability measures flip consistency, not calibrated correctness."""
    depth=np.asarray(depth,np.float32);normal=np.asarray(normal,np.float32)
    mirrored=np.asarray(mirror_normal,np.float32)[:,::-1].copy();mirrored[:,:,0]*=-1
    mirror_valid=np.asarray(mirror_valid,bool)[:,::-1]
    length=np.linalg.norm(normal,axis=2)
    valid=np.asarray(valid,bool)&np.isfinite(depth)&(depth>1e-5)&np.isfinite(normal).all(2)&(length>1e-7)
    if not valid.any():raise ValueError('未得到可用的补光几何，照片未应用补光。')
    normal=normal/np.maximum(length[:,:,None],1e-7)
    mirrored=mirrored/np.maximum(np.linalg.norm(mirrored,axis=2,keepdims=True),1e-7)
    deviation=np.linalg.norm(normal-mirrored,axis=2)*.5
    confidence=np.clip(1-deviation*6,0,1)*valid*mirror_valid*np.isfinite(mirrored).all(2)
    normal*=np.array([1,-1,-1],np.float32) # OpenCV -> AURA camera axes.
    normal[~valid]=0
    inverse=1/np.maximum(depth,1e-5);inverse[~valid]=np.median(inverse[valid])
    confidence[~np.isfinite(confidence)]=0
    if not np.isfinite(inverse).all():raise ValueError('补光深度返回无效数值。')
    return inverse.astype(np.float32),normal.astype(np.float32),confidence.astype(np.float32)

def predict(rgb,progress=None):
    global _failed_gpu
    dependencies()
    with GPU_LOCK:
        verify();device='cpu' if _failed_gpu else RUNTIME.device()
        def run(target):
            if progress:progress('MoGe-2 Small 正在分析深度与表面方向…')
            model=_load(target)
            tensor=torch.from_numpy(np.ascontiguousarray(rgb)).permute(2,0,1).to(target,dtype=torch.float32)/255
            with torch.inference_mode():
                result=model.infer(tensor,resolution_level=9,apply_mask=False,use_fp16=target=='cuda')
                if progress:progress('正在检查补光几何一致性…')
                # Reliability needs normals only, avoiding a second camera/depth solve.
                with torch.autocast(device_type=target,dtype=torch.float16,enabled=target=='cuda'):
                    mirror=model.forward(torch.flip(tensor,[-1])[None],num_tokens=model.num_tokens_range[1])
            arrays=[v.float().cpu().numpy() for v in (result['depth'],result['normal'],result['mask'],mirror['normal'][0],mirror['mask'][0]>.5)]
            output=adapt(*arrays)
            RUNTIME.mark('几何补光','CUDA · MoGe-2 Small FP16 / 合成FP32' if target=='cuda' else 'CPU · MoGe-2 Small FP32')
            return output
        try:return run(device)
        except RuntimeError as error:
            if device!='cuda' or not gpu_error(error):raise
            _failed_gpu=True
            if 'moge' in _models:_models['moge'].to('cpu')
            torch.cuda.empty_cache();RUNTIME.mark('几何补光','CPU','GPU补光分析失败，已自动改用CPU：'+str(error)[:220])
            return run('cpu')
