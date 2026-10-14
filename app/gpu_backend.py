"""CUDA array backend, native image kernels and explicit host/device boundaries.

CPU metadata/AI/file I/O is separate from resident floating-point RGB rendering.
No OpenCV call accepting a device image is allowed to fall back to a CPU filter.
"""
import ctypes
import os
from pathlib import Path
import sys
import threading
import time
from collections import Counter
import numpy as np
from ascii_paths import ascii_directory
from cuda_runtime import preload

ROOT=Path(__file__).resolve().parent
_cp=None;_lock=threading.RLock();_handles=[];_tls=threading.local()
_kernel_cache={}


def raw_kernel(name,source):
    if name not in _kernel_cache:_kernel_cache[name]=cupy().RawKernel(source,name,options=('--std=c++17',))
    return _kernel_cache[name]


def _ascii_root(root):
    """NVRTC requires ASCII include paths; directory links consume no drives."""
    return ascii_directory(root)


def cupy():
    global _cp
    if os.environ.get('AURA_RENDER_BACKEND','cuda').lower()=='cpu':raise RuntimeError('Explicit CPU render override')
    with _lock:
        if _cp is not None:return _cp
        deps=_ascii_root(ROOT)/'gpu-render-deps-cuda130'
        if not deps.is_dir():raise RuntimeError('GPU 渲染运行库不可用，使用 CPU。')
        # Keep the existing NumPy/runtime version; append only the new packages.
        sys.path.append(str(deps))
        from cuda_headers import ensure_headers
        toolkit=ensure_headers();os.environ['CUDA_PATH']=str(toolkit)
        # NVRTC interprets temporary source paths through an ANSI API on Windows.
        # Keep data in the portable folder while using its verified ASCII alias.
        import tempfile
        temp_root=Path(os.environ.get('AURA_DATA_DIR',str(ROOT/'.aura-photo-data')))/'temp'
        temp_root.mkdir(parents=True,exist_ok=True)
        temp_path=str(ascii_directory(temp_root))
        os.environ['TEMP']=temp_path;os.environ['TMP']=temp_path;tempfile.tempdir=temp_path
        preload(ROOT,deps,_handles)
        os.environ.setdefault('CUPY_CACHE_DIR',str(Path(os.environ.get('AURA_DATA_DIR',str(ROOT/'.aura-photo-data')))/'gpu-kernel-cache'))
        import cupy as cp
        if cp.cuda.runtime.getDeviceCount()<1:raise RuntimeError('未发现可用 CUDA 图形处理器。')
        cp.sin(cp.ones(1,cp.float32));cp.cuda.get_current_stream().synchronize()
        free,total=cp.cuda.runtime.memGetInfo()
        cp.get_default_memory_pool().set_limit(size=min(int(total*.72),max(512*1024**2,int(free)-2*1024**3)))
        _cp=cp
        return cp


def is_device(value):return _cp is not None and isinstance(value,_cp.ndarray)


def upload(value):
    if is_device(value):return value
    result=cupy().asarray(value)
    stats=getattr(_tls,'stats',None)
    if stats is not None and isinstance(value,np.ndarray):stats['uploads']+=1;stats['upload_bytes']+=value.nbytes
    return result


def download(value,reason='display/file boundary'):
    if not is_device(value):return value
    stats=getattr(_tls,'stats',None)
    if stats is not None:stats['downloads']+=1;stats['download_bytes']+=value.nbytes;stats['host_boundaries'][reason]+=1
    return cupy().asnumpy(value)


def convert_args(value):
    if isinstance(value,np.ndarray):return upload(value)
    if isinstance(value,(list,tuple)):return type(value)(convert_args(v) for v in value)
    if isinstance(value,dict):return {k:convert_args(v) for k,v in value.items()}
    return value


def device_array(value,dtype=None):
    cp=cupy()
    if isinstance(value,(list,tuple)) and any(is_device(x) for x in value):
        result=cp.stack([device_array(x) for x in value])
        return result.astype(dtype) if dtype is not None else result
    return cp.asarray(value,dtype=dtype)


