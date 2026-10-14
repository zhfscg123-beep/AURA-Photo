"""LittleCMS float transforms using the bundled RawTherapee runtime.

Embedded ICC inputs never pass through an 8-bit Pillow color conversion.
Proof/display transforms operate on a derived preview, not the export buffer.
"""
from pathlib import Path
import ctypes,threading,os
from functools import lru_cache
import numpy as np
from core import ROOT
from color_science import icc_profile
_lock=threading.RLock();_dll=None;_directory=None
RGB_FLOAT=(1<<22)|(4<<16)|(3<<3)|4

def library():
    global _dll,_directory
    if _dll is None:
        candidates=list((ROOT/'tools/rawtherapee').rglob('liblcms2-2.dll'))
        if not candidates:raise ValueError('缺少浮点ICC运行库，请使用完整AURA运行包。')
        path=candidates[0];_directory=os.add_dll_directory(str(path.parent));_dll=ctypes.CDLL(str(path))
        signatures={
          'cmsOpenProfileFromMem':([ctypes.c_void_p,ctypes.c_uint32],ctypes.c_void_p),
          'cmsCloseProfile':([ctypes.c_void_p],ctypes.c_int),
          'cmsCreateTransform':([ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32],ctypes.c_void_p),
          'cmsCreateProofingTransform':([ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32],ctypes.c_void_p),
          'cmsDoTransform':([ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32],None),
          'cmsDeleteTransform':([ctypes.c_void_p],None)}
        for name,(args,result) in signatures.items():getattr(_dll,name).argtypes=args;getattr(_dll,name).restype=result
    return _dll

def profile_bytes(path):
    p=Path(path)
    if p.stat().st_size>4*1024**2:raise ValueError('ICC文件过大。')
    value=p.read_bytes()
    if len(value)<128 or value[36:40]!=b'acsp':raise ValueError('ICC配置格式无效。')
    return value

def transform(rgb,source,destination,proof=None,intent=1):
    rgb=np.ascontiguousarray(rgb,np.float32)
    if rgb.ndim!=3 or rgb.shape[2]!=3 or not np.isfinite(rgb).all():raise ValueError('ICC输入像素无效。')
    with _lock:
        api=library();buffers=[ctypes.create_string_buffer(x) for x in [source,destination]+([proof] if proof else [])]
        handles=[];conversion=None
        try:
            handles=[api.cmsOpenProfileFromMem(b,len(b)-1) for b in buffers]
            if any(not x for x in handles):raise ValueError('ICC配置无法读取。')
            if proof:conversion=api.cmsCreateProofingTransform(handles[0],RGB_FLOAT,handles[1],RGB_FLOAT,handles[2],intent,1,0x4000|0x2000|0x40)
            else:conversion=api.cmsCreateTransform(handles[0],RGB_FLOAT,handles[1],RGB_FLOAT,intent,0x40)
            if not conversion:raise ValueError('ICC配置不支持所选转换；请选择RGB或可用的输出配置。')
            output=np.empty_like(rgb)
            # LCMS count is uint32; process in bounded rows for large photos.
            for a in range(0,len(rgb),192):
                api.cmsDoTransform(conversion,rgb[a:].ctypes.data,output[a:].ctypes.data,min(192,len(rgb)-a)*rgb.shape[1])
            if not np.isfinite(output).all():raise ValueError('ICC转换返回无效像素。')
            return output
        finally:
            if conversion:api.cmsDeleteTransform(conversion)
            for handle in handles:
                if handle:api.cmsCloseProfile(handle)

def working_from_input(rgb,profile):return transform(rgb,profile,icc_profile('ProPhoto',linear=True))

def monitor_profile():
    if os.name!='nt':return None
    user=ctypes.WinDLL('user32');gdi=ctypes.WinDLL('gdi32')
    user.GetDC.argtypes=[ctypes.c_void_p];user.GetDC.restype=ctypes.c_void_p
    user.ReleaseDC.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    gdi.GetICMProfileW.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.c_wchar_p]
    dc=user.GetDC(None)
    try:
        size=ctypes.c_uint32(32768);buffer=ctypes.create_unicode_buffer(size.value)
        if gdi.GetICMProfileW(dc,ctypes.byref(size),buffer) and Path(buffer.value).is_file():return buffer.value
    finally:user.ReleaseDC(None,dc)
    return None
