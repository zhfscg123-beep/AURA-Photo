"""AURA NumPy-only adapters for the reviewed 2D float DST solver.

DST-I uses an odd FFT extension; mirror correlation uses reflected edge samples.
No additional binary dependency is introduced into the offline runtime.
"""
from types import SimpleNamespace
import numpy as np

def dstn(data,type=1,axes=None):
    if type!=1:raise ValueError('Only DST-I is supported.')
    result=np.asarray(data)
    axes=tuple(range(result.ndim)) if axes is None else axes
    for axis in axes:
        n=result.shape[axis];shape=list(result.shape);shape[axis]=2*(n+1)
        extended=np.zeros(shape,dtype=result.dtype)
        indices=[slice(None)]*result.ndim;indices[axis]=slice(1,n+1);extended[tuple(indices)]=result
        indices[axis]=slice(n+2,None);extended[tuple(indices)]=-np.flip(result,axis=axis)
        indices[axis]=slice(1,n+1)
        result=-np.fft.fft(extended,axis=axis).imag[tuple(indices)]
    return result

def idstn(data,type=1,axes=None):
    axes=tuple(range(data.ndim)) if axes is None else axes
    result=dstn(data,type,axes)
    return result/np.prod([2*(data.shape[a]+1) for a in axes])

def correlate1d(data,weights,axis=0,mode='mirror'):
    if mode!='mirror':raise ValueError('Only whole-sample symmetric borders are supported.')
    radius=len(weights)//2;pad=[(0,0)]*data.ndim;pad[axis]=(radius,radius)
    padded=np.pad(data,pad,mode='reflect');result=np.zeros_like(data)
    for i,value in enumerate(weights):
        if value:
            index=[slice(None)]*data.ndim;index[axis]=slice(i,i+data.shape[axis])
            result+=padded[tuple(index)]*float(value)
    return result

def correlate(data,weights,mode='mirror'):
    if mode!='mirror':raise ValueError('Only whole-sample symmetric borders are supported.')
    pad=[(size//2,size//2) for size in weights.shape]
    padded=np.pad(data,pad,mode='reflect');result=np.zeros_like(data)
    for index in np.ndindex(weights.shape):
        value=weights[index]
        if value:
            area=tuple(slice(i,i+size) for i,size in zip(index,data.shape))
            result+=padded[area]*float(value)
    return result

fft=SimpleNamespace(dstn=dstn,idstn=idstn)
ndimage=SimpleNamespace(correlate=correlate,correlate1d=correlate1d)
