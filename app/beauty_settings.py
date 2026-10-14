"""Versioned controls shared by UI, recipes and per-person state."""
from feature_catalog import ADVANCED
from reshape_settings import RESHAPE,SMART
BASE={'repair':75,'smooth':0,'whiten':0,'texture':50,'wrinkles':0,'dark_circles':0,'slim':0}
EXTRA=[('even_light','明暗平整',0,100),('low_smooth','低频磨皮',0,100),('skin_even','肤色均匀',0,100),
 ('oil','减淡油光',0,100),('gloss','光泽度',-100,100),('clarity','皮肤清晰度',-100,100),
 ('redness','皮肤红润（旧配置兼容）',-100,100),('skin_temp','肤色色温',-100,100),('skin_tint','肤色红润 / 色调',-200,200),
 ('skin_translucent','肤色透亮',0,100),('skin_hydrate','水润柔化',0,100),
 ('skin_fill','面部补光',0,100),('skin_shadow','柔化面部阴影',0,100),('skin_match','向多人共同肤色靠拢',0,100)]
ZONES=[('wr_forehead','抬头纹',0,100),('wr_glabella','眉间纹',0,100),('wr_eyes','眼周纹（含眼下细纹）',0,100),
 ('wr_naso_left','法令纹 · 人物左侧',0,100),('wr_naso_right','法令纹 · 人物右侧',0,100),('wr_mouth','嘴周纹',0,100),
 ('wr_nose','鼻背纹',0,100),('wr_cheek','脸颊纹',0,100),('wr_marionette','木偶纹',0,100)]
DEFAULTS=dict(BASE,**{n:0 for n,_,_,_ in EXTRA+ZONES+ADVANCED+RESHAPE+SMART})
RANGES={n:(0,100) for n in BASE};RANGES.update({n:(lo,hi) for n,_,lo,hi in EXTRA+ZONES+ADVANCED+RESHAPE+SMART})
NAMES=tuple(DEFAULTS)

def neutral_values():
    # Texture 50 is identity. Repair 75 is a historical UI default, not neutral.
    return dict(DEFAULTS,repair=0,smooth=0,whiten=0,texture=50)
def normalized(values):
    # Keep the serialized schema readable, but retired controls cannot run hidden.
    result=dict(DEFAULTS,**{k:v for k,v in values.items() if k in DEFAULTS and k not in ('wrinkles','dark_circles','slim','double_chin','armpit_left','armpit_right')})
    # Both old sliders added the same LAB offset. Fold once, retaining their
    # combined range so existing projects keep exactly the same colour.
    for old,new in (('redness','skin_tint'),('body_redness','body_tint')):
        result[new]=max(-200,min(200,result.get(new,0)+result.get(old,0)))
        result[old]=0
    return result
