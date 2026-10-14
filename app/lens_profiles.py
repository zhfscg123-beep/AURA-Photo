"""Bundled Lensfun database and C API for measured lens corrections.

Bindings follow https://lensfun.github.io/manual/v0.3.1/lensfun_8h.html .
No profile is guessed from focal length; automatic selection is exact-name.
"""
from pathlib import Path
from functools import lru_cache
import ctypes,os,threading,xml.etree.ElementTree as ET
import numpy as np
from core import ROOT
_lock=threading.RLock();_dll=None;_db=None;_directory=None

def norm(x):return ''.join(c for c in str(x).casefold() if c.isalnum())

@lru_cache(maxsize=1)
def registry():
    lenses={};cameras={}
    for p in sorted((ROOT/'tools/rawtherapee').rglob('share/lensfun/*.xml')):
        tree=ET.parse(p).getroot()
        for c in tree.findall('camera'):
            cameras[norm(c.findtext('maker','')+' '+c.findtext('model',''))]=float(c.findtext('cropfactor','1'))
        for l in tree.findall('lens'):
            model=l.findtext('model','');maker=l.findtext('maker','')
            if model and l.find('calibration') is not None:
                key=maker+' | '+model
                lenses.setdefault(key,dict(maker=maker,model=model,crop=float(l.findtext('cropfactor','1')),file=str(p)))
    return lenses,cameras

def match(metadata):
    lenses,cameras=registry();make=metadata.get('camera_make','');model=metadata.get('camera_model','');name=metadata.get('lens_model','')
    crop=cameras.get(norm(make+' '+model),cameras.get(norm(model)))
    candidates=[key for key,rec in lenses.items() if norm(name) in (norm(rec['model']),norm(rec['maker']+' '+rec['model'])) or name and norm(rec['model'])==norm(make+' '+name)]
    return (candidates[0] if len(candidates)==1 else None),crop

def library():
    global _dll,_db,_directory
    if _dll is None:
        paths=list((ROOT/'tools/rawtherapee').rglob('liblensfun.dll'))
        if not paths:raise ValueError('缺少Lensfun运行库。')
        path=paths[0];_directory=os.add_dll_directory(str(path.parent));_dll=ctypes.CDLL(str(path))
        V=ctypes.c_void_p;I=ctypes.c_int;F=ctypes.c_float;S=ctypes.c_char_p;A=ctypes.POINTER(V)
        signatures={'lf_db_new':([],V),'lf_db_load_file':([V,S],I),'lf_db_find_lenses_hd':([V,V,S,S,I],A),
            'lf_free':([V],None),'lf_modifier_new':([V,F,I,I],V),'lf_modifier_destroy':([V],None),
            'lf_modifier_initialize':([V,V,I,F,F,F,F,I,I,I],I),
            'lf_modifier_apply_subpixel_geometry_distortion':([V,F,F,I,I,V],I),
            'lf_modifier_apply_color_modification':([V,V,F,F,I,I,I,I],I)}
        for n,(args,result) in signatures.items():getattr(_dll,n).argtypes=args;getattr(_dll,n).restype=result
        _db=_dll.lf_db_new()
        files=sorted(set(rec['file'] for rec in registry()[0].values()))
        for file in files:
            if _dll.lf_db_load_file(_db,file.encode('utf8'))!=0:raise ValueError('镜头配置数据库无法读取。')
    return _dll

def field(key,crop,focal,aperture,w,h):
    rec=registry()[0].get(key)
    if rec is None:raise ValueError('所选镜头配置不存在。')
    with _lock:
        api=library();found=api.lf_db_find_lenses_hd(_db,None,rec['maker'].encode('utf8'),rec['model'].encode('utf8'),0)
        if not found or not found[0]:raise ValueError('Lensfun没有找到所选镜头配置。')
        lens=found[0];api.lf_free(found)
        modifier=api.lf_modifier_new(lens,float(crop),w,h)
        if not modifier:raise ValueError('镜头校正初始化失败。')
        try:
            flags=api.lf_modifier_initialize(modifier,lens,3,float(focal),float(aperture),1000.,1.,1,1|2|8,0)
            yy,xx=np.mgrid[:h,:w].astype(np.float32);identity=np.stack([xx,yy],2)
            coords=np.repeat(identity[:,:,None,:],3,axis=2).copy()
            if flags&(1|8):api.lf_modifier_apply_subpixel_geometry_distortion(modifier,0.,0.,w,h,coords.ctypes.data)
            gain=np.ones((h,w,3),np.float32)
            if flags&2:api.lf_modifier_apply_color_modification(modifier,gain.ctypes.data,0.,0.,w,h,0x654,w*3*4)
            if not np.isfinite(coords).all() or not np.isfinite(gain).all():raise ValueError('镜头校正返回无效坐标。')
            return (coords-identity[:,:,None,:])/np.array([max(1,w-1),max(1,h-1)],np.float32),gain,flags
        finally:api.lf_modifier_destroy(modifier)
