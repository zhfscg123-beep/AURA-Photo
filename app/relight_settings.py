"""Strict portable per-person light rig; no model/UI dependencies."""
import copy,math

REVISION=1
TYPES={'柔面光':'area','点光':'point','方向光':'directional','后轮廓光':'back'}
TYPE_LABELS={v:k for k,v in TYPES.items()}
SCOPES={'面部与身体皮肤':'skin','人物轮廓与衣物':'person'}
SCOPE_LABELS={v:k for k,v in SCOPES.items()}
DEFAULTS=dict(enabled=True,type='area',scope='skin',power=.35,x=-.75,y=.65,z=1.1,
    size=.7,softness=65,diffuse_wrap=.12,specular_strength=.08,roughness=.85,
    temperature=0,tint=0,saturation=.5,color_mix=.6,lip_receive=.8,brow_receive=.8,
    color=[255,255,255],rim_gain=1,rim_width=.008,range=3,
    shadow_priority=.35,highlight_protect=.4,geometry_protect=.5,occlusion=True)
LIMITS={'power':(0,20),'x':(-3,3),'y':(-3,3),'z':(-3,3),'size':(.01,2),'softness':(0,100),
    'diffuse_wrap':(0,.5),'specular_strength':(0,1),'roughness':(.12,1),'temperature':(-100,100),
    'tint':(-100,100),'saturation':(0,1),'color_mix':(0,1),'lip_receive':(0,1),'brow_receive':(0,1),
    'rim_gain':(0,5),'rim_width':(.002,.2),'range':(.05,10),
    'shadow_priority':(0,1),'highlight_protect':(0,1),'geometry_protect':(0,1)}

def lamp(index=0):
    v=copy.deepcopy(DEFAULTS);v['name']='主光' if index==0 else '补光' if index==1 else '轮廓光' if index==2 else f'光源{index+1}'
    if index==1:v.update(x=.65,y=.15,z=1,power=.12,size=.6,temperature=-5,color_mix=.5)
    elif index==2:v.update(type='back',scope='person',x=.65,y=.5,z=-.6,power=.6,occlusion=False)
    return v

def defaults():return dict(revision=REVISION,enabled=False,selected=0,lights=[lamp(i) for i in range(3)])

SECTION_FIELDS={
    'relight_position':('x','y','z','size'),
    'relight_material':('specular_strength','roughness','diffuse_wrap','lip_receive','brow_receive','rim_gain','rim_width'),
    'relight_protection':('shadow_priority','highlight_protect','geometry_protect','occlusion'),
}

def reset_section(value,scope):
    rig=copy.deepcopy(checked(value));index=rig['selected'];light=rig['lights'][index]
    default=lamp(index)
    # A back light must remain behind the subject even when its slot moved.
    if light['type']=='back':default['z']=-.6
    elif default['z']<0:default['z']=DEFAULTS['z']
    for key in SECTION_FIELDS[scope]:light[key]=copy.deepcopy(default[key])
    return checked(rig)

def checked_lamp(value,index=0):
    if not isinstance(value,dict):raise ValueError('补光光源记录无效。')
    v=dict(DEFAULTS,**{k:value[k] for k in DEFAULTS if k in value})
    v['name']=value.get('name',f'光源{index+1}')
    if not isinstance(v['name'],str) or not 1<=len(v['name'])<=30:raise ValueError('光源名称无效。')
    if type(v['enabled']) is not bool or type(v['occlusion']) is not bool or v['type'] not in TYPE_LABELS or v['scope'] not in SCOPE_LABELS:raise ValueError('光源类型或范围无效。')
    for key,(lo,hi) in LIMITS.items():
        x=v[key]
        if type(x) not in [int,float] or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('光源参数无效：'+key)
    if v['type']=='back' and v['z']>=0:raise ValueError('后轮廓光必须放在人物背后，深度应小于0。')
    color=v['color']
    if not isinstance(color,list) or len(color)!=3 or any(type(x) not in [int,float] or not math.isfinite(x) or not 0<=x<=255 for x in color):raise ValueError('灯光颜色无效。')
    v['color']=color.copy();return v

def checked(value):
    if value is None:return defaults()
    if not isinstance(value,dict) or value.get('revision')!=REVISION or type(value.get('enabled')) is not bool:raise ValueError('几何补光记录版本无效。')
    lights=value.get('lights')
    if not isinstance(lights,list) or not 1<=len(lights)<=5:raise ValueError('每个人物需有1–5盏光源。')
    selected=value.get('selected',0)
    if type(selected) is not int or not 0<=selected<len(lights):raise ValueError('所选光源编号无效。')
    return dict(revision=REVISION,enabled=value['enabled'],selected=selected,lights=[checked_lamp(v,i) for i,v in enumerate(lights)])

def active(value):
    v=checked(value)
    return v['enabled'] and any(x['enabled'] and x['power']>0 for x in v['lights'])

def renderer_lamp(value):
    v=checked_lamp(value)
    result={k:v[k] for k in ['enabled','type','scope','power','size','softness','diffuse_wrap','specular_strength','roughness',
        'temperature','tint','saturation','color_mix','lip_receive','brow_receive','rim_gain','rim_width','range',
        'shadow_priority','highlight_protect','geometry_protect','occlusion']}
    result.update(position=[v['x'],v['y'],v['z']],color_hex='#'+''.join(f'{round(c):02X}' for c in v['color']),
        area_grid=4,hair_gloss=0,hair_transmission=0)
    return result

def from_legacy(value):
    rig=defaults();level=float(value.get('light',0))
    if level!=0:
        rig['enabled']=True;rig['lights'][0]['power']=min(20,abs(level)/100)
        rig['lights'][0]['softness']=value.get('light_softness',65)
        rig['lights'][0]['temperature']=value.get('light_temp',0)
        for x in rig['lights'][1:]:x['enabled']=False
    return rig
