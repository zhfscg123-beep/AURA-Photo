"""Independent wide-float photographic tone/color processing, not Adobe code.

No early display clamp. Spatial controls filter luminance/chroma separately;
native pixels remain full resolution, and coarse adaptation has no tile seams.
"""
import numpy as np,cv2
import color_science as cs
from develop_settings import DEFAULTS as EXTRA_DEFAULTS
HUES={'红':29.,'橙':58.,'黄':108.,'绿':142.,'青':195.,'蓝':264.,'紫':300.,'洋红':328.}
WEIGHTS=np.array([.2880402,.7118741,.0000857],np.float32)

def smoothstep(x):
    t=np.clip(x,0,1);return t*t*(3-2*t)

def point_weight(lab,record):
    hue=(np.rad2deg(np.arctan2(lab[:,:,2],lab[:,:,1]))+360)%360;chroma=np.linalg.norm(lab[:,:,1:],axis=2)
    distance=np.abs((hue-record['hue']+180)%360-180)
    return smoothstep(1-distance/record['hue_range'])*smoothstep(1-np.abs(chroma-record['chroma'])/record['chroma_range'])*smoothstep(1-np.abs(lab[:,:,0]-record['lightness'])/record['lightness_range'])

def edit_lch(lab,dh,ds,dl,weight):
    angle=np.deg2rad(dh*.45)*weight;ab=lab[:,:,1:].copy();c=np.cos(angle);s=np.sin(angle)
    lab[:,:,1]=(ab[:,:,0]*c-ab[:,:,1]*s)*np.exp2(ds/100*weight)
    lab[:,:,2]=(ab[:,:,0]*s+ab[:,:,1]*c)*np.exp2(ds/100*weight)
    lab[:,:,0]*=np.exp2(dl*.006*weight)

def input_working(rgb,document=None,top=0,end=None):
    current=rgb[top:end]
    scene=getattr(document,'scene',None)
    if scene is None or scene.shape!=rgb.shape:return cs.from_srgb(current)
    original=document.rgb[top:end].astype(np.float32)/(257 if document.rgb.dtype==np.uint16 else 1)
    return scene[top:end]+cs.from_srgb(current)-cs.from_srgb(original)

def tone(working,v,coarse=None):
    if v['exposure']:working=working*np.exp2(v['exposure'])
    y=np.maximum(working@WEIGHTS,1e-7)
    if v['contrast']:
        target=.18*np.maximum(y/.18,1e-6)**(1+v['contrast']*.004)
        working=working*(target/y)[:,:,None];y=target
    guide=y if coarse is None else np.maximum(coarse*np.exp2(v['exposure']),0)
    shadow=1-smoothstep(guide/.55);high=guide/(guide+.55)
    stops=v['shadows']*.013*shadow+v['highlights']*.015*high
    if np.any(stops):working=working*np.exp2(stops)[:,:,None];y=np.maximum(working@WEIGHTS,1e-7)
    white=y/(y+.85);black=np.exp(-y/.035)
    target=y*np.exp2(v['whites']*.01*white)+v['blacks']*.00035*black
    target=np.maximum(target,0)
    result=working*(target/y)[:,:,None]
    black=(np.abs(working@WEIGHTS)<1e-7)
    if v['blacks']>0:result[black]=target[black,None]
    return result

def white_balance(working,data):
    v=data['values']
    if v['wb_kelvin']!=6500 or v['wb_tint']:working=working@cs.temperature_matrix(v['wb_kelvin'],v['wb_tint']).T
    # Legacy cold/warm controls become a relative Kelvin shift in process 2.
    if v['temperature'] or v['tint']:working=working@cs.temperature_matrix(np.clip(6500*np.exp2(v['temperature']/160),2000,50000),v['tint']).T
    if data.get('wb_sample') is not None:
        working=cs.convert_linear(cs.convert_linear(working,'ProPhoto','sRGB')*np.array(data['wb_sample'],np.float32),'sRGB','ProPhoto')
    return working

