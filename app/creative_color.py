"""Float color adjustments, portable 3D LUTs and robust reference statistics."""
import hashlib,shlex
from pathlib import Path
import cv2,numpy as np
CONTROLS=[('exposure','曝光',-5,5),('contrast','对比度',-100,100),('highlights','高光',-100,100),
 ('shadows','阴影',-100,100),('whites','白色色阶',-100,100),('blacks','黑色色阶',-100,100),
 ('temperature','色温',-100,100),('tint','色调',-100,100),('saturation','饱和度',-100,100),('vibrance','自然饱和度',-100,100),
 ('shadow_hue','阴影色相',0,360),('shadow_color','阴影染色',0,100),('highlight_hue','高光色相',0,360),('highlight_color','高光染色',0,100),
 ('lut_strength','LUT强度',0,100),('skin_protect','调色肤色保护',0,100)]
DEFAULTS={k:0. for k,_,_,_ in CONTROLS};HUES={'红':0,'橙':30,'黄':60,'绿':120,'青':180,'蓝':240,'紫':270,'洋红':315}
from develop_settings import EXTRA as DEVELOP_CONTROLS,DEFAULTS as DEVELOP_DEFAULTS,checked_points
CONTROLS+= [(k,label,lo,hi) for k,label,lo,hi,_ in DEVELOP_CONTROLS]
DEFAULTS.update(DEVELOP_DEFAULTS)

def validate(data):
    values=dict(DEFAULTS,**data.get('values',{}))
    for k,_,lo,hi in CONTROLS:
        v=values[k]
        if type(v) not in (int,float) or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('调色参数无效：'+k)
    if set(values)!=set(DEFAULTS):raise ValueError('未知调色参数。')
    if not values['curve_split_shadow']<values['curve_split_mid']<values['curve_split_highlight']:raise ValueError('曲线分界需依次递增。')
    for k in ('vignette_style','grain_model'):
        if values[k]!=int(values[k]):raise ValueError('调色模式需为整数。')
    hsl=data.get('hsl',{});curve=data.get('curve',[0]*5)
    if len(curve)!=5 or any(type(v) not in (int,float) or not np.isfinite(v) or not -100<=v<=100 for v in curve):raise ValueError('曲线参数无效。')
    for name,triple in hsl.items():
        if name not in HUES or len(triple)!=3 or any(type(v) not in (int,float) or not np.isfinite(v) or not -100<=v<=100 for v in triple):raise ValueError('HSL参数无效。')
    lut=data.get('lut')
    if lut is not None:
        from portable_lut import array as lut_array
        n=lut['size'];cube=np.asarray(lut_array(lut))
        if type(n) is not int or not 2<=n<=33 or cube.shape!=(n,n,n,3) or not np.isfinite(cube).all() or np.max(np.abs(cube))>8:raise ValueError('LUT数据无效。')
        lo=np.asarray(lut.get('min',[0,0,0]));hi=np.asarray(lut.get('max',[1,1,1]))
        if lo.shape!=(3,) or hi.shape!=(3,) or not np.isfinite(lo).all() or not np.isfinite(hi).all() or np.any(hi<=lo):raise ValueError('LUT范围无效。')
    from point_curves import checked
    process=data.get('process',1 if data else 2)
    if type(process) is not int or process not in (1,2):raise ValueError('调色算法版本无效。')
    bw=data.get('bw_mix',{})
    if not isinstance(bw,dict) or any(k not in HUES or type(x) not in (int,float) or not np.isfinite(x) or not -100<=x<=100 for k,x in bw.items()):raise ValueError('黑白混色参数无效。')
    wb_sample=data.get('wb_sample')
    if wb_sample is not None:
        a=np.asarray(wb_sample)
        if a.shape!=(3,) or not np.isfinite(a).all() or np.any(a<.125) or np.any(a>8):raise ValueError('白平衡取样无效。')
        wb_sample=a.tolist()
    return dict(process=process,values=values,hsl=hsl,curve=list(curve),lut=lut,points=checked(data.get('points',{})),point_colors=checked_points(data.get('point_colors',[])),bw_mix=bw,wb_sample=wb_sample)

