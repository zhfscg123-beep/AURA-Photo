"""Portable bounded settings for the independent photographic develop process."""
EXTRA=[('wb_kelvin','色温 K',2000,50000,6500),('wb_tint','白平衡偏色',-150,150,0),
 ('midtone_hue','中间调色相',0,360,0),('midtone_color','中间调饱和度',0,100,0),
 ('global_hue','全局分级色相',0,360,0),('global_color','全局分级饱和度',0,100,0),
 ('shadow_luma','阴影分级明度',-100,100,0),('midtone_luma','中间调分级明度',-100,100,0),('highlight_luma','高光分级明度',-100,100,0),
 ('grading_balance','分级平衡',-100,100,0),('grading_blend','分级混合',0,100,50),('grading_warm_protect','暖色分级保护',0,100,0),
 ('curve_saturation','曲线保色',0,100,100),('channel_curve_saturation','通道曲线保色',0,100,0),('hue_stability','低饱和保护',0,100,0),('texture','全图纹理',-100,100,0),('clarity','全图清晰度',-100,100,0),('dehaze','去朦胧',-100,100,0),
 ('denoise_luma','明度降噪',0,100,0),('denoise_chroma','颜色降噪',0,100,0),
 ('sharpen','锐化量',0,150,0),('sharpen_radius','锐化半径',.5,3,1),('sharpen_detail','锐化细节',0,100,25),('sharpen_mask','锐化蒙版',0,100,0),
 ('bw','黑白转换',0,1,0),('cal_red_hue','红原色色相',-100,100,0),('cal_red_sat','红原色饱和度',-100,100,0),
 ('cal_green_hue','绿原色色相',-100,100,0),('cal_green_sat','绿原色饱和度',-100,100,0),('cal_blue_hue','蓝原色色相',-100,100,0),('cal_blue_sat','蓝原色饱和度',-100,100,0),
 ('vignette','后期暗角',-100,100,0),('grain','颗粒',0,100,0),('grain_size','颗粒大小',1,8,2)]
from develop_advanced import CONTROLS as ADVANCED
EXTRA+=ADVANCED
DEFAULTS={k:default for k,_,_,_,default in EXTRA}

def checked_points(records):
    import math
    if not isinstance(records,list) or len(records)>8:raise ValueError('点颜色最多8组。')
    defaults=dict(hue=0,chroma=.1,lightness=.5,hue_range=30,chroma_range=.15,lightness_range=.4,hue_shift=0,saturation=0,luminance=0,variance=0)
    limits=dict(hue=(0,360),chroma=(0,1),lightness=(0,4),hue_range=(1,180),chroma_range=(.01,1),lightness_range=(.01,4),hue_shift=(-100,100),saturation=(-100,100),luminance=(-100,100),variance=(-100,100))
    out=[]
    for record in records:
        if not isinstance(record,dict) or set(record)-set(defaults):raise ValueError('点颜色记录无效。')
        v=dict(defaults,**record)
        for k,(lo,hi) in limits.items():
            x=v[k]
            if type(x) not in (int,float) or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('点颜色范围无效：'+k)
        out.append(v)
    return out
