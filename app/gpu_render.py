"""GPU-first render graph using AURA's existing, trusted photographic formulae.

Pixel functions are compiled from local project source into a CUDA-array
namespace. There is no user code evaluation and no per-stage CPU image fallback.
The CPU implementations remain unchanged as the reference/failure recovery path.
"""
import ast
import copy
import functools
import importlib
import inspect
import json
import operator
import threading
import textwrap
import types
import weakref
from collections import OrderedDict
import numpy as np
from gpu_backend import cupy,upload,download,is_device,NP,CV,binary,inplace,FrameStats,mark_stage

PIXEL = {
 'color_science':{'convert_linear','decode','encode','from_srgb','to_srgb','oklab','oklab_rgb'},
 'develop_engine':{'smoothstep','point_weight','edit_lch','input_working','tone','white_balance','color_tile','spatial_details','render'},
 'creative_color':{'lut_apply','apply','match','statistics','reference_lab','reference_rgb'},
 'point_curves':{'evaluate','apply'},
 'complexion':{'render_skin'},'skin_enhance':{'enhance_skin'},
 'skin_texture':{'adaptive'},'skin_detail_protection':{'strength_mask'},
 'skin_color':{'tone','adjust','apply_skin_color'},'face_volume':{'zones','apply_face_volume'},
 'face_details':{'apply_face_repairs','apply_face_details','protect_face_details'},
 'body_details':{'body_blend','apply_body'},'skin_junction':{'blend_junction'},
 'region_masks':{'soft_edge','skin_blend','apply_layers'},
 'portrait_effects':{'chroma_preserving_lift','wrinkle_and_circles','wrinkle_zone_strength'},
 'patch_repair':{'sample','plane','apply_patches'},
 'manual_retouch':{'coverage','linear','display','smooth','source_point','gradient_heal','apply'},
 'creative_portrait':{'masked','legacy_light','fabric','recolor','blush','background','apply_clean'},
 'effect_controls':{'before','blend'},'mobile_cached_patches':{'apply'},
 'local_develop':{'alpha','apply'},
 'face_reshape':{'_dense_plan','apply','display_mask'},'body_shape':{'maps','apply_forms','chin_shadow'},
 'photo_body':{'apply','inverse_points','display_mask'},'live_body':{'apply_body_field'},'video_body_field':{'apply'},
 'liquify':{'maps','crop','apply','freeze_crop'},
 'develop_optics':{'_normalized','mapped','zoom_for','inverse_points','apply'},
 'develop_output':{'preview','encoded_output'},'composition':{'oriented','apply'},
 'relight_math':{'unit','linear','srgb','light_rgb','native_geometry','visible_depth_visibility','_contribution','_light','contribution','compose'},'relight_engine':{'_bytes','_put','_coefficients','allocation','apply'},
 'damo_blend_engine':{'compose'},
 'app_v3':{'_render_pixels','_render_color_pixels','_render_pixels_cpu','_render_color_pixels_cpu'},
 'creative_scene_ui':{'apply_scene','creative_render','background_mask','clothes_mask'},
 'creative_color_ui':{'apply_creative_color'},
 'effect_ui':{'effect_before','effect_after'},'liquify_guides':{'sample_grid'},
 'editing':{'repair_alpha'},'vendor.pie.poisson':{'blend_dst_numpy'},
 'gpu_render':{'output_pixels','preview_pixels','quantize_pixels','surface_filters'},
 'video_skin':{'retouch'},
}

_variants={};_compile_lock=threading.RLock();_tls=threading.local();_report={};_report_lock=threading.Lock()
DOMAIN_LOCK=threading.RLock()
_contract_stamp=None
_icc_tables=OrderedDict()


def icc_transform_device(rgb,source,destination,proof=None,intent=1):
    """Compile an ICC profile into a GPU preview LUT; LCMS reads profiles on CPU.

    This adapter is used for display/soft-proof previews, never for RAW source
    storage or HDR export. Full RGB raster evaluation is device-side.
    """
    import hashlib,icc_runtime,color_science as cs
    cp=cupy();key=(hashlib.sha256(source).digest(),hashlib.sha256(destination).digest(),hashlib.sha256(proof or b'').digest(),intent)
    table=_icc_tables.get(key)
    if table is None:
        n=129;axis=np.linspace(0,1,n,dtype=np.float32);r,g,b=np.meshgrid(axis,axis,axis,indexing='ij')
        samples=np.stack([r,g,b],axis=-1).reshape(n*n,n,3)
        # Profile parsing/table compilation is bounded configuration work.
        if source!=cs.icc_profile('ProPhoto',linear=True):raise RuntimeError('GPU ICC preview expects the linear ProPhoto working profile.')
        working=cs.from_srgb(samples*255)
        mapped=icc_runtime.transform(working,source,destination,proof,intent).reshape(n,n,n,3)
        table=upload(mapped);_icc_tables[key]=table
        while len(_icc_tables)>3:_icc_tables.popitem(last=False)
    encoded=variant(cs.to_srgb)(rgb)/255;n=table.shape[0]
    pos=encoded*(n-1);index=cp.clip(cp.floor(pos),0,n-2).astype(cp.int32);fraction=pos-index
    output=cp.zeros_like(encoded,cp.float32)
    for bits in range(8):
        ix=index[:,:,0]+(bits&1);iy=index[:,:,1]+((bits>>1)&1);iz=index[:,:,2]+((bits>>2)&1)
        weight=cp.ones(encoded.shape[:2],cp.float32)
        for c in range(3):weight*=fraction[:,:,c] if (bits>>c)&1 else 1-fraction[:,:,c]
        output+=table[ix,iy,iz]*weight[:,:,None]
    return output