class NumpyCUDA:
    """NumPy-compatible math using device arrays; scalar controls stay on host."""
    def __getattr__(self,name):
        cp=cupy()
        if name=='ndarray':return (np.ndarray,cp.ndarray)
        if name in ('issubdtype','floating','integer','number','bool_','float32','float64','uint8','uint16','int32','int64','pi','inf','nan','finfo','iinfo','dtype'):return getattr(np,name)
        if name in ('linalg','fft'):return NamespaceCUDA(getattr(cp,name))
        if name=='mgrid':return cp.mgrid
        if name in ('array','asarray','ascontiguousarray'):
            def create(value,dtype=None,**kwargs):
                out=device_array(value,dtype)
                if name=='ascontiguousarray':return cp.ascontiguousarray(out)
                return out.copy() if name=='array' and kwargs.get('copy',True) else out
            return create
        target=getattr(cp,name)
        if hasattr(target,'reduce') or name in ('maximum','minimum'):return UFuncCUDA(target,name)
        if callable(target):
            def run(*args,**kwargs):
                if name=='interp':
                    if np.isscalar(args[0]) and not is_device(args[0]):return np.interp(*args,**kwargs)
                    return cp.interp(device_array(args[0]),device_array(args[1]),device_array(args[2]),**kwargs)
                if name in ('clip','interp','isfinite','round','rint','floor','ceil','sqrt','exp','exp2','sin','cos','log','abs','maximum','minimum') and args and all(np.isscalar(x) for x in args):
                    return getattr(np,name)(*args,**kwargs)
                values=[convert_args(a) for a in args]
                if name=='clip':values=[device_array(v) if isinstance(v,(list,tuple)) else v for v in values]
                if name in ('median','mean','std','var','sum','min','max','any','all','quantile','percentile') and values and isinstance(values[0],(list,tuple)):values[0]=device_array(values[0])
                initial=kwargs.pop('initial',None) if name in ('min','max','amin','amax','sum') else None
                if initial is not None and values and hasattr(values[0],'size') and values[0].size==0:return cp.asarray(initial)
                out=target(*values,**{k:convert_args(v) for k,v in kwargs.items()})
                if initial is not None:
                    out=cp.minimum(out,initial) if name in ('min','amin') else cp.maximum(out,initial) if name in ('max','amax') else out+initial
                return out
            return run
        return target


class UFuncCUDA:
    def __init__(self,fn,name):self.fn=fn;self.name=name
    def __call__(self,*args,**kwargs):
        if args and all(np.isscalar(a) for a in args):return getattr(np,self.name)(*args,**kwargs)
        return self.fn(*(device_array(a) if isinstance(a,(list,tuple)) else convert_args(a) for a in args),**kwargs)
    def reduce(self,a,*args,**kwargs):
        cp=cupy()
        if isinstance(a,(list,tuple)):a=cp.stack([upload(x) for x in a])
        if self.name in ('maximum','minimum'):return (cp.max if self.name=='maximum' else cp.min)(upload(a),axis=kwargs.pop('axis',0),**kwargs)
        if hasattr(self.fn,'reduce'):return self.fn.reduce(upload(a),*args,**kwargs)
        return (cp.max if self.name=='maximum' else cp.min)(upload(a),axis=kwargs.pop('axis',0),**kwargs)
    def accumulate(self,a,*args,**kwargs):
        if self.name not in ('maximum','minimum') and hasattr(self.fn,'accumulate'):return self.fn.accumulate(upload(a),*args,**kwargs)
        cp=cupy();a=upload(a);axis=kwargs.pop('axis',0)
        out=a.copy();step=1
        # Parallel inclusive scan; avoid one kernel per curve-table entry.
        while step<a.shape[axis]:
            here=[slice(None)]*a.ndim;prior=list(here);here[axis]=slice(step,None);prior[axis]=slice(None,-step)
            out[tuple(here)]=self.fn(out[tuple(here)],out[tuple(prior)])
            step*=2
        return out


class NamespaceCUDA:
    def __init__(self,target):self.target=target
    def __getattr__(self,name):
        fn=getattr(self.target,name)
        return lambda *args,**kwargs:fn(*(convert_args(a) for a in args),**kwargs)


def binary(operation,left,right):
    import operator
    if is_device(left) or is_device(right) or isinstance(left,np.ndarray) or isinstance(right,np.ndarray):
        if isinstance(left,np.ndarray):left=upload(left)
        if isinstance(right,np.ndarray):right=upload(right)
        if isinstance(left,(list,tuple)):left=device_array(left)
        if isinstance(right,(list,tuple)):right=device_array(right)
    return getattr(operator,operation)(left,right)


