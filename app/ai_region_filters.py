"""Editable AURA-owned region recipes; masks are never embedded in presets."""
import copy,hashlib,uuid
import cv2,numpy as np
import color_presets as presets
from region_masks import LOCAL_DEFAULTS

NAMES={'person':'AI 人物','sky':'AI 天空','background':'AI 背景'}
ANIME={
 'person':dict(values=dict(exposure=.95,highlights=-95,whites=-20,shadows=35,temperature=-8,tint=-3,saturation=-2,vibrance=4,curve_saturation=45,shadow_hue=235,shadow_color=7,shadow_luma=14,highlight_hue=230,highlight_color=3,grading_blend=70,grading_balance=10),hsl={'橙':[0,-2,8],'黄':[0,-3,5]},point_colors=[dict(hue=50,hue_range=40,chroma=.05,chroma_range=.08,lightness=.50,lightness_range=.3,luminance=40,saturation=-2)],points={'rgb':[[0,0],[.03,.038],[.1,.18],[.25,.40],[.5,.675],[.75,.84],[.9,.935],[1,.975]],'b':[[0,0],[.12,.137],[.35,.365],[.65,.66],[1,1]]}),
 'sky':dict(values=dict(exposure=.15,highlights=-25,whites=-10,contrast=0,saturation=47,vibrance=12,clarity=0,dehaze=10,curve_saturation=20,denoise_chroma=18,denoise_color_smooth=50),hsl={'蓝':[-10,20,-14],'青':[-3,10,-2]},point_colors=[dict(hue=240,hue_range=80,chroma=.025,chroma_range=.045,lightness=.91,lightness_range=.18,saturation=-60,luminance=0),dict(hue=240,hue_range=80,chroma=.12,chroma_range=.07,lightness=.68,lightness_range=.35,luminance=-35,saturation=20)],points={'rgb':[[0,0],[.3,.09],[.5,.23],[.7,.69],[.85,.955],[.95,.993],[1,1]]}),
 'background':dict(values=dict(exposure=.45,highlights=-22,whites=-3,shadows=9,contrast=3,saturation=14,vibrance=7,curve_saturation=100,shadow_hue=185,shadow_color=3,highlight_hue=75,highlight_color=3),hsl={'绿':[18,1,12],'黄':[12,-8,8]},point_colors=[dict(hue=140,hue_range=45,chroma=.09,chroma_range=.12,lightness=.43,lightness_range=.25,hue_shift=28,saturation=-4,luminance=5)],points={'rgb':[[0,0],[.1,.075],[.25,.335],[.5,.66],[.75,.855],[.93,.97],[1,1]]})}
SCHEMES={'xhs-anime-cyan':ANIME}
from reference_region_recipes import SCHEMES as REFERENCE_SCHEMES
SCHEMES.update(REFERENCE_SCHEMES)
from open_reference_region_recipes import SCHEMES as OPEN_REFERENCE_SCHEMES
SCHEMES.update(OPEN_REFERENCE_SCHEMES)
PREPARATIONS={'xhs-anime-cyan':{'sky':dict(values=dict(denoise_chroma=65,denoise_color_smooth=60))}}

def source_key(rgb):return hashlib.sha256(np.ascontiguousarray(rgb).tobytes()).hexdigest()

def apply_recipe(layer,recipe,preset_id,amount,source_rgb=None,exposure=0):
    if source_rgb is not None and preset_id in REFERENCE_SCHEMES and layer.get('mask_alpha') is not None:
        from reference_region_recipes import REFERENCE_LIGHTNESS
        from regional_adaptation import adapted
        kind=layer['ai_region']['kind'];recipe,_=adapted(recipe,REFERENCE_LIGHTNESS.get(preset_id,{}).get(kind),source_rgb,layer['mask_alpha'],kind,exposure)
    recipe=copy.deepcopy(recipe);recipe.setdefault('values',{})['hue_stability']=100
    recipe=presets.checked_recipe(recipe);layer['color_process']=2;layer['color_recipe']=copy.deepcopy(recipe)
    geometry={key:layer['parameters'][key] for key in ('feather','expand','opacity','edge_protect') if key in layer['parameters']}
    layer['parameters']=dict(LOCAL_DEFAULTS,**{key:value for key,value in recipe.get('values',{}).items() if key in LOCAL_DEFAULTS},**geometry)
    layer['filter_link']=dict(id=preset_id,amount=float(amount))
    kind=layer['ai_region']['kind'];pre=PREPARATIONS.get(preset_id,{}).get(kind)
    if pre:layer['color_preparation']=presets.checked_recipe(pre)
    else:layer.pop('color_preparation',None)
    return layer

def create_layers(masks,shape,source,models,kinds=None):
    result=[];h,w=shape
    for kind in kinds or NAMES:
        prob=masks[kind]
        if prob.max()<128 or np.count_nonzero(prob>128)<max(4,prob.size*.0001):continue
        mask=cv2.resize(prob,(w,h),interpolation=cv2.INTER_LINEAR)>0
        parameters=dict(LOCAL_DEFAULTS)
        if kind=='person':parameters['edge_protect']=60.
        result.append(dict(id='ai-'+uuid.uuid4().hex,name=NAMES[kind],enabled=True,color_process=2,mask=mask,mask_alpha=prob.copy(),parameters=parameters,ai_region=dict(kind=kind,source=source,models=list(models))))
    return result

def sync_linked(layers,preset_id,amount):
    for layer in layers:
        link=layer.get('filter_link')
        if link is not None:link['amount']=float(amount) if link['id']==preset_id else 0.