def refresh_extensions():
    """Read the agreed local extension manifest; it contains names, not code."""
    global _contract_stamp
    from pathlib import Path
    import re
    root=Path(__file__).resolve().parent;path=root/'docs/color-workbench-gpu-contract.json'
    if not path.is_file():return
    stamp=path.stat().st_mtime_ns
    if stamp==_contract_stamp:return
    data=json.loads(path.read_text(encoding='utf-8'))
    modules=data.get('pixel_modules',{})
    if not isinstance(modules,dict):raise ValueError('GPU extension manifest must contain pixel_modules.')
    for module,functions in modules.items():
        if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',module):raise ValueError('Invalid local GPU extension name.')
        if not isinstance(functions,list) or any(not isinstance(f,str) or not f.isidentifier() for f in functions):raise ValueError('Invalid local GPU extension functions.')
        PIXEL.setdefault(module,set()).update(functions)
    with _compile_lock:_variants.clear()
    _contract_stamp=stamp


def register_pixel_functions(module,functions):
    """Extend only trusted project modules; metadata analysis stays unregistered."""
    from pathlib import Path
    import re
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',module):raise ValueError('Invalid GPU module name.')
    root=Path(__file__).resolve().parent
    source=root.joinpath(*module.split('.')).with_suffix('.py')
    if not source.is_file() or not source.resolve().is_relative_to(root):raise ValueError('GPU extensions must be local AURA source modules.')
    functions=list(functions)
    if any(not isinstance(name,str) or not name.isidentifier() for name in functions):raise ValueError('Invalid GPU function name.')
    with _compile_lock:PIXEL.setdefault(module,set()).update(functions)


def execute_pixel(fn,*args,host_result=False,**kwargs):
    """Execute a registered pixel function from an independent preview worker.

    The returned arrays stay in CUDA unless host_result=True is explicitly used
    at the presentation/encoding boundary. No silent CPU fallback is performed.
    """
    cupy();refresh_extensions()
    if fn.__name__ not in PIXEL.get(fn.__module__,set()):raise ValueError('Register this pixel function before GPU execution.')
    values=[CACHE.get(v) if isinstance(v,np.ndarray) else v for v in args]
    with DOMAIN_LOCK,FrameStats() as stats:
        old=active();_tls.active=True
        try:result=variant(fn)(*values,**kwargs)
        finally:_tls.active=old
        if host_result:
            result=publish_tree(result,{})
    stats['backend']='CUDA'
    with _report_lock:_report.clear();_report.update(stats)
    return result