def color_tile(working,data,skin=None,coarse=None):
    v=data['values'];working=white_balance(working,data);working=tone(working,v,coarse)
    linear=cs.convert_linear(working,'ProPhoto','sRGB')
    from develop_advanced import parametric_curve,point_variance,shadow_calibration
    linear=shadow_calibration(linear,v['cal_shadow_tint'])
    if any(v[k] for k in ('curve_shadow','curve_dark','curve_light','curve_highlight')):
        lum=np.maximum(linear@np.array([.2126,.7152,.0722],np.float32),1e-7)
        target=parametric_curve(lum,v);linear*= (target/lum)[:,:,None]
    import point_curves
    points=data['points'];curve=data['curve']
    if any(curve) or any(point_curves.active(p) for p in points.values()):
        encoded=cs.encode(linear);limited=np.clip(encoded,0,1)
        curved=point_curves.apply(limited,{'rgb':points['rgb']} if 'rgb' in points else {})
        if any(curve):
            xs=np.linspace(0,1,5);ys=np.maximum.accumulate(np.clip(xs+np.asarray(curve)/500,0,1))
            curved=np.interp(curved,xs,ys).astype(np.float32)
        changed=cs.decode(curved)+linear-cs.decode(limited)
        if v['curve_saturation']:
            oldlab=cs.oklab(linear);newlab=cs.oklab(changed)
            keep=v['curve_saturation']/100;newlab[:,:,1:]=newlab[:,:,1:]*(1-keep)+oldlab[:,:,1:]*keep
            changed=cs.oklab_rgb(newlab)
        channels={k:p for k,p in points.items() if k!='rgb'}
        if any(point_curves.active(p) for p in channels.values()):
            encoded_changed=cs.encode(changed);bounded=np.clip(encoded_changed,0,1)
            transformed=point_curves.apply(bounded,channels)
            transformed_linear=cs.decode(transformed)+changed-cs.decode(bounded)
            if v['channel_curve_saturation']:
                before=cs.oklab(changed);after=cs.oklab(transformed_linear)
                keep=v['channel_curve_saturation']/100
                after[:,:,1:]=after[:,:,1:]*(1-keep)+before[:,:,1:]*keep
                transformed_linear=cs.oklab_rgb(after)
            changed=transformed_linear
        linear=changed
    tone_rgb=linear.copy();lab=cs.oklab(linear);original=lab.copy()
    if data.get('_point_mask') is not None:
        weight=point_weight(original,data['_point_mask']);return np.stack([weight,weight,weight],axis=2)*255
    chroma=np.linalg.norm(lab[:,:,1:],axis=2);hue=(np.rad2deg(np.arctan2(lab[:,:,2],lab[:,:,1]))+360)%360
    # Achromatic hue is undefined. Opt-in protection keeps old saved recipes
    # unchanged while making new styles continuous at the neutral axis.
    hue_weight=1-v['hue_stability']/100*(1-smoothstep(chroma/.01))
    for name,(dh,ds,dl) in data['hsl'].items():
        if dh or ds or dl:
            distance=np.abs((hue-HUES[name]+180)%360-180);weight=smoothstep(1-distance/45)*hue_weight
            edit_lch(lab,dh,ds,dl,weight)
    for record in data['point_colors']:
        if any(record.get(k,0) for k in ('hue_shift','saturation','luminance','variance')):
            weight=point_weight(original,record)*hue_weight;lab=point_variance(lab,record,weight)
            edit_lch(lab,record['hue_shift'],record['saturation'],record['luminance'],weight)
    if v['saturation'] or v['vibrance']:
        gain=max(0,1+v['saturation']/100)+v['vibrance']/100*np.clip(1-chroma/.28,0,1)*.75
        lab[:,:,1:]*=np.maximum(gain,0)[:,:,None]
    if v['bw']:
        for name,shift in data['bw_mix'].items():
            distance=np.abs((hue-HUES[name]+180)%360-180);lab[:,:,0]*=np.exp2(shift*.005*v['bw']*smoothstep(1-distance/45)*hue_weight)
        lab[:,:,1:]*=1-v['bw']
    guide=np.maximum(lab[:,:,0],0);balance=v['grading_balance']/100
    width=.35+v['grading_blend']/100*.25
    sweight=1-smoothstep((guide-(.25+balance*.2))/width);hweight=smoothstep((guide-(.55+balance*.2))/width)
    weights=np.stack([sweight,(1-sweight)*(1-hweight),hweight],axis=2);weights/=np.maximum(weights.sum(2,keepdims=True),1e-6)
    grading_keep=1
    if v['grading_warm_protect']:
        # Protect a broad warm-color interval, not a claimed face detector.
        # This limits cyan grading on skin without changing green/blue scenery.
        warm_hue=(np.rad2deg(np.arctan2(lab[:,:,2],lab[:,:,1]))+360)%360
        warm_chroma=np.linalg.norm(lab[:,:,1:],axis=2)
        warm=smoothstep((warm_hue-5)/15)*(1-smoothstep((warm_hue-85)/15))
        warm*=smoothstep((warm_chroma-.005)/.01)*(1-smoothstep((warm_chroma-.16)/.08))
        grading_keep=1-warm*v['grading_warm_protect']/100
    for i,name in enumerate(('shadow','midtone','highlight')):
        angle=np.deg2rad(v[name+'_hue']);weight=weights[:,:,i]
        endpoint=smoothstep(guide/.12)*(1-smoothstep((guide-.85)/.15))
        amount=v[name+'_color']*.0012*weight*endpoint*grading_keep
        lab[:,:,1]+=np.cos(angle)*amount;lab[:,:,2]+=np.sin(angle)*amount
        lab[:,:,0]*=np.exp2(v[name+'_luma']*.005*weight)
    if v['global_color']:
        angle=np.deg2rad(v['global_hue']);endpoint=smoothstep(guide/.12)*(1-smoothstep((guide-.85)/.15));lab[:,:,1]+=np.cos(angle)*v['global_color']*.0012*endpoint*grading_keep;lab[:,:,2]+=np.sin(angle)*v['global_color']*.0012*endpoint*grading_keep
    linear=cs.oklab_rgb(lab)
    for i,name in enumerate(('red','green','blue')):
        sat=v['cal_'+name+'_sat'];shift=v['cal_'+name+'_hue']
        if sat or shift:
            amount=linear[:,:,i].copy();linear[:,:,i]*=1+sat*.005
            linear[:,:,(i+1)%3]+=amount*shift*.0015;linear[:,:,(i+2)%3]-=amount*shift*.0015
    encoded=cs.encode(linear)
    if data['lut'] is not None and v['lut_strength']:
        from creative_color import lut_apply
        bounded=np.clip(encoded,0,1);encoded+=(lut_apply(bounded,data['lut'])-bounded)*v['lut_strength']/100
    if skin is not None and v['skin_protect']:
        alpha=skin.astype(np.float32)*v['skin_protect']/100
        encoded=encoded*(1-alpha[:,:,None])+cs.encode(tone_rgb)*alpha[:,:,None]
    return encoded*255

