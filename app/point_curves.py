"""Bounded piecewise cubic Hermite curves with exact identity bypass."""
import numpy as np
from functools import lru_cache
IDENTITY=[[0.,0.],[1.,1.]]
def checked(data):
    if not isinstance(data,dict) or set(data)-{'rgb','r','g','b'}:raise ValueError('曲线通道无效')
    out={}
    for channel,pts in data.items():
        if not isinstance(pts,(list,tuple)):raise ValueError('曲线控制点无效')
        a=np.asarray(pts,float)
        if not 2<=len(a)<=64 or a.shape!=(len(a),2) or not np.isfinite(a).all() or np.any(a<0) or np.any(a>1) or a[0,0]!=0 or a[-1,0]!=1 or np.any(np.diff(a[:,0])<.002):raise ValueError('曲线控制点无效')
        out[channel]=a.tolist()
    return out
def active(points):return bool(points) and any(abs(x-y)>1e-8 for x,y in points)
def evaluate(x,points):
    a=np.asarray(points,float);xx,yy=a[:,0],a[:,1];h=np.diff(xx);delta=np.diff(yy)/h;m=np.zeros(len(a));m[0]=delta[0];m[-1]=delta[-1]
    for i in range(1,len(a)-1):
        if delta[i-1]*delta[i]>0:
            w1=2*h[i]+h[i-1];w2=h[i]+2*h[i-1];m[i]=(w1+w2)/(w1/delta[i-1]+w2/delta[i])
    x=np.clip(np.asarray(x),0,1);idx=np.clip(np.searchsorted(xx,x,side='right')-1,0,len(h)-1);t=(x-xx[idx])/h[idx]
    return np.clip((2*t**3-3*t**2+1)*yy[idx]+(t**3-2*t**2+t)*h[idx]*m[idx]+(-2*t**3+3*t**2)*yy[idx+1]+(t**3-t**2)*h[idx]*m[idx+1],0,1)
def apply(rgb,curves):
    if not any(active(p) for p in curves.values()):return rgb
    out=rgb.copy()
    for channel,key in ((None,'rgb'),(0,'r'),(1,'g'),(2,'b')):
        points=curves.get(key,IDENTITY)
        if not active(points):continue
        table=curve_table(tuple(tuple(p) for p in points))
        def transfer(values):
            position=np.clip(values,0,1)*4096;index=position.astype(np.uint16);fraction=position-index
            return table[index]+(table[np.minimum(index+1,4096)]-table[index])*fraction
        if channel is None:out=transfer(out)
        else:out[:,:,channel]=transfer(out[:,:,channel])
    return out
@lru_cache(maxsize=32)
def curve_table(points):
    table=evaluate(np.linspace(0,1,4097),points).astype(np.float32);table.flags.writeable=False;return table