def download_tree(value,reason='metadata/file boundary'):
    if is_device(value):return download(value,reason)
    if isinstance(value,dict):return {k:download_tree(v,reason) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return type(value)(download_tree(v,reason) for v in value)
    return value


class ResidentCache:
    """Weak host mirrors share one device buffer; mutable masks are not cached."""
    def __init__(self,budget=3*1024**3):self.values=OrderedDict();self.budget=budget;self.lock=threading.RLock()
    def key(self,a):return (a.__array_interface__['data'][0],a.shape,a.strides,a.dtype.str)
    def get(self,a):
        if is_device(a):return a
        if not isinstance(a,np.ndarray):return a
        key=self.key(a)
        with self.lock:
            item=self.values.get(key)
            if item is not None and item[0]() is not None:
                self.values.move_to_end(key);return item[1]
        device=upload(a)
        if not a.flags.writeable:self.put(a,device)
        return device
    def put(self,host,device):
        if not isinstance(host,np.ndarray) or not is_device(device):return
        with self.lock:
            self.values[self.key(host)]=(weakref.ref(host),device)
            while sum(v.nbytes for ref,v in self.values.values())>self.budget and len(self.values)>1:self.values.popitem(last=False)
            for k,(ref,v) in list(self.values.items()):
                if ref() is None:self.values.pop(k,None)
    def host(self,device,memo):
        if not is_device(device):return device
        if id(device) in memo:return memo[id(device)]
        with self.lock:
            for ref,value in self.values.values():
                if value is device and ref() is not None:
                    memo[id(device)]=ref();return ref()
        host=download(device,'completed render host mirror');host.flags.writeable=False
        self.put(host,device);memo[id(device)]=host;return host
    def clear(self):
        with self.lock:self.values.clear()


CACHE=ResidentCache()


def active():return bool(getattr(_tls,'active',False))


def _operator(op,left,right):return binary(op,left,right)


def _getitem(value,index):
    if isinstance(value,np.ndarray) and (value.ndim>=2 or is_device(index)):
        value=CACHE.get(value) if not value.flags.writeable else upload(value)
    return value[index]


def _setitem(value,index,source):
    if is_device(value) and isinstance(source,np.ndarray):source=upload(source)
    if isinstance(value,np.ndarray) and is_device(source):raise RuntimeError('GPU render attempted to write a CPU pixel buffer.')
    value[index]=source


def _array_method(value,name,*args,**kwargs):
    if isinstance(value,np.ndarray) and name in ('astype','copy','reshape','transpose','flatten','ravel'):value=upload(value)
    if is_device(value) and name in ('tobytes','tolist'):
        return getattr(download(value,'cache/compact geometry serialization'),name)(*args,**kwargs)
    return getattr(value,name)(*args,**kwargs)


def _cast(name,value):
    return value.astype(getattr(cupy(),name)) if is_device(value) else getattr(np,name)(value)


def _immutable(array,value):
    if not is_device(array):array.flags.writeable=value


class Adapt(ast.NodeTransformer):
    ops={ast.Add:'add',ast.Sub:'sub',ast.Mult:'mul',ast.Div:'truediv',ast.FloorDiv:'floordiv',ast.Pow:'pow',ast.Mod:'mod',ast.MatMult:'matmul',ast.BitAnd:'and_',ast.BitOr:'or_',ast.BitXor:'xor',ast.LShift:'lshift',ast.RShift:'rshift'}
    def visit_BinOp(self,node):
        node=self.generic_visit(node)
        return ast.copy_location(ast.Call(ast.Name('_cuda_binary',ast.Load()),[ast.Constant(self.ops[type(node.op)]),node.left,node.right],[]),node)
    def visit_Compare(self,node):
        names={ast.Eq:'eq',ast.NotEq:'ne',ast.Lt:'lt',ast.LtE:'le',ast.Gt:'gt',ast.GtE:'ge'}
        if len(node.ops)==1 and type(node.ops[0]) in names:
            return ast.copy_location(ast.Call(ast.Name('_cuda_binary',ast.Load()),[ast.Constant(names[type(node.ops[0])]),self.visit(node.left),self.visit(node.comparators[0])],[]),node)
        return self.generic_visit(node)
    def visit_AugAssign(self,node):
        target=copy.deepcopy(node.target)
        for n in ast.walk(target):
            if hasattr(n,'ctx'):n.ctx=ast.Load()
        expression=ast.Call(ast.Name('_cuda_inplace',ast.Load()),[ast.Constant(self.ops[type(node.op)]),self.visit(target),self.visit(node.value)],[])
        assignment=ast.copy_location(ast.Assign([node.target],expression),node)
        return self.visit_Assign(assignment)
    def visit_Assign(self,node):
        if len(node.targets)==1:
            target=node.targets[0]
            if isinstance(target,ast.Attribute) and target.attr=='writeable' and isinstance(target.value,ast.Attribute) and target.value.attr=='flags':
                return ast.copy_location(ast.Expr(ast.Call(ast.Name('_cuda_immutable',ast.Load()),[self.visit(target.value.value),self.visit(node.value)],[])),node)
            if isinstance(target,ast.Subscript):
                return ast.copy_location(ast.Expr(ast.Call(ast.Name('_cuda_setitem',ast.Load()),[self.visit(target.value),self.index(target.slice),self.visit(node.value)],[])),node)
        return self.generic_visit(node)
    def index(self,node):
        if isinstance(node,ast.Slice):return ast.Call(ast.Name('slice',ast.Load()),[self.visit(x) if x is not None else ast.Constant(None) for x in (node.lower,node.upper,node.step)],[])
        if isinstance(node,ast.Tuple):return ast.Tuple([self.index(x) for x in node.elts],ast.Load())
        return self.visit(node)
    def visit_Subscript(self,node):
        if isinstance(node.ctx,ast.Load):
            return ast.copy_location(ast.Call(ast.Name('_cuda_getitem',ast.Load()),[self.visit(node.value),self.index(node.slice)],[]),node)
        return self.generic_visit(node)
    def visit_Call(self,node):
        if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='np' and node.func.attr in ('float32','float64','int32','int64','uint8','uint16','uint32') and len(node.args)==1:
            return ast.copy_location(ast.Call(ast.Name('_cuda_cast',ast.Load()),[ast.Constant(node.func.attr),self.visit(node.args[0])],[]),node)
        if isinstance(node.func,ast.Attribute) and node.func.attr in ('astype','copy','reshape','transpose','flatten','ravel','tobytes','tolist'):
            return ast.copy_location(ast.Call(ast.Name('_cuda_array_method',ast.Load()),[self.visit(node.func.value),ast.Constant(node.func.attr)]+[self.visit(x) for x in node.args],[self.visit(x) for x in node.keywords]),node)
        return self.generic_visit(node)
    def visit_ImportFrom(self,node):
        if node.module in PIXEL or node.module in ('skin_surface_cache','icc_runtime','damo_blend_engine','vendor.pie.poisson'):
            values=[]
            for alias in node.names:
                values.append(ast.Assign([ast.Name(alias.asname or alias.name,ast.Store())],ast.Call(ast.Name('_cuda_get',ast.Load()),[ast.Constant(node.module),ast.Constant(alias.name)],[])))
            return [ast.copy_location(v,node) for v in values]
        return node
    def visit_Import(self,node):
        out=[]
        for alias in node.names:
            if alias.name in PIXEL:
                out.append(ast.Assign([ast.Name(alias.asname or alias.name,ast.Store())],ast.Call(ast.Name('_cuda_module',ast.Load()),[ast.Constant(alias.name)],[])))
            else:out.append(ast.Import([alias]))
        return [ast.copy_location(v,node) for v in out]


class ModuleCUDA:
    def __init__(self,module):self.module=module
    def __getattr__(self,name):return gpu_function(self.module.__name__,name)


def _module(name):return ModuleCUDA(importlib.import_module(name))


def gpu_function(module,name):
    original=getattr(importlib.import_module(module),name)
    special=_special(module,name)
    if special:return special
    if name in PIXEL.get(module,set()) and inspect.isfunction(original):
        return lambda *args,**kwargs:variant(original)(*args,**kwargs)
    return original


def variant(fn):
    raw=inspect.unwrap(fn);key=(raw.__module__,raw.__qualname__)
    with _compile_lock:
        if key in _variants:return _variants[key]
        source=textwrap.dedent(inspect.getsource(raw));tree=ast.parse(source)
        if not tree.body or not isinstance(tree.body[0],(ast.FunctionDef,ast.AsyncFunctionDef)) or tree.body[0].name!=raw.__name__:
            raise RuntimeError('渲染业务源码正在更新，请重新启动 worker 后再验证：'+raw.__module__+'.'+raw.__name__)
        tree.body[0].decorator_list=[];tree=Adapt().visit(tree);ast.fix_missing_locations(tree)
        namespace=dict(raw.__globals__)
        namespace.update(np=NP,cv2=CV,_cuda_binary=_operator,_cuda_immutable=_immutable,_cuda_get=gpu_function,_cuda_module=_module,
                         _cuda_getitem=_getitem,_cuda_setitem=_setitem,_cuda_array_method=_array_method,_cuda_inplace=inplace)
        namespace['_cuda_cast']=_cast
        if raw.__module__=='relight_engine' and raw.__name__=='_coefficients':namespace['_fields']=OrderedDict()
        if raw.__module__=='vendor.pie.poisson':
            from cupyx.scipy import ndimage
            from gpu_backend import NamespaceCUDA,FFTCUDA
            namespace['scipy']=types.SimpleNamespace(fft=FFTCUDA());namespace['ndimage']=NamespaceCUDA(ndimage)
        for name,value in list(namespace.items()):
            if isinstance(value,types.ModuleType) and value.__name__ in PIXEL:namespace[name]=ModuleCUDA(value)
            elif callable(value) and hasattr(value,'__module__') and _special(value.__module__,getattr(value,'__name__','')):
                namespace[name]=_special(value.__module__,value.__name__)
            elif inspect.isfunction(value) and value.__name__ in PIXEL.get(value.__module__,set()):
                namespace[name]=lambda *args,_fn=value,**kwargs:variant(_fn)(*args,**kwargs)
        exec(compile(tree,inspect.getsourcefile(raw)+' [CUDA]','exec'),namespace)
        compiled=namespace[raw.__name__]
        @functools.wraps(raw)
        def run(*args,**kwargs):
            mark_stage(raw.__module__+'.'+raw.__qualname__)
            return compiled(*args,**kwargs)
        _variants[key]=run
        return run


class DocumentCUDA:
    def __init__(self,document):
        self.original=document;self._base=None
        self._rgb=CACHE.get(document.rgb);CACHE.put(document.rgb,self._rgb)
    def __getattr__(self,name):
        value=getattr(self.original,name)
        if name=='rgb':return self._rgb
        if name=='scene' and value is not None:
            device=CACHE.get(value);CACHE.put(value,device);return device
        return value
    def base_float(self):
        if self._base is None:
            cp=cupy();self._base=self._rgb.astype(cp.float32)/(257 if self._rgb.dtype==cp.uint16 else 1)
        return self._base


class ContextCUDA:
    fields={'generated','done_mask','small_mask','output','output_float','manual_input','creative_input','creative_output','color_input','liquify_input','form_changed','slim_changed'}
    def __init__(self,context):
        self.__dict__.update(context.__dict__);self._original=context;self.document=DocumentCUDA(context.document)
        # GPU-only cache entries created while rendering must not leak into the
        # original session or poison the CPU recovery/reference implementation.
        from render_queue import detached
        self.session=detached(context.session)
        for name in self.fields:
            value=getattr(context,name,None)
            if isinstance(value,np.ndarray):setattr(self,name,CACHE.get(value))
        self.selection=SelectionCUDA(context.selection)
    def __getattr__(self,name):
        original=getattr(self._original,name)
        if inspect.ismethod(original) and original.__func__.__name__ in PIXEL.get(original.__func__.__module__,set()):
            return lambda *args,**kwargs:variant(original.__func__)(self,*args,**kwargs)
        return original


class SelectionCUDA:
    def __init__(self,original):self.original=original;self.mask=upload(original.mask);self.auto=upload(original.auto)
    def repair_alpha(self,*args,**kwargs):
        from editing import Selection
        return variant(Selection.repair_alpha)(self,*args,**kwargs)


def _special(module,name):
    if (module,name)==('icc_runtime','transform'):return icc_transform_device
    if (module,name)==('point_curves','curve_table'):
        import point_curves
        return lambda points:upload(point_curves.curve_table(points))
    if (module,name)==('skin_surface_cache','surfaces'):
        def surfaces(source,width):
            fine=CV.GaussianBlur(source,(0,0),max(.65,width*.0035))
            low=CV.bilateralFilter(fine,0,22,max(2,width*.015))
            return fine,low
        return surfaces
    if (module,name)==('damo_blend_engine','blend_map'):
        def learned(source):
            # Resize and reconstruction are rendering operations and stay CUDA.
            # Only the compact model/cache input crosses the inference boundary.
            import damo_blend_engine,torch
            cp=cupy();source=upload(source).astype(cp.float32)
            small=CV.resize(source/127.5-1,(512,512),interpolation=CV.cv.INTER_LINEAR)
            tensor=torch.from_numpy(np.ascontiguousarray(download(small,'compact AI inference/cache input').transpose(2,0,1)))[None]
            prediction=upload(damo_blend_engine._predict(tensor))
            h,w=source.shape[:2];field=CV.resize(prediction,(w,h),interpolation=CV.cv.INTER_LINEAR)
            coordinates=cp.arange(500,dtype=cp.float32)
            edge=cp.minimum(cp.where(coordinates<=20,coordinates/20,1),cp.where(coordinates>480,(500-coordinates)/20,1))
            mask=cp.clip(cp.minimum(edge[:,None],edge[None,:]),0,1)
            fade=CV.resize(mask,(w,h),interpolation=CV.cv.INTER_LINEAR)
            return ((field-.5)*fade[:,:,None]+.5).astype(cp.float32)
        return learned
    return None


OUTPUT_FIELDS=('output','output_float','manual_input','creative_input','creative_output','color_input','liquify_input','slim_changed','form_changed','reshape_changed','photo_body_cache','photo_body_changed','photo_body_message')


def render(context,method):
    """Execute the whole requested RGB chain on CUDA; publish immutable mirrors."""
    cupy();refresh_extensions();old=active();_tls.active=True
    try:
        with DOMAIN_LOCK,FrameStats() as stats:
            device=ContextCUDA(context);variant(method)(device)
            memo={}
            for name in OUTPUT_FIELDS:
                value=getattr(device,name,None)
                if is_device(value):value=CACHE.host(value,memo)
                elif isinstance(value,(dict,list,tuple)):value=publish_tree(value,memo)
                setattr(context,name,value)
        stats['backend']='CUDA';name=cupy().cuda.runtime.getDeviceProperties(0)['name'];stats['device']=name.decode() if isinstance(name,bytes) else str(name)
        context.gpu_render_report=dict(stats)
        with _report_lock:_report.clear();_report.update(stats)
        return context.output_float
    finally:_tls.active=old


def publish_tree(value,memo):
    if is_device(value):return CACHE.host(value,memo)
    if isinstance(value,dict):return {k:publish_tree(v,memo) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return type(value)(publish_tree(v,memo) for v in value)
    return value


def render_automatic(context,method):
    """Default to CUDA, record an explicit whole-frame recovery when unavailable."""
    import os,traceback
    from ai_runtime import RUNTIME
    if os.environ.get('AURA_RENDER_BACKEND','cuda').lower()=='cpu':
        result=method(context)
        with _report_lock:_report.clear();_report.update(backend='CPU',reason='Explicit CPU render override')
        context.gpu_render_report=dict(_report)
        RUNTIME.mark('图片渲染','CPU','显式 CPU 渲染设置');return result
    try:
        result=render(context,method);RUNTIME.mark('图片渲染','CUDA');return result
    except InterruptedError:raise
    except Exception as error:
        reason=str(error)
        # DeviceContext is separate, so partial CUDA results cannot overwrite the
        # original recipe, analysis session or CPU reference input.
        result=method(context)
        with _report_lock:_report.clear();_report.update(backend='CPU',reason=reason,recovery=True)
        context.gpu_render_report=dict(_report)
        RUNTIME.mark('图片渲染','CPU','GPU 渲染回退：'+reason)
        from pathlib import Path
        (Path(__file__).resolve().parent/'gpu-render-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        return result


def report():
    with _report_lock:return dict(_report)


def record_cpu_recovery(stage,error):
    from ai_runtime import RUNTIME
    reason=str(error);RUNTIME.mark(stage,'CPU','GPU 运算回退：'+reason)
    with _report_lock:_report.setdefault('cpu_recoveries',{})[stage]=reason


def output_pixels(rgb,space='sRGB',hdr=False,depth=16):
    """Color conversion and output quantization; encoding itself remains CPU."""
    import color_science as cs
    if space=='sRGB' and not hdr:encoded=rgb/255
    else:
        linear=cs.convert_linear(cs.decode(rgb/255),'sRGB',space)
        if hdr:return linear.astype(np.float32)
        encoded=cs.encode(linear,space)
    maximum=65535 if depth==16 else 255
    return np.clip(np.rint(encoded*maximum),0,maximum).astype(np.uint16 if depth==16 else np.uint8)


def quantize_pixels(rgb,depth=8):
    return np.clip(np.rint(rgb*(257 if depth==16 else 1)),0,65535 if depth==16 else 255).astype(np.uint16 if depth==16 else np.uint8)


def surface_filters(source,width):
    fine=CV.GaussianBlur(source,(0,0),max(.65,width*.0035))
    return fine,CV.bilateralFilter(fine,0,22,max(2,width*.015))


def preview_pixels(rgb,box=None,max_edge=1600):
    if box is not None:
        a,b,c,d=box;rgb=rgb[b:d,a:c]
    h,w=rgb.shape[:2];factor=min(1,max_edge/max(h,w));size=(max(1,round(w*factor)),max(1,round(h*factor)))
    if factor<1:rgb=CV.resize(rgb,size,interpolation=CV.cv.INTER_AREA)
    return np.clip(np.rint(rgb),0,255).astype(np.uint8)


def original_view_points(app,points):
    """Original-coordinate map for a visible GPU raster, without OpenCV row limits."""
    import develop_optics,liquify_guides,photo_body,face_reshape
    cp=cupy();q=upload(points).astype(cp.float32)
    q=variant(develop_optics.inverse_points)(q,app.document.rgb.shape,app.workflow_extensions.get('optics',{}))
    if app.liquify_active():q=q+variant(liquify_guides.sample_grid)(app.liquify_state['flow'],q,(0,0,app.output.shape[1],app.output.shape[0]))
    if getattr(app,'photo_body_changed',False):q=variant(photo_body.inverse_points)(q,photo_body.current_field(app.photo_body_cache))
    for field in face_reshape._fields(app.reshape_cache,app.face_settings):q=q+variant(liquify_guides.sample_grid)(field['grid'],q,field['roi'])
    return q


def viewport(app,bounds,size,localcut):
    """All viewport sampling, comparison and mask-color compositing stays CUDA.

    Tk receives only the small, final 8-bit screen raster. GUI text/handles are
    still ordinary Tk widgets and are not part of the photographic pixel graph.
    """
    from PIL import Image
    import face_reshape
    cp=cupy();a,b,c,d=bounds;pw,ph=size
    with DOMAIN_LOCK:
        xs=a+(cp.arange(pw,dtype=cp.float32)+.5)*(c-a)/pw-.5
        ys=b+(cp.arange(ph,dtype=cp.float32)+.5)*(d-b)/ph-.5
        y,x=cp.meshgrid(ys,xs,indexing='ij');cut=int(round(localcut*pw/max(1,c-a)))
        source=CACHE.get(app.output)
        if getattr(app,'_preview_frame',None) is not None:
            frame=CACHE.get(app._preview_frame);h,w=app.document.rgb.shape[:2];sh,sw=frame.shape[:2]
            q=original_view_points(app,cp.stack((x,y),axis=2).reshape(-1,2)).reshape(ph,pw,2)
            rgb=CV.remap(frame,(q[:,:,0]+.5)*sw/w-.5,(q[:,:,1]+.5)*sh/h-.5,CV.cv.INTER_LINEAR,CV.cv.BORDER_REFLECT_101)
        elif app.drag and app.drag['mode'].startswith('liquify_'):
            flow=upload(app.liquify_state['flow']);sy=(flow.shape[0]-1)/max(1,app.output.shape[0]-1);sx=(flow.shape[1]-1)/max(1,app.output.shape[1]-1)
            delta=CV.remap(flow,x*sx,y*sy,CV.cv.INTER_LINEAR,CV.cv.BORDER_REPLICATE)
            frame=upload(app.liquify_preview);factor=app.liquify_preview_factor
            rgb=CV.remap(frame,(x+delta[:,:,0]+.5)*factor-.5,(y+delta[:,:,1]+.5)*factor-.5,CV.cv.INTER_LINEAR,CV.cv.BORDER_REFLECT_101)
        elif app.drag and app.drag['mode'].startswith('retouch_') and getattr(app,'manual_preview',None) is not None:
            q=original_view_points(app,cp.stack((x,y),axis=2).reshape(-1,2)).reshape(ph,pw,2)
            factor=app.manual_preview_factor
            delta=CV.remap(upload(app.manual_preview)-upload(app.manual_preview_base),(q[:,:,0]+.5)*factor-.5,(q[:,:,1]+.5)*factor-.5,CV.cv.INTER_LINEAR,CV.cv.BORDER_REFLECT_101)
            rgb=cp.clip(cp.rint(CV.remap(CACHE.get(app.output_float),x,y,CV.cv.INTER_LINEAR,CV.cv.BORDER_REFLECT_101)+delta),0,255).astype(cp.uint8)
        else:
            rgb=CV.resize(source[b:d,a:c],size,interpolation=CV.cv.INTER_LANCZOS4)
        workbench=getattr(app,'color_workbench',None)
        if workbench is not None and workbench.active and workbench.compare.get()=='原图滑动对比' and workbench.clipping.get():
            values=CV.remap(CACHE.get(app.output_float),x,y,CV.cv.INTER_LINEAR,CV.cv.BORDER_REFLECT_101)
            bright=values.max(2)>=255;dark=values.max(2)<=0
            rgb[bright]=cp.asarray([245,58,65],cp.uint8);rgb[dark]=cp.asarray([58,96,245],cp.uint8)
        if cut:rgb[:,:cut]=CV.remap(upload(app.session.original),x[:,:cut],y[:,:cut],CV.cv.INTER_LINEAR,CV.cv.BORDER_REFLECT_101)
        needs_masks=bool(app.overlay.get() or app.mask_overlay.get() or app.mode.get()=='creative_clean' or app.mode.get().startswith(('beauty_','effect_')) or getattr(app,'beauty_auto_overlay',None) and app.beauty_auto_overlay.get())
        if needs_masks:
            q=original_view_points(app,cp.stack((x,y),axis=2).reshape(-1,2)).reshape(ph,pw,2)
            def mask_image(mask):
                result=CV.remap(upload(mask).astype(cp.uint8),q[:,:,0],q[:,:,1],CV.cv.INTER_NEAREST,CV.cv.BORDER_CONSTANT)>0
                if cut:result[:,:cut]=False
                return result
            layers=[]
            if app.mask_overlay.get() and 0<=app.active_layer<len(app.region_layers):
                from smart_selection import refine
                layer=app.region_layers[app.active_layer]
                if layer.get('color_process',1)==2:
                    from local_develop import alpha as local_alpha
                    reference=app.color_input if app.color_input is not None else app.session.original
                    mh,mw=reference.shape[:2];scale=min(1,1200/max(mh,mw));ss=(max(2,round(mw*scale)),max(2,round(mh*scale)))
                    if scale<1 and max((bounds[2]-bounds[0])/size[0],(bounds[3]-bounds[1])/size[1])<=1:
                        lo=max(0,min(mh-1,int(cp.floor(q[:,:,1].min()).item())-2));hi=max(lo+1,min(mh,int(cp.ceil(q[:,:,1].max()).item())+3))
                        weights=variant(local_alpha)(layer,CACHE.get(reference),(lo,hi))
                        opacity=CV.remap(weights,q[:,:,0],q[:,:,1]-lo,CV.cv.INTER_LINEAR,CV.cv.BORDER_CONSTANT)*.6
                    else:
                        local=dict(layer,mask=CV.resize(upload(layer['mask']).astype(cp.uint8),ss,interpolation=CV.cv.INTER_NEAREST)>0,parameters=dict(layer['parameters']))
                        local['parameters']['feather']*=scale;local['parameters']['expand']*=scale
                        weights=variant(local_alpha)(local,CV.resize(CACHE.get(reference),ss,interpolation=CV.cv.INTER_AREA))
                        opacity=CV.remap(weights,(q[:,:,0]+.5)*ss[0]/mw-.5,(q[:,:,1]+.5)*ss[1]/mh-.5,CV.cv.INTER_LINEAR,CV.cv.BORDER_CONSTANT)*.6
                    if cut:opacity[:,:cut]=0
                    if getattr(app,'_local_mask_view','彩色叠加')=='黑白蒙版':rgb=cp.repeat(cp.clip(cp.rint(opacity[:,:,None]/.6*255),0,255).astype(cp.uint8),3,axis=2)
                    else:rgb=cp.clip(cp.rint(rgb*(1-opacity[:,:,None])+cp.asarray([155,110,235])*opacity[:,:,None]),0,255).astype(cp.uint8)
                else:layers.append((mask_image(refine(layer['mask'],layer['parameters'].get('expand',0))),[155,110,235],.6))
            elif app.overlay.get():
                selected=mask_image(app.selection.mask);automatic=mask_image(app.selection.auto)
                layers.extend([(selected&automatic,[255,156,40],.62),(selected&~automatic,[60,190,255],.62)])
                if getattr(app,'show_excluded',False):layers.append((automatic&~selected,[239,102,116],.62))
            if app.mode.get()=='creative_clean' and app.clean_overlay.get():
                mask=app.workflow_extensions.get('masks',{}).get('select-'+app.clean_key())
                if mask is not None:layers.append((mask_image(mask),[235,100,80],.35))
            if app.mode.get().startswith('effect_') and app.effect_overlay.get():
                mask=app.workflow_extensions.get('masks',{}).get('erase-'+app.effect_key())
                if mask is not None:layers.append((mask_image(mask),[80,170,245],.35))
            scope='body' if getattr(app,'active_category',None)=='身体' else 'face'
            if hasattr(app,'beauty_include_key'):
                key=app.beauty_include_key(scope);exclude=app.shown_beauty_mask(key.replace('include','exclude'))
                if app.beauty_auto_overlay.get() and app.session.faces and getattr(app,'active_category',None) in ('美颜','身体'):
                    shown=mask_image(app.automatic_beauty_preview())
                    if exclude is not None:shown&=~mask_image(exclude)
                    layers.append((shown,[70,200,90],.22))
                if app.mode.get().startswith('beauty_') and app.beauty_range_overlay.get():
                    for mask,color,strength in ((app.shown_beauty_mask(key),[45,205,185],.35),(exclude,[235,90,95],.30)):
                        if mask is not None:layers.append((mask_image(mask),color,strength))
            for mask,color,strength in layers:rgb[mask]=cp.clip(cp.rint(rgb[mask]*(1-strength)+cp.asarray(color)*strength),0,255).astype(cp.uint8)
        if app.liquify_state is not None and app.liquify_protection.get() and app.mode.get().startswith('liquify_'):
            freeze=upload(app.liquify_state['freeze']);sx=(freeze.shape[1]-1)/max(1,app.output.shape[1]-1);sy=(freeze.shape[0]-1)/max(1,app.output.shape[0]-1)
            alpha=CV.remap(freeze,x*sx,y*sy,CV.cv.INTER_LINEAR,CV.cv.BORDER_REPLICATE)*.45
            if cut:alpha[:,:cut]=0
            rgb=cp.clip(cp.rint(rgb*(1-alpha[:,:,None])+cp.asarray([48,174,244])*alpha[:,:,None]),0,255).astype(cp.uint8)
        return Image.fromarray(download(rgb,'Tk screen raster'))


def thumbnail(image,size):
    from PIL import Image
    h,w=image.shape[:2];factor=min(1,size[0]/w,size[1]/h);target=(max(1,round(w*factor)),max(1,round(h*factor)))
    with DOMAIN_LOCK:return Image.fromarray(download(CV.resize(CACHE.get(image),target,interpolation=CV.cv.INTER_AREA),'thumbnail raster'))


def resize_pixels(image,size,interpolation=None):
    """GPU resampling at a decode/encoder compatibility boundary."""
    with DOMAIN_LOCK:
        device=CV.resize(CACHE.get(image),size,interpolation=CV.cv.INTER_AREA if interpolation is None else interpolation)
        return CACHE.host(device,{})


def histogram(image):
    cp=cupy()
    with DOMAIN_LOCK:
        small=CV.resize(CACHE.get(image),(320,240),interpolation=CV.cv.INTER_LINEAR)
        return [download(cp.histogram(small[:,:,i],bins=64,range=(0,256))[0],'histogram scalar bins') for i in range(3)]


def crop_stage(pixels,data,canvas_size):
    import composition
    cp=cupy();h,w=pixels.shape[:2];factor=min(1,1600/max(h,w))
    with DOMAIN_LOCK:
        small=CV.resize(CACHE.get(pixels),(max(2,round(w*factor)),max(2,round(h*factor))),interpolation=CV.cv.INTER_AREA)
        stage=variant(composition.oriented)(small,data,margin=max(1,round(4*factor)));h,w=stage.shape[:2]
        scale=min((canvas_size[0]-40)/w,(canvas_size[1]-50)/h)
        device=CV.resize(stage,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=CV.cv.INTER_AREA)
        return CACHE.host(device,{})


def crop_shade(image,box):
    cp=cupy();a,b,c,d=box
    with DOMAIN_LOCK:
        value=CACHE.get(image).copy();mask=cp.ones(value.shape[:2],bool);mask[b:d,a:c]=False
        value[mask]=(value[mask]*.35).astype(cp.uint8)
        return download(value,'crop viewport raster')