def spatial_details(rgb,v,tile_height=192):
    if not any(v[k] for k in ('texture','clarity','dehaze','denoise_luma','denoise_chroma','sharpen','vignette','grain')):return rgb
    out=rgb.copy();h,w=out.shape[:2]
    # Halo rows are independent of render tile boundaries; no RGB blur is used
    # for texture/sharpness, only luminance, while chroma denoise is separate.
    clarity_sigma=max(2,min(30,max(h,w)*.006));dehaze_sigma=max(3,min(30,max(h,w)*.01))
    radius=int(np.ceil(4*(1+(clarity_sigma if v['clarity'] else 0)+(dehaze_sigma if v['dehaze'] else 0)+(v['sharpen_radius'] if v['sharpen'] else 0))+10))
    for top in range(0,h,tile_height):
        end=min(h,top+tile_height);a=max(0,top-radius);b=min(h,end+radius)
        encoded=rgb[a:b]/255;linear=cs.decode(encoded);lab=cs.oklab(linear);L=lab[:,:,0].copy();original=L.copy()
        if v['denoise_luma']:
            scale=v['denoise_luma']/100
            low=cv2.bilateralFilter(L.astype(np.float32),5,.025+.075*scale,2.5)
            from develop_advanced import denoise_detail
            low=denoise_detail(L,low,v['denoise_detail'],v['denoise_contrast'])
            L=L+(low-L)*scale
        if v['denoise_chroma']:
            scale=v['denoise_chroma']/100
            for c in (1,2):
                low=cv2.GaussianBlur(lab[:,:,c],(0,0),1+2*scale+v['denoise_color_smooth']*.03)
                from develop_advanced import denoise_detail
                low=denoise_detail(lab[:,:,c],low,v['denoise_color_detail'],0)
                lab[:,:,c]+=(low-lab[:,:,c])*scale
        fine=cv2.GaussianBlur(L,(0,0),1)
        if v['texture']:L+=(L-fine)*v['texture']*.008
        if v['clarity']:
            broad=cv2.GaussianBlur(L,(0,0),max(2,min(30,max(h,w)*.006)))
            L+=(L-broad)*v['clarity']*.008
        if v['dehaze']:
            baseline=cv2.GaussianBlur(L,(0,0),max(3,min(30,max(h,w)*.01)))
            L=(L-.12*v['dehaze']/100)*(1+v['dehaze']*.004)+(L-baseline)*v['dehaze']*.003
        if v['sharpen']:
            low=cv2.GaussianBlur(L,(0,0),v['sharpen_radius']);detail=L-low
            gradient=np.hypot(cv2.Sobel(original,cv2.CV_32F,1,0),cv2.Sobel(original,cv2.CV_32F,0,1))
            mask=smoothstep(gradient/(.005+v['sharpen_mask']*.002)) if v['sharpen_mask'] else np.ones_like(L)
            detail*=smoothstep(np.abs(detail)/(.0005+(100-v['sharpen_detail'])*.00003))
            L+=detail*v['sharpen']*.012*mask
        lab[:,:,0]=np.maximum(L,0)
        tile=cs.encode(cs.oklab_rgb(lab))*255
        if v['vignette']:
            from develop_advanced import vignette
            tile=cs.encode(vignette(cs.decode(tile/255),v,a,h,w))*255
        if v['grain']:
            if v['grain_model']:
                from develop_advanced import grain
                tile+=grain(v,a,h,w,b-a)[:,:,None]
            else:
                yy,xx=np.mgrid[a:b,:w].astype(np.float32);size=v['grain_size']
                noise=np.sin(np.floor(xx/size)*12.9898+np.floor(yy/size)*78.233)*43758.5453;noise=(noise-np.floor(noise))-.5
                tile+=noise[:,:,None]*v['grain']*.18
        out[top:end]=tile[top-a:end-a]
    return out