def read_cube(path):
    path=Path(path)
    if path.stat().st_size>8*1024**2:raise ValueError('LUT文件过大；当前支持2–33阶3D .cube。')
    size=None;rows=[];lo=[0.,0.,0.];hi=[1.,1.,1.]
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        tokens=shlex.split(line.split('#',1)[0])
        if not tokens:continue
        if tokens[0]=='TITLE':continue
        if tokens[0]=='LUT_3D_SIZE':size=int(tokens[1]);continue
        if tokens[0]=='DOMAIN_MIN':lo=list(map(float,tokens[1:]));continue
        if tokens[0]=='DOMAIN_MAX':hi=list(map(float,tokens[1:]));continue
        if tokens[0].startswith(('LUT_1D','LUT_3D_INPUT_RANGE')):raise ValueError('请使用标准3D .cube；暂不支持1D或混合LUT。')
        if len(tokens)!=3:raise ValueError('LUT行格式无效。')
        rows.append(list(map(float,tokens)))
    if size is None or not 2<=size<=33 or len(rows)!=size**3 or len(lo)!=3 or len(hi)!=3 or np.any(np.asarray(hi)<=lo):raise ValueError('LUT尺寸、点数或范围无效。')
    cube=np.asarray(rows,np.float32).reshape(size,size,size,3)
    lut=dict(size=size,cube=np.round(cube,6).tolist(),min=lo,max=hi,name=path.stem[:100],sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    validate({'lut':lut});return lut

def lut_apply(rgb,lut):
    from portable_lut import array as lut_array
    table=np.asarray(lut_array(lut),np.float32);n=lut['size'];lo=np.asarray(lut['min'],np.float32);hi=np.asarray(lut['max'],np.float32)
    pos=np.clip((rgb-lo)/(hi-lo),0,1)*(n-1);low=np.floor(pos).astype(np.int32);high=np.minimum(low+1,n-1);fraction=pos-low
    output=np.zeros_like(rgb)
    # .cube rows vary red fastest, then green, then blue.
    for red in (0,1):
        for green in (0,1):
            for blue in (0,1):
                ids=[(high if bit else low)[:,:,channel] for channel,bit in enumerate((red,green,blue))]
                weight=np.ones(rgb.shape[:2],np.float32)
                for channel,bit in enumerate((red,green,blue)):weight*=fraction[:,:,channel] if bit else 1-fraction[:,:,channel]
                output+=table[ids[2],ids[1],ids[0]]*weight[:,:,None]
    return output

def apply(rgb,data,skin=None,document=None):
    data=validate(data);v=data['values'];hsl=data['hsl'];curve=data['curve'];lut=data['lut']
    if data['process']==2:
        from develop_engine import render
        return render(rgb,data,skin,document)
    import point_curves
    active=any(v[k] for k in ('exposure','contrast','highlights','shadows','whites','blacks','temperature','tint','saturation','vibrance','shadow_color','highlight_color')) or any(curve) or any(any(row) for row in hsl.values()) or any(point_curves.active(p) for p in data['points'].values()) or lut is not None and v['lut_strength']>0
    if not active:return rgb
    result=np.empty_like(rgb,dtype=np.float32)
    for top in range(0,rgb.shape[0],192):
        src=rgb[top:top+192].astype(np.float32)/255;out=src.copy()
        if v['exposure']:
            linear=np.where(out<=.04045,out/12.92,((out+.055)/1.055)**2.4)*2**v['exposure']
            out=np.where(linear<=.0031308,linear*12.92,1.055*np.maximum(linear,0)**(1/2.4)-.055)
        if v['contrast']:out=(out-.5)*(1+v['contrast']*.007)+.5
        luminance=np.clip(out@np.array([.2126,.7152,.0722],np.float32),0,1)
        change=(v['shadows']*.0015*(1-luminance)**2+v['highlights']*.0015*luminance**2+
                v['blacks']*.001*(1-luminance)**5+v['whites']*.001*luminance**5)
        out+=change[:,:,None]
        if any(curve):
            positions=np.linspace(0,1,5);targets=np.maximum.accumulate(np.clip(positions+np.asarray(curve)/500,0,1))
            out=np.interp(np.clip(out,0,1),positions,targets).astype(np.float32)
        out=point_curves.apply(out,data['points']);tone=out.copy()
        if v['temperature'] or v['tint']:
            lab=cv2.cvtColor(np.clip(out,0,1),cv2.COLOR_RGB2LAB);lab[:,:,1]+=v['tint']*.10;lab[:,:,2]+=v['temperature']*.16
            out=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)
        if v['saturation'] or v['vibrance'] or hsl:
            hsv=cv2.cvtColor(np.clip(out,0,1),cv2.COLOR_RGB2HSV);hue=hsv[:,:,0].copy();sat=hsv[:,:,1].copy()
            hsv[:,:,1]*=1+v['saturation']/100+v['vibrance']/100*(1-sat)*.75
            shift=np.zeros_like(hue);sgain=np.zeros_like(hue);vgain=np.zeros_like(hue)
            for name,(dh,ds,dl) in hsl.items():
                distance=np.abs((hue-HUES[name]+180)%360-180);weight=np.maximum(0,1-distance/40)
                shift+=weight*dh*.25;sgain+=weight*ds/100*.75;vgain+=weight*dl/100*.25
            hsv[:,:,0]=(hsv[:,:,0]+shift)%360;hsv[:,:,1]=np.clip(hsv[:,:,1]*(1+sgain),0,1);hsv[:,:,2]=np.clip(hsv[:,:,2]*(1+vgain),0,1)
            out=cv2.cvtColor(hsv,cv2.COLOR_HSV2RGB)
        if v['shadow_color'] or v['highlight_color']:
            lab=cv2.cvtColor(np.clip(out,0,1),cv2.COLOR_RGB2LAB)
            for which,weight in (('shadow',(1-luminance)**2),('highlight',luminance**2)):
                angle=np.deg2rad(v[which+'_hue']);amount=v[which+'_color']*.15*weight
                lab[:,:,1]+=np.cos(angle)*amount;lab[:,:,2]+=np.sin(angle)*amount
            out=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)
        if lut is not None and v['lut_strength']:out+=(lut_apply(np.clip(out,0,1),lut)-out)*v['lut_strength']/100
        if skin is not None and v['skin_protect']:
            alpha=skin[top:top+192].astype(np.float32)*v['skin_protect']/100
            out=out*(1-alpha[:,:,None])+tone*alpha[:,:,None]
        pixels=np.clip(out*255,0,255)
        if skin is not None and v['skin_protect']==100 and not any(v[k] for k in ('exposure','contrast','highlights','shadows','whites','blacks')) and not any(curve) and not any(point_curves.active(p) for p in data['points'].values()):
            protected=skin[top:top+192];pixels[protected]=rgb[top:top+192][protected]
        result[top:top+192]=pixels
    return result