def inplace(operation,left,right):
    import operator
    if isinstance(left,np.ndarray):left=upload(left)
    if is_device(left):
        if isinstance(right,np.ndarray):right=upload(right)
        elif isinstance(right,(list,tuple)):right=device_array(right)
    names={'add':'iadd','sub':'isub','mul':'imul','truediv':'itruediv','floordiv':'ifloordiv','pow':'ipow','mod':'imod','matmul':'imatmul','and_':'iand','or_':'ior','xor':'ixor','lshift':'ilshift','rshift':'irshift'}
    return getattr(operator,names[operation])(left,right)


def _border(index,length,mode):
    cp=cupy()
    if mode==1:return cp.clip(index,0,length-1)
    if mode==2:
        p=cp.mod(index,2*length);return cp.where(p<length,p,2*length-p-1)
    if length==1:return cp.zeros_like(index)
    p=cp.mod(index,2*length-2);return cp.where(p<length,p,2*length-2-p)


class CvCUDA:
    def __init__(self):
        import cv2
        self.cv=cv2
    def __getattr__(self,name):
        if name.isupper():return getattr(self.cv,name)
        raise RuntimeError('GPU 图像运算尚未实现：cv2.'+name)

    def GaussianBlur(self,src,ksize,sigmaX,sigmaY=0,borderType=None):
        cp=cupy();src=upload(src);sx=float(sigmaX);sy=float(sigmaY or sigmaX)
        from cupyx.scipy.ndimage import convolve1d
        mode={self.cv.BORDER_REPLICATE:'nearest',self.cv.BORDER_REFLECT:'reflect',self.cv.BORDER_CONSTANT:'constant'}.get(borderType,'mirror')
        original=src.dtype;out=src.astype(cp.float32,copy=False)
        for axis,sigma,n in ((1,sx,ksize[0]),(0,sy,ksize[1])):
            if n==0:n=(int(round(sigma*8+1))|1) if original!=cp.uint8 else (int(round(sigma*6+1))|1)
            if n<=1:continue
            if sigma<=0:sigma=.3*((n-1)*.5-1)+.8
            x=cp.arange(n,dtype=cp.float64)-(n-1)*.5;weights=cp.exp(-x*x/(2*sigma*sigma));weights=(weights/weights.sum()).astype(cp.float32)
            out=convolve1d(out,weights,axis=axis,mode=mode)
        return cp.clip(cp.rint(out),0,255).astype(original) if original==cp.uint8 else out.astype(original)

    def cvtColor(self,src,code):
        cp=cupy();x=upload(src);original=x.dtype
        if x.dtype==cp.uint8:x=x.astype(cp.float32)/255
        if code==self.cv.COLOR_RGB2GRAY:
            gray=x@cp.asarray([.299,.587,.114],cp.float32)
            return cp.clip(cp.rint(gray*255),0,255).astype(cp.uint8) if original==cp.uint8 else gray.astype(cp.float32)
        if code==self.cv.COLOR_RGB2LAB:
            rgb=cp.clip(x,0,1);rgb=cp.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
            xyz=rgb@cp.asarray([[.412453,.357580,.180423],[.212671,.715160,.072169],[.019334,.119193,.950227]],cp.float32).T
            xyz/=cp.asarray([.950456,1,1.088754],cp.float32)
            f=cp.where(xyz>.008856,cp.cbrt(cp.maximum(xyz,0)),7.787*xyz+16/116)
            return cp.stack([116*f[:,:,1]-16,500*(f[:,:,0]-f[:,:,1]),200*(f[:,:,1]-f[:,:,2])],axis=-1).astype(cp.float32)
        if code==self.cv.COLOR_LAB2RGB:
            fy=(x[:,:,0]+16)/116;fx=fy+x[:,:,1]/500;fz=fy-x[:,:,2]/200
            f=cp.stack([fx,fy,fz],axis=-1);xyz=cp.where(f>.206893,f**3,(f-16/116)/7.787)
            xyz*=cp.asarray([.950456,1,1.088754],cp.float32)
            rgb=xyz@cp.asarray([[3.240479,-1.53715,-.498535],[-.969256,1.875991,.041556],[.055648,-.204043,1.057311]],cp.float32).T
            rgb=cp.where(rgb<=.0031308,rgb*12.92,1.055*cp.maximum(rgb,0)**(1/2.4)-.055)
            return cp.clip(rgb,0,1).astype(cp.float32)
        raise RuntimeError('GPU 色彩转换尚未实现：'+str(code))

    def remap(self,src,map1,map2,interpolation,borderMode=None,borderValue=0):
        cp=cupy();src=upload(src);mx=upload(map1).astype(cp.float32);my=upload(map2).astype(cp.float32)
        h,w=src.shape[:2];mode=self.cv.BORDER_CONSTANT if borderMode is None else borderMode
        original=src.dtype;channels=1 if src.ndim==2 else src.shape[2]
        out=cp.zeros(mx.shape+(channels,),cp.float32)
        def sample(xx,yy):
            valid=(xx>=0)&(xx<w)&(yy>=0)&(yy<h)
            if mode==self.cv.BORDER_CONSTANT:
                xx=cp.clip(xx,0,w-1);yy=cp.clip(yy,0,h-1)
            else:
                m=1 if mode==self.cv.BORDER_REPLICATE else 2 if mode==self.cv.BORDER_REFLECT else 4
                xx=_border(xx,w,m);yy=_border(yy,h,m)
            value=src[yy,xx];value=value[:,:,None] if channels==1 and src.ndim==2 else value
            if mode==self.cv.BORDER_CONSTANT:value=cp.where(valid[:,:,None],value,cp.asarray(borderValue,cp.float32))
            return value
        if interpolation==self.cv.INTER_NEAREST:
            out=sample(cp.rint(mx).astype(cp.int32),cp.rint(my).astype(cp.int32)).astype(cp.float32)
        elif interpolation==self.cv.INTER_LINEAR:
            # OpenCV 5 float images use continuous linear weights; older builds
            # and integer images use the 1/32 interpolation table.
            if int(self.cv.__version__.split('.')[0])<5 or original==cp.uint8:
                mx=cp.rint(mx*32)/32;my=cp.rint(my*32)/32
            ix=cp.floor(mx).astype(cp.int32);iy=cp.floor(my).astype(cp.int32);fx=mx-ix;fy=my-iy
            for dx,dy,weight in ((0,0,(1-fx)*(1-fy)),(1,0,fx*(1-fy)),(0,1,(1-fx)*fy),(1,1,fx*fy)):
                out+=sample(ix+dx,iy+dy)*weight[:,:,None]
        else:raise RuntimeError('GPU 重采样插值尚未实现：'+str(interpolation))
        if original==cp.uint8:out=cp.clip(cp.rint(out),0,255)
        if src.ndim==2:out=out[:,:,0]
        return out.astype(original)

    def resize(self,src,dsize,fx=0,fy=0,interpolation=None):
        cp=cupy();src=upload(src);h,w=src.shape[:2];ow,oh=map(int,dsize)
        if ow<=0:ow=max(1,round(w*fx))
        if oh<=0:oh=max(1,round(h*fy))
        if (ow,oh)==(w,h):return src.copy()
        interpolation=self.cv.INTER_LINEAR if interpolation is None else interpolation
        source=cp.ascontiguousarray(src,dtype=cp.float32);channels=1 if src.ndim==2 else src.shape[2]
        out=cp.empty((oh,ow,channels),cp.float32)
        kernel=raw_kernel('aura_resize',r'''
        __device__ float cubic(float x){x=fabsf(x);float a=-.75f;return x<1?(a+2)*x*x*x-(a+3)*x*x+1:x<2?a*x*x*x-5*a*x*x+8*a*x-4*a:0;}
        __device__ float sinc(float x){if(fabsf(x)<1e-6f)return 1;float p=3.14159265358979323846f*x;return sinf(p)/p;}
        extern "C" __global__ void aura_resize(const float* s,float* o,int h,int w,int oh,int ow,int channels,int mode){
          int i=blockDim.x*blockIdx.x+threadIdx.x;if(i>=oh*ow*channels)return;
          int c=i%channels,x=(i/channels)%ow,y=i/(channels*ow);float sx=(float)w/ow,sy=(float)h/oh,value=0,total=0;
          if(mode==0){int xx=min(w-1,(int)(x*sx)),yy=min(h-1,(int)(y*sy));o[i]=s[(yy*w+xx)*channels+c];return;}
          if(mode==3 && sx>=1 && sy>=1){
            float x0=x*sx,x1=(x+1)*sx,y0=y*sy,y1=(y+1)*sy;
            for(int yy=(int)floorf(y0);yy<(int)ceilf(y1);yy++)for(int xx=(int)floorf(x0);xx<(int)ceilf(x1);xx++){
              float weight=fmaxf(0,fminf(x1,xx+1.f)-fmaxf(x0,(float)xx))*fmaxf(0,fminf(y1,yy+1.f)-fmaxf(y0,(float)yy));
              value+=s[(min(h-1,yy)*w+min(w-1,xx))*channels+c]*weight;
            }o[i]=value/(sx*sy);return;
          }
          float xx=(x+.5f)*sx-.5f,yy=(y+.5f)*sy-.5f;int ix=(int)floorf(xx),iy=(int)floorf(yy);
          int radius=mode==2?2:mode==4?4:1;
          for(int dy=1-radius;dy<=radius;dy++)for(int dx=1-radius;dx<=radius;dx++){
            float ax=xx-(ix+dx),ay=yy-(iy+dy);
            float wx=mode==2?cubic(ax):mode==4?(fabsf(ax)<4?sinc(ax)*sinc(ax/4):0):fmaxf(0,1-fabsf(ax));
            float wy=mode==2?cubic(ay):mode==4?(fabsf(ay)<4?sinc(ay)*sinc(ay/4):0):fmaxf(0,1-fabsf(ay));
            float weight=wx*wy;value+=s[(max(0,min(h-1,iy+dy))*w+max(0,min(w-1,ix+dx)))*channels+c]*weight;total+=weight;
          }o[i]=value/fmaxf(total,1e-8f);
        }''')
        if interpolation not in (self.cv.INTER_NEAREST,self.cv.INTER_LINEAR,self.cv.INTER_CUBIC,self.cv.INTER_AREA,self.cv.INTER_LANCZOS4):raise RuntimeError('Unsupported GPU resize interpolation.')
        kernel(((out.size+255)//256,),(256,),(source,out,h,w,oh,ow,channels,int(interpolation)))
        if src.dtype==cp.uint8:out=cp.clip(cp.rint(out),0,255)
        return (out[:,:,0] if src.ndim==2 else out).astype(src.dtype)

    def bilateralFilter(self,src,d,sigmaColor,sigmaSpace,borderType=None):
        cp=cupy();src=upload(src);original=src.dtype;source=cp.ascontiguousarray(src,dtype=cp.float32)
        h,w=src.shape[:2];channels=1 if src.ndim==2 else src.shape[2]
        if channels not in (1,3):raise RuntimeError('GPU bilateral requires one or three channels.')
        radius=max(1,int(round(float(sigmaSpace)*1.5)) if d<=0 else int(d)//2)
        out=cp.empty_like(source);mode=1 if borderType==self.cv.BORDER_REPLICATE else 4
        kernel=raw_kernel('aura_bilateral',r'''
        __device__ int reflect(int p,int n,int mode){if(mode==1)return max(0,min(n-1,p));if(n==1)return 0;int m=2*n-2;p=((p%m)+m)%m;return p<n?p:m-p;}
        extern "C" __global__ void aura_bilateral(const float* s,float* o,int h,int w,int c,int r,float color,float space,int mode){
          int p=blockDim.x*blockIdx.x+threadIdx.x;if(p>=h*w)return;int x=p%w,y=p/w;float sums[3]={0,0,0},total=0;
          for(int dy=-r;dy<=r;dy++)for(int dx=-r;dx<=r;dx++){
            if(dx*dx+dy*dy>r*r)continue;int q=(reflect(y+dy,h,mode)*w+reflect(x+dx,w,mode))*c;float diff=0;
            for(int k=0;k<c;k++)diff+=fabsf(s[q+k]-s[p*c+k]);
            float weight=expf(-.5f*diff*diff/(color*color)-.5f*(dx*dx+dy*dy)/(space*space));
            total+=weight;for(int k=0;k<c;k++)sums[k]+=weight*s[q+k];
          }for(int k=0;k<c;k++)o[p*c+k]=sums[k]/fmaxf(total,1e-20f);
        }''')
        kernel(((h*w+127)//128,),(128,),(source,out,h,w,channels,radius,np.float32(max(float(sigmaColor),1e-6)),np.float32(max(float(sigmaSpace),1e-6)),mode))
        if original==cp.uint8:out=cp.clip(cp.rint(out),0,255)
        return out.astype(original)

    def connectedComponentsWithStats(self,src,connectivity=8):
        cp=cupy();from cupyx.scipy.ndimage import label
        source=upload(src)!=0;structure=cp.ones((3,3),cp.int32) if connectivity==8 else cp.asarray([[0,1,0],[1,1,1],[0,1,0]],cp.int32)
        labels,n=label(source,structure=structure);count=int(n)+1;h,w=source.shape
        stats=cp.empty((count,5),cp.int32);stats[:,0]=w;stats[:,1]=h;stats[:,2:4]=0;stats[:,4]=0
        sums=cp.zeros((count,2),cp.float64)
        kernel=raw_kernel('aura_component_stats',r'''
        extern "C" __global__ void aura_component_stats(const int* l,int* s,double* sums,int h,int w){
          int p=blockDim.x*blockIdx.x+threadIdx.x;if(p>=h*w)return;int id=l[p],x=p%w,y=p/w;
          atomicMin(s+id*5,x);atomicMin(s+id*5+1,y);atomicMax(s+id*5+2,x);atomicMax(s+id*5+3,y);atomicAdd(s+id*5+4,1);
          atomicAdd(sums+id*2,(double)x);atomicAdd(sums+id*2+1,(double)y);
        }''')
        kernel(((source.size+255)//256,),(256,),(labels.astype(cp.int32),stats,sums,h,w))
        stats[:,2]-=stats[:,0]-1;stats[:,3]-=stats[:,1]-1;centers=sums/cp.maximum(stats[:,4:5],1)
        return count,labels,download(stats,'compact connected-component metadata'),download(centers,'compact connected-component metadata')

    def getRotationMatrix2D(self,center,angle,scale):return self.cv.getRotationMatrix2D(center,angle,scale)

    def warpAffine(self,src,matrix,dsize,flags=None,borderMode=None,borderValue=0):
        cp=cupy();w,h=dsize
        # Matrix inversion is six scalar configuration values. Match the CPU
        # reference's fixed-point coordinate construction on the device raster.
        inverse=self.cv.invertAffineTransform(np.asarray(download(matrix,'six affine configuration scalars'),np.float64))
        xx=cp.arange(w,dtype=cp.float64)[None,:];yy=cp.arange(h,dtype=cp.float64)[:,None]
        if int(self.cv.__version__.split('.')[0])>=5 and upload(src).dtype!=cp.uint8:
            mx=(inverse[0,0]*xx+inverse[0,1]*yy+inverse[0,2]).astype(cp.float32);my=(inverse[1,0]*xx+inverse[1,1]*yy+inverse[1,2]).astype(cp.float32)
        else:
            adelta=cp.rint(inverse[0,0]*xx*1024).astype(cp.int32);bdelta=cp.rint(inverse[1,0]*xx*1024).astype(cp.int32)
            xbase=cp.rint((inverse[0,1]*yy+inverse[0,2])*1024).astype(cp.int32)+16
            ybase=cp.rint((inverse[1,1]*yy+inverse[1,2])*1024).astype(cp.int32)+16
            mx=((xbase+adelta)>>5).astype(cp.float32)/32;my=((ybase+bdelta)>>5).astype(cp.float32)/32
        return self.remap(src,mx,my,self.cv.INTER_LINEAR if flags is None else flags,borderMode,borderValue)

    def distanceTransform(self,src,distanceType,maskSize):
        from cupyx.scipy.ndimage import distance_transform_edt
        return distance_transform_edt(upload(src)!=0).astype(cupy().float32)

    def Sobel(self,src,ddepth,dx,dy,ksize=3,scale=1,delta=0,borderType=None):
        cp=cupy();from cupyx.scipy.ndimage import convolve1d
        if ksize not in (1,3):raise RuntimeError('GPU Sobel supports ksize 1/3.')
        out=upload(src).astype(cp.float32)
        for axis,deriv in ((1,dx),(0,dy)):
            kernel=[1,0,-1] if deriv==1 else [1,-2,1] if deriv==2 else [1,2,1] if ksize==3 else [1]
            if len(kernel)>1:out=convolve1d(out,cp.asarray(kernel,cp.float32),axis=axis,mode='mirror')
        return out*scale+delta

    def findNonZero(self,mask):
        cp=cupy();yx=cp.argwhere(upload(mask)!=0)
        return None if len(yx)==0 else yx[:,::-1].astype(cp.int32)[:,None,:]

    def boundingRect(self,points):
        p=upload(points).reshape(-1,2);lo=p.min(0);hi=p.max(0)
        x,y=map(int,download(lo,'compact geometry bounds'));z,t=map(int,download(hi,'compact geometry bounds'))
        return x,y,z-x+1,t-y+1

    def getStructuringElement(self,shape,ksize):
        # Kernel construction is scalar configuration, not image rendering.
        return self.cv.getStructuringElement(shape,ksize)

    def dilate(self,src,kernel,iterations=1):return self._morph(src,kernel,iterations,True)
    def erode(self,src,kernel,iterations=1):return self._morph(src,kernel,iterations,False)
    def _morph(self,src,kernel,iterations,maximum):
        from cupyx.scipy.ndimage import maximum_filter,minimum_filter
        cp=cupy();out=upload(src);footprint=upload(kernel).astype(bool)
        for _ in range(iterations):out=(maximum_filter if maximum else minimum_filter)(out,footprint=footprint,mode='constant',cval=0 if maximum else 255)
        return out

    def morphologyEx(self,src,operation,kernel):
        if operation==self.cv.MORPH_OPEN:return self.dilate(self.erode(src,kernel),kernel)
        if operation==self.cv.MORPH_CLOSE:return self.erode(self.dilate(src,kernel),kernel)
        raise RuntimeError('GPU morphology operation not implemented.')

    def floodFill(self,image,mask,seedPoint,newVal,loDiff=0,upDiff=0,flags=4):
        cp=cupy();from cupyx.scipy.ndimage import label
        if mask is not None or loDiff!=0 or upDiff!=0:raise RuntimeError('GPU flood fill currently supports exact-value regions without an external mask.')
        value=upload(image);x,y=map(int,seedPoint)
        same=value==value[y,x]
        structure=cp.ones((3,3),cp.int32) if flags&255==8 else cp.asarray([[0,1,0],[1,1,1],[0,1,0]],cp.int32)
        regions,_=label(same,structure=structure);ident=int(regions[y,x]);selected=regions==ident
        count=int(selected.sum());value[selected]=newVal
        if not is_device(image):image[:]=download(value,'mask editing boundary')
        external=cp.pad(selected.astype(cp.uint8),1,mode='constant',constant_values=1)
        rect=self.boundingRect(self.findNonZero(selected.astype(cp.uint8))) if count else (0,0,0,0)
        return count,value,external,rect


NP=NumpyCUDA();CV=CvCUDA()


class FrameStats:
    def __enter__(self):
        self.old=getattr(_tls,'stats',None)
        self.data=dict(uploads=0,downloads=0,upload_bytes=0,download_bytes=0,host_boundaries=Counter(),stages=Counter())
        _tls.stats=self.data;self.start=time.perf_counter();return self.data
    def __exit__(self,*_):
        cupy().cuda.get_current_stream().synchronize()
        self.data['seconds']=time.perf_counter()-self.start;_tls.stats=self.old


def mark_stage(name):
    stats=getattr(_tls,'stats',None)
    if stats is not None:stats['stages'][name]+=1


class FFTCUDA:
    def dstn(self,data,type=1,axes=None):
        if type!=1:raise ValueError('GPU Poisson expects DST-I.')
        cp=cupy();result=upload(data);axes=tuple(range(result.ndim)) if axes is None else axes
        for axis in axes:
            n=result.shape[axis];shape=list(result.shape);shape[axis]=2*(n+1)
            extended=cp.zeros(shape,dtype=result.dtype);index=[slice(None)]*result.ndim;index[axis]=slice(1,n+1)
            extended[tuple(index)]=result;index[axis]=slice(n+2,None);extended[tuple(index)]=-cp.flip(result,axis=axis)
            index[axis]=slice(1,n+1);result=-cp.fft.fft(extended,axis=axis).imag[tuple(index)]
        return result
    def idstn(self,data,type=1,axes=None):
        axes=tuple(range(data.ndim)) if axes is None else axes
        return self.dstn(data,type,axes)/np.prod([2*(data.shape[a]+1) for a in axes])
