"""Array-only develop extensions, shared by CPU reference and CUDA compiler.

No UI, IO, host downloads, or backend selection occurs inside pixel functions.
New controls have neutral defaults; old recipes retain their original results.
"""
import numpy as np
import cv2

CONTROLS=[
 ('curve_shadow','参数曲线阴影',-100,100,0),('curve_dark','参数曲线暗调',-100,100,0),('curve_light','参数曲线亮调',-100,100,0),('curve_highlight','参数曲线高光',-100,100,0),
 ('curve_split_shadow','阴影分界 %',1,97,25),('curve_split_mid','中调分界 %',2,98,50),('curve_split_highlight','高光分界 %',3,99,75),
 ('vignette_midpoint','暗角中点',0,100,25),('vignette_roundness','暗角圆度',-100,100,0),('vignette_feather','暗角羽化',1,100,100),('vignette_highlights','暗角高光保护',0,100,0),('vignette_style','暗角模式',0,2,0),
 ('grain_roughness','颗粒粗糙度',0,100,50),('grain_model','胶片颗粒模式',0,1,0),
 ('denoise_detail','明度细节保留',0,100,0),('denoise_contrast','明度对比保留',0,100,0),('denoise_color_detail','颜色细节保留',0,100,0),('denoise_color_smooth','颜色平滑',0,100,0),
 ('cal_shadow_tint','校准阴影偏色',-100,100,0)]

def ramp(x):
    t=np.clip(x,0,1);return t*t*(3-2*t)

def parametric_curve(x,v):
    """Monotone transfer with user-defined regions and positive log slopes."""
    if not any(v[k] for k in ('curve_shadow','curve_dark','curve_light','curve_highlight')):return x
    xs=np.linspace(0,1,1025,dtype=np.float32)
    splits=np.array([v['curve_split_shadow'],v['curve_split_mid'],v['curve_split_highlight']],np.float32)/100
    b0=ramp((xs-splits[0]+.1)/.2);b1=ramp((xs-splits[1]+.1)/.2);b2=ramp((xs-splits[2]+.1)/.2)
    delta=(v['curve_shadow']*(1-b0)+v['curve_dark']*(b0-b1)+v['curve_light']*(b1-b2)+v['curve_highlight']*b2)*.004*xs*(1-xs)
    transfer=np.maximum.accumulate(np.clip(xs+delta,0,1));transfer[-1]=1
    return np.interp(np.clip(x,0,1),xs,transfer)+(x-np.clip(x,0,1))

def point_variance(lab,record,weight):
    variance=record.get('variance',0)/100
    if not variance:return lab
    angle=np.deg2rad(record['hue']);target=np.array([record['lightness'],record['chroma']*np.cos(angle),record['chroma']*np.sin(angle)],np.float32)
    return lab+(lab-target)*variance*weight[:,:,None]

def shadow_calibration(linear,amount):
    if not amount:return linear
    luminance=np.maximum(linear@np.array([.2126,.7152,.0722],np.float32),0)
    weight=(1-ramp(luminance/.4))*ramp(luminance/.025)*amount*.001
    # Green/magenta opponent vector has zero weighted luminance.
    return linear+weight[:,:,None]*np.array([.5,-.1424/.7152,.5],np.float32)

def denoise_detail(original,smoothed,detail,contrast):
    if not detail and not contrast:return smoothed
    residual=original-smoothed
    edge=np.hypot(cv2.Sobel(original,cv2.CV_32F,1,0),cv2.Sobel(original,cv2.CV_32F,0,1))
    keep=ramp(edge/.15)*detail/100
    result=smoothed+residual*keep
    if contrast:
        local=cv2.GaussianBlur(original,(0,0),3);result+=(original-local)*contrast*.0015
    return result

def vignette(linear,v,top,height,width):
    yy,xx=np.mgrid[top:top+linear.shape[0],:width].astype(np.float32)
    x=(xx-(width-1)/2)/max(width/2,1);y=(yy-(height-1)/2)/max(height/2,1)
    roundness=v['vignette_roundness']/100
    radius=(x*x+y*y)*(1-max(0,roundness))+(np.maximum(np.abs(x),np.abs(y))**2)*max(0,roundness)
    radius*=1+min(0,roundness)*-.6
    start=v['vignette_midpoint']/100;feather=v['vignette_feather']/100
    falloff=ramp((radius-start)/max(.02,1.25*feather))
    lum=np.maximum(linear@np.array([.2126,.7152,.0722],np.float32),0)
    protected=falloff*(1-v['vignette_highlights']/100*ramp(lum/.85))
    gain=np.exp2(v['vignette']*.012*protected)
    style=int(v['vignette_style'])
    if style==2:
        target=1. if v['vignette']>0 else 0.;return linear*(1-np.abs(v['vignette'])/100*protected[:,:,None])+target*np.abs(v['vignette'])/100*protected[:,:,None]
    if style==1:
        # Preserve chromaticity in linear light.
        return linear*gain[:,:,None]
    from color_science import oklab,oklab_rgb
    if v['vignette_highlights'] or v['vignette_roundness'] or v['vignette_midpoint']!=25 or v['vignette_feather']!=100:
        lab=oklab(linear);lab[:,:,0]*=np.cbrt(gain);return oklab_rgb(lab)
    return linear*gain[:,:,None]

def grain(v,top,height,width,rows):
    yy,xx=np.mgrid[top:top+rows,:width].astype(np.float32)
    size=max(.25,v['grain_size']*max(height,width)/1500)
    x=xx/size;y=yy/size;ix=np.floor(x).astype('uint32');iy=np.floor(y).astype('uint32')
    seed=ix*np.array(374761393,dtype='uint32')+iy*np.array(668265263,dtype='uint32')+np.array(1447,dtype='uint32')
    seed=(seed^(seed>>13))*np.array(1274126177,dtype='uint32');seed=seed^(seed>>16)
    noise=seed.astype(np.float32)/4294967295.-.5
    low=cv2.GaussianBlur(noise,(0,0),.5+2*(1-v['grain_roughness']/100))
    noise=noise*v['grain_roughness']/100+low*(1-v['grain_roughness']/100)
    return noise*v['grain']*.18