def reference_lab(rgb):
    """Analytical D65 Lab shared by CPU/CUDA (no 8-bit OpenCV LUT steps)."""
    rgb=np.clip(rgb.astype(np.float32)/255,0,1)
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    matrix=np.asarray([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]],np.float32)
    xyz=(linear@matrix.T)/np.asarray([.95047,1.,1.08883],np.float32)
    f=np.where(xyz>(6/29)**3,np.cbrt(xyz),xyz/(3*(6/29)**2)+4/29)
    return np.stack((116*f[:,:,1]-16,500*(f[:,:,0]-f[:,:,1]),200*(f[:,:,1]-f[:,:,2])),axis=2)

def reference_rgb(lab):
    y=(lab[:,:,0]+16)/116
    f=np.stack((y+lab[:,:,1]/500,y,y-lab[:,:,2]/200),axis=2)
    xyz=np.where(f>6/29,f**3,3*(6/29)**2*(f-4/29))*np.asarray([.95047,1.,1.08883],np.float32)
    matrix=np.asarray([[3.2404542,-1.5371385,-.4985314],[-.9692660,1.8760108,.0415560],[.0556434,-.2040259,1.0572252]],np.float32)
    linear=np.maximum(xyz@matrix.T,0)
    return np.clip(np.where(linear<=.0031308,linear*12.92,1.055*linear**(1/2.4)-.055),0,1)*255

