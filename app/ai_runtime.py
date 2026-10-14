"""Shared GPU-first inference policy with visible, per-engine CPU fallback."""
import json,os,threading
from pathlib import Path
import torch
from concurrent.futures import Future

ROOT=Path(__file__).resolve().parent
CONFIG=ROOT/'acceleration.json'
GPU_LOCK=threading.RLock()

def saved_mode():
    try:value=json.loads(CONFIG.read_text(encoding='utf8')).get('mode','auto')
    except (OSError,ValueError,AttributeError):value='auto'
    return value if value in ('auto','cpu') else 'auto'
def save_mode(mode):
    if mode not in ('auto','cpu'):raise ValueError('计算模式无效。')
    CONFIG.write_text(json.dumps({'mode':mode},indent=2),encoding='utf8')

class Runtime:
    def __init__(self):
        self.mode='cpu' if torch.version.cuda is None else os.environ.get('BEAUTY_AI_DEVICE',saved_mode())
        if self.mode not in ('auto','cpu'):self.mode='auto'
        self.checked=False;self.cuda=False;self.gpu_name='';self.used={};self.notes={};self.gpu_disabled=False
        self.lock=threading.RLock()
    def device(self):
        with self.lock:
            if not self.checked:
                self.checked=True;torch.set_num_threads(4)
                if self.mode!='cpu':
                    try:
                        if torch.cuda.is_available():
                            # Real allocation + kernel validates architecture/driver, not just GPU discovery.
                            x=torch.ones((8,8),device='cuda');torch.mm(x,x);torch.cuda.synchronize();del x
                            self.gpu_name=torch.cuda.get_device_name(0);self.cuda=True
                            torch.backends.cuda.matmul.allow_tf32=False
                            torch.backends.cudnn.allow_tf32=False
                            torch.backends.cudnn.benchmark=False
                            torch.backends.cudnn.deterministic=True
                        else:self.notes['runtime']='CUDA 不可用，使用 CPU'
                    except (RuntimeError,OSError) as e:self.notes['runtime']='GPU 检测失败，使用 CPU：'+str(e)[:240]
            return 'cuda' if self.cuda and not self.gpu_disabled and self.mode!='cpu' else 'cpu'
    def mark(self,engine,device,reason=None):
        with self.lock:
            self.used[engine]=device
            if reason:self.notes[engine]=str(reason)[:300]
    def disable_torch_gpu(self,reason):
        self.gpu_disabled=True;self.mark('祛痘检测/修复','CPU',reason)
        if torch.cuda.is_available():torch.cuda.empty_cache()
    def summary(self):
        gpu=any('CUDA' in value for value in self.used.values())
        if gpu:return 'AI：GPU＋CPU · '+self.gpu_name
        if self.used or self.checked or self.mode=='cpu':return 'AI：CPU'
        return 'AI：自动选择 GPU / CPU'
    def report(self):
        with self.lock:return {'mode':self.mode,'gpu_name':self.gpu_name,'cuda_verified':self.cuda,
            'engines':self.used.copy(),'fallback_reasons':self.notes.copy(),'precision':'补光GPU法线FP16；照片合成FP32；TF32关闭' if any('FP16' in v for v in self.used.values()) else 'FP32; TF32 and FP16 disabled',
            'cpu_tasks':['RAW/DCP development','landmarks','preprocessing','selection','smoothing','compositing','UI','export']}

RUNTIME=Runtime()
def preload_portrait_async():
    """Prepare GPU models while the calling worker develops sensor RAW on CPU."""
    if RUNTIME.mode=='cpu' or torch.version.cuda is None:return None
    future=Future()
    def warm():
        try:
            if RUNTIME.device()!='cuda':future.set_result(False);return
            from damo_engine import networks
            from ai_engine import MODELS
            # Each engine takes the GPU lock itself. Never nest MODELS.lock under it.
            run_torch(lambda device:bool(networks(device)))
            future.set_result(True)
        except Exception as e:future.set_exception(e)
    threading.Thread(target=warm,daemon=True,name='portrait-gpu-warmup').start()
    return future
def gpu_error(error):
    return isinstance(error,torch.OutOfMemoryError) or any(word in str(error).lower() for word in
      ('cuda','cudnn','cublas','out of memory','allocation','gpu','device-side'))

