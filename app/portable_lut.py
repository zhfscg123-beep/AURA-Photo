"""Bounded, lossless float32 LUT packets for portable presets and projects."""
import base64,hashlib,zlib
from functools import lru_cache
import numpy as np


@lru_cache(maxsize=16)
def _decode(size,encoded,checksum):
    if type(size) is not int or not 2<=size<=33:raise ValueError('LUT尺寸无效。')
    expected=size**3*3*4
    if not isinstance(encoded,str) or len(encoded)>600000:raise ValueError('压缩LUT过大。')
    if not isinstance(checksum,str) or len(checksum)!=64:raise ValueError('LUT校验格式无效。')
    try:
        compressed=base64.b64decode(encoded,validate=True);stream=zlib.decompressobj()
        raw=stream.decompress(compressed,expected+1)
    except (ValueError,zlib.error) as e:raise ValueError('压缩LUT无效。') from e
    if len(raw)!=expected or not stream.eof or stream.unused_data or stream.unconsumed_tail:raise ValueError('压缩LUT尺寸不符。')
    if hashlib.sha256(raw).hexdigest()!=checksum:raise ValueError('LUT内容校验失败。')
    cube=np.frombuffer(raw,dtype='<f4').reshape(size,size,size,3)
    if not np.isfinite(cube).all() or np.max(np.abs(cube))>8:raise ValueError('LUT输出范围无效。')
    cube.flags.writeable=False;return cube


def array(lut):
    if lut.get('encoding')=='zlib-f32le':return _decode(lut['size'],lut['data'],lut['data_sha256'])
    if 'encoding' in lut:raise ValueError('LUT编码不支持。')
    return np.asarray(lut['cube'],np.float32)


def pack(lut):
    if lut is None:return None
    if lut.get('encoding')=='zlib-f32le':array(lut);return dict(lut)
    cube=array(lut);size=lut['size']
    if type(size) is not int or not 2<=size<=33 or cube.shape!=(size,size,size,3):raise ValueError('LUT尺寸无效。')
    raw=cube.astype('<f4').tobytes()
    out={k:v for k,v in lut.items() if k!='cube'}
    out.update(encoding='zlib-f32le',data=base64.b64encode(zlib.compress(raw,6)).decode('ascii'),data_sha256=hashlib.sha256(raw).hexdigest())
    array(out);return out


def mix_effects(base,a,target,b,t):
    """Interpolate rendered LUT effects, including a previous different LUT."""
    import creative_color as color
    a=a/100 if base else 0;b=b/100 if target else 0
    if a==0 and target is not None and 0<=b*t<=1:return pack(target),b*t*100
    n=max(base['size'] if base else 2,target['size'] if target else 2)
    z,y,x=np.meshgrid(np.linspace(0,1,n,dtype=np.float32),np.linspace(0,1,n,dtype=np.float32),np.linspace(0,1,n,dtype=np.float32),indexing='ij')
    grid=np.stack((x,y,z),axis=3);flat=grid.reshape(n*n,n,3)
    start=flat if not base or a==0 else flat+(color.lut_apply(flat,base)-flat)*a
    end=flat if not target or b==0 else flat+(color.lut_apply(flat,target)-flat)*b
    cube=(start+(end-start)*t).reshape(n,n,n,3)
    return pack(dict(size=n,cube=cube,min=[0,0,0],max=[1,1,1],name=target.get('name','LUT混合') if target else 'LUT混合',sha256=hashlib.sha256(cube.tobytes()).hexdigest())),100.