def statistics(rgb,mask=None):
    factor=min(1,1200/max(rgb.shape[:2]));small=cv2.resize(rgb,(max(1,round(rgb.shape[1]*factor)),max(1,round(rgb.shape[0]*factor))),interpolation=cv2.INTER_AREA)
    lab=reference_lab(small)
    valid=np.ones(small.shape[:2],bool) if mask is None else cv2.resize(mask.astype(np.uint8),(small.shape[1],small.shape[0]),interpolation=cv2.INTER_NEAREST)>0
    samples=lab[valid]
    if len(samples)<40:raise ValueError('所选参考区域过小或未可靠识别，请换区域或参考照片。')
    bounds=np.percentile(samples[:,0],[3,97]);samples=samples[(samples[:,0]>=bounds[0])&(samples[:,0]<=bounds[1])]
    return dict(mean=samples.mean(0).tolist(),std=np.maximum(samples.std(0),[4,2,2]).tolist(),quantiles=np.percentile(samples[:,0],[0,10,25,50,75,90,100]).tolist())

def match(rgb,reference,color_strength,tone_strength,mask=None,skin=None,skin_protect=0):
    if not color_strength and not tone_strength:return rgb
    current=statistics(rgb,mask);output=rgb.copy();refmean=np.asarray(reference['mean']);curmean=np.asarray(current['mean'])
    if (np.max(np.abs(refmean-curmean))<1e-5 and
        np.max(np.abs(np.asarray(reference['std'])-np.asarray(current['std'])))<1e-5 and
        np.max(np.abs(np.asarray(reference['quantiles'])-np.asarray(current['quantiles'])))<1e-5):return rgb
    ratio=np.clip(np.asarray(reference['std'])/current['std'],.65,1.5)
    q=np.asarray(current['quantiles']);rq=np.asarray(reference['quantiles']);q,unique=np.unique(q,return_index=True)
    # Interpolate a correction with zero at display black/white. Interpolating
    # absolute luminance clamped both tails even when matching a photo to itself.
    inside=(q>0)&(q<100)
    anchors=np.concatenate((np.asarray([0.]),q[inside],np.asarray([100.])))
    differences=np.concatenate((np.asarray([0.]),np.clip(rq[unique][inside]-q[inside],-18,18),np.asarray([0.])))
    for top in range(0,rgb.shape[0],192):
        src=rgb[top:top+192];lab=reference_lab(src)
        transfer=(lab[:,:,1:]-curmean[1:])*ratio[1:]+refmean[1:]
        strength=color_strength/100
        if skin is not None and skin_protect:
            strength=strength*(1-skin[top:top+len(src)].astype(np.float32)*skin_protect/100)[:,:,None]
        lab[:,:,1:]+=np.clip(transfer-lab[:,:,1:],-16,16)*strength
        lab[:,:,0]+=np.interp(lab[:,:,0].copy(),anchors,differences)*tone_strength/100
        changed=reference_rgb(lab)
        # Preserve out-of-display-range scene headroom and exact protected RGB.
        changed+=src-np.clip(src,0,255)
        if skin is not None and skin_protect==100 and not tone_strength:
            keep=skin[top:top+len(src)];changed[keep]=src[keep]
        if mask is None:output[top:top+192]=changed
        else:
            from region_masks import soft_edge
            lo=max(0,top-8);hi=min(len(mask),top+200)
            alpha=soft_edge(mask[lo:hi],4)[top-lo:top-lo+len(src)]
            output[top:top+192]=src+(changed-src)*alpha[:,:,None]
    return output.astype(np.float32)
