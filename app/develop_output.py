"""Preview/proof and output settings; exports use numerical color conversion."""
import numpy as np
import color_science as cs
DEFAULTS=dict(space='sRGB',hdr=False,monitor='',proof='',proof_enabled=False,gamut_warning=False,hdr_preview=False,intent=1)
EXPORT_KEYS=('space','hdr','intent')

def portable(data):
    value=checked(data);value['monitor']=''
    return value

def synced(target,source):
    value=portable(target);source=checked(source)
    value.update({k:source[k] for k in EXPORT_KEYS})
    return value

def display_profiles(data):
    """A monitor belongs to this computer; absent proofs never block editing."""
    from app_preferences import preferences
    from icc_runtime import profile_bytes
    v=checked(data);monitor=preferences().get('monitor_profile','');notes=[]
    target=cs.icc_profile('sRGB');proof=None;has_monitor=False
    if monitor:
        try:target=profile_bytes(monitor);has_monitor=True
        except (OSError,ValueError):notes.append('显示器ICC不可用，已暂用sRGB显示；可重新选择。')
    if v['proof_enabled']:
        if v['proof']:
            try:proof=profile_bytes(v['proof'])
            except (OSError,ValueError):notes.append('软打样ICC不可用，已暂时停用；输出色彩设置保留。')
        else:notes.append('请先选择软打样ICC；当前显示正常预览。')
    return target,proof,notes,has_monitor

def checked(data):
    if not isinstance(data,dict):raise ValueError('色彩输出设置无效。')
    v=dict(DEFAULTS,**{k:data[k] for k in DEFAULTS if k in data})
    if v['space'] not in cs.SPACES or type(v['intent']) is not int or v['intent'] not in (0,1,2,3):raise ValueError('色彩空间或呈色意图无效。')
    for k in ('hdr','proof_enabled','gamut_warning','hdr_preview'):
        if type(v[k]) is not bool:raise ValueError('输出预览开关无效。')
    for k in ('monitor','proof'):
        if not isinstance(v[k],str) or len(v[k])>1000:raise ValueError('ICC路径无效。')
    return v

def preview(rgb,data):
    v=checked(data)
    target,proof,notes,has_monitor=display_profiles(v)
    if not any((has_monitor,proof is not None,v['gamut_warning'],v['hdr_preview'])):
        return np.clip(np.rint(rgb),0,255).astype(np.uint8)
    linear=cs.decode(rgb/255)
    if v['hdr_preview']:
        y=np.maximum(linear@np.array([.2126,.7152,.0722],np.float32),1e-6)
        # A clearly labelled SDR mapping, not a claim of native HDR monitor output.
        mapped=np.where(y<=.65,y,.65+(y-.65)/(1+(y-.65)/.35));linear*= (mapped/y)[:,:,None]
    working=cs.convert_linear(linear,'sRGB','ProPhoto')
    from icc_runtime import transform
    output=transform(working,cs.icc_profile('ProPhoto',linear=True),target,proof,v['intent'])
    if v['gamut_warning']:
        candidate=cs.encode(cs.convert_linear(linear,'sRGB',v['space']),v['space'])
        invalid=(candidate.min(2)<-.001) if v['hdr'] else (candidate.min(2)<-.001)|(candidate.max(2)>1.001)
        output[invalid]=[1,0,1]
    return np.clip(np.rint(output*255),0,255).astype(np.uint8)

def encoded_output(rgb,space):return cs.encode(cs.convert_linear(cs.decode(rgb/255),'sRGB',space),space)