def run_torch(fn):
    """fn(device) must return CPU results, so a retry never applies partial GPU work."""
    with GPU_LOCK:
        device=RUNTIME.device()
        try:
            result=fn(device);RUNTIME.mark('祛痘检测/修复','CUDA' if device=='cuda' else 'CPU');return result
        except RuntimeError as e:
            if device!='cuda' or not gpu_error(e):raise
            # Move cached models off CUDA before freeing allocator memory.
            from damo_engine import release_gpu_networks
            release_gpu_networks();RUNTIME.disable_torch_gpu('GPU 推理失败，已重试 CPU：'+str(e))
            return fn('cpu')

class AcceleratedSession:
    def __init__(self,path,engine):
        self.path=str(path);self.engine=engine;self.session=None;self.profile_paths=[]
        with GPU_LOCK:self.create(RUNTIME.device()=='cuda')
    def create(self,gpu):
        import onnxruntime as ort
        options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
        options.log_severity_level=3
        if os.environ.get('BEAUTY_AI_PROFILE')=='1':
            directory=ROOT/'validation-v7';directory.mkdir(exist_ok=True)
            options.enable_profiling=True;options.profile_file_prefix=str(directory/(Path(self.path).stem+'-profile'))
        providers=['CPUExecutionProvider']
        if gpu and 'CUDAExecutionProvider' in ort.get_available_providers():
            try:
                # Matching CUDA 13/cuDNN 9 DLLs are provided by our local PyTorch wheel.
                if hasattr(ort,'preload_dlls'):ort.preload_dlls()
                # ORT 1.30's CUDA DLL is a plugin, but this wheel's build-info
                # string lacks the marker used by its automatic registration.
                # Register through the public API only when no CUDA EP device
                # exists. Windows plugin loading also needs an ASCII path.
                if hasattr(ort,'get_ep_devices') and hasattr(ort,'register_execution_provider_library'):
                    if not any(ep.ep_name=='CUDAExecutionProvider' for ep in ort.get_ep_devices()):
                        from ascii_paths import ascii_directory
                        library=Path(ort.__file__).parent/'capi/onnxruntime_providers_cuda.dll'
                        if library.is_file():
                            ort.register_execution_provider_library('CUDAExecutionProvider',str(ascii_directory(library.parent)/library.name))
                providers=[('CUDAExecutionProvider',{'device_id':0,'gpu_mem_limit':2*1024**3,
                    'arena_extend_strategy':'kSameAsRequested','cudnn_conv_algo_search':'HEURISTIC',
                    'cudnn_conv_use_max_workspace':'0','do_copy_in_default_stream':'1','use_tf32':'0'}),'CPUExecutionProvider']
            except (RuntimeError,OSError,UnicodeError) as e:RUNTIME.mark(self.engine,'CPU','CUDA DLL 加载失败：'+str(e))
        try:self.session=ort.InferenceSession(self.path,sess_options=options,providers=providers)
        except Exception as e:
            if providers==['CPUExecutionProvider']:raise
            RUNTIME.mark(self.engine,'CPU','GPU 模型初始化失败，使用 CPU：'+str(e));self.session=None
            self.session=ort.InferenceSession(self.path,sess_options=options,providers=['CPUExecutionProvider'])
        self.session.disable_fallback()
        active='CUDAExecutionProvider' in self.session.get_providers()
        RUNTIME.mark(self.engine,'CUDA + CPU operators' if active else 'CPU')
        if gpu and not active and self.engine not in RUNTIME.notes:RUNTIME.notes[self.engine]='CUDA 执行接口不可用或加载失败，使用 CPU'
    def run(self,*args,**kwargs):
        with GPU_LOCK:
            try:return self.session.run(*args,**kwargs)
            except Exception as e:
                if 'CUDAExecutionProvider' not in self.session.get_providers() or not gpu_error(e):raise
                RUNTIME.mark(self.engine,'CPU','GPU 推理失败，已重试 CPU：'+str(e))
                self.session=None;self.create(False)
                return self.session.run(*args,**kwargs)
    def get_inputs(self):return self.session.get_inputs()
    def get_outputs(self):return self.session.get_outputs()
    def get_providers(self):return self.session.get_providers()
    def end_profiling(self):
        value=self.session.end_profiling()
        if value:self.profile_paths.append(value)
        return value