def render(rgb,data,skin=None,document=None):
    v=data['values'];h,w=rgb.shape[:2];result=np.empty_like(rgb,np.float32)
    from creative_color import DEFAULTS
    active=any(v[k]!=DEFAULTS[k] for k in v) or bool(data.get('wb_sample')) or any(data['curve']) or any(any(row) for row in data['hsl'].values()) or bool(data['point_colors']) or any(data['bw_mix'].values()) or any(abs(x-y)>1e-8 for points in data['points'].values() for x,y in points) or data['lut'] is not None and v['lut_strength']>0
    if not active:
        if getattr(document,'scene',None) is None:return rgb
        return cs.to_srgb(input_working(rgb,document))
    factor=min(1,1200/max(h,w));small=cv2.resize(rgb,(max(2,round(w*factor)),max(2,round(h*factor))),interpolation=cv2.INTER_AREA)
    tiny=cs.from_srgb(small)
    if getattr(document,'scene',None) is not None and document.scene.shape==rgb.shape:
        size=(small.shape[1],small.shape[0]);original=cv2.resize(document.rgb,size,interpolation=cv2.INTER_AREA).astype(np.float32)/(257 if document.rgb.dtype==np.uint16 else 1)
        tiny=cv2.resize(document.scene,size,interpolation=cv2.INTER_AREA)+tiny-cs.from_srgb(original)
    guide=white_balance(tiny,data)@WEIGHTS;guide=cv2.GaussianBlur(guide,(0,0),max(1,max(guide.shape)*.012))
    for top in range(0,h,192):
        end=min(h,top+192)
        # Sample a single full-image adaptation field; never filter per tile.
        xs=np.arange(w,dtype=np.float32)*guide.shape[1]/w;ys=np.arange(top,end,dtype=np.float32)*guide.shape[0]/h
        mx,my=np.meshgrid(xs,ys);coarse=cv2.remap(guide,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        working=input_working(rgb,document,top,end)
        result[top:end]=color_tile(working,data,None if skin is None else skin[top:end],coarse)
    if data.get('_point_mask') is None:result=spatial_details(result,v)
    if not np.isfinite(result).all():raise ValueError('调色输出包含无效数值。')
    return result.astype(np.float32)

def point_mask(rgb,data,record,document=None):
    return render(rgb,dict(data,_point_mask=record),document=document)
