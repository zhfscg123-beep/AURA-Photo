"""Explicit common-parameter mapping from Camera Raw XMP; no Adobe renderer.

Namespace definition: https://developer.adobe.com/xmp/docs/xmp-namespaces/crs/
Unsupported look/profile/local AI instructions are reported, never executed.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import json
import creative_color as color
CRS='{http://ns.adobe.com/camera-raw-settings/1.0/}'
AURA='{https://aura.local/ns/develop/1.0/}'
MAPPING={
 'Exposure2012':'exposure','Exposure':'exposure','Contrast2012':'contrast','Contrast':'contrast',
 'Highlights2012':'highlights','Shadows2012':'shadows','Whites2012':'whites','Blacks2012':'blacks',
 'Temperature':'wb_kelvin','Tint':'wb_tint','Saturation':'saturation','Vibrance':'vibrance',
 'Texture':'texture','Clarity2012':'clarity','Dehaze':'dehaze','Sharpness':'sharpen','SharpenRadius':'sharpen_radius','SharpenDetail':'sharpen_detail','SharpenEdgeMasking':'sharpen_mask',
 'LuminanceSmoothing':'denoise_luma','ColorNoiseReduction':'denoise_chroma','PostCropVignetteAmount':'vignette','GrainAmount':'grain','GrainSize':'grain_size',
 'SplitToningShadowHue':'shadow_hue','SplitToningShadowSaturation':'shadow_color','SplitToningHighlightHue':'highlight_hue','SplitToningHighlightSaturation':'highlight_color',
 'ColorGradeMidtoneHue':'midtone_hue','ColorGradeMidtoneSat':'midtone_color','ColorGradeShadowLum':'shadow_luma','ColorGradeMidtoneLum':'midtone_luma','ColorGradeHighlightLum':'highlight_luma',
 'ColorGradeGlobalHue':'global_hue','ColorGradeGlobalSat':'global_color','ColorGradeBlending':'grading_blend','SplitToningBalance':'grading_balance',
 'RedHue':'cal_red_hue','RedSaturation':'cal_red_sat','GreenHue':'cal_green_hue','GreenSaturation':'cal_green_sat','BlueHue':'cal_blue_hue','BlueSaturation':'cal_blue_sat'}
COLORS=dict(zip(('Red','Orange','Yellow','Green','Aqua','Blue','Purple','Magenta'),color.HUES))
MAPPING.update({'ParametricShadows':'curve_shadow','ParametricDarks':'curve_dark','ParametricLights':'curve_light','ParametricHighlights':'curve_highlight','ParametricShadowSplit':'curve_split_shadow','ParametricMidtoneSplit':'curve_split_mid','ParametricHighlightSplit':'curve_split_highlight',
 'PostCropVignetteMidpoint':'vignette_midpoint','PostCropVignetteRoundness':'vignette_roundness','PostCropVignetteFeather':'vignette_feather','PostCropVignetteHighlightContrast':'vignette_highlights','PostCropVignetteStyle':'vignette_style','GrainFrequency':'grain_roughness',
 'LuminanceNoiseReductionDetail':'denoise_detail','LuminanceNoiseReductionContrast':'denoise_contrast','ColorNoiseReductionDetail':'denoise_color_detail','ColorNoiseReductionSmoothness':'denoise_color_smooth','ShadowTint':'cal_shadow_tint'})
# Modern grading keys take precedence over their legacy split-toning aliases.
MAPPING.update({'ColorGradeShadowHue':'shadow_hue','ColorGradeShadowSat':'shadow_color',
 'ColorGradeHighlightHue':'highlight_hue','ColorGradeHighlightSat':'highlight_color',
 'ColorGradeBalance':'grading_balance','IncrementalTemperature':'temperature','IncrementalTint':'tint'})
OPTICS_MAPPING={'PerspectiveVertical':'vertical','PerspectiveHorizontal':'horizontal','PerspectiveRotate':'rotation','PerspectiveAspect':'aspect','PerspectiveScale':'scale','PerspectiveX':'shift_x','PerspectiveY':'shift_y','LensManualDistortionAmount':'distortion','VignetteAmount':'lens_vignette'}

def curve_points(points,name,warnings):
    """Keep an imported curve's endpoint values, including lifted black/white."""
    a=np.asarray(points,float)
    if a.ndim!=2 or a.shape[1]!=2 or len(a)<2 or not np.isfinite(a).all() or np.any(a<0) or np.any(a>1) or np.any(np.diff(a[:,0])<=0):
        raise ValueError('XMP曲线控制点无效。')
    if a[0,0]>0:a=np.vstack(([0,a[0,1]],a))
    if a[-1,0]<1:a=np.vstack((a,[1,a[-1,1]]))
    if points[0][0]!=0 or points[-1][0]!=1:warnings.append(name+'未覆盖完整输入范围，已按端点值延伸。')
    if len(a)>64 or np.any(np.diff(a[:,0])<.002):
        positions=np.linspace(0,1,64);a=np.column_stack((positions,np.interp(positions,a[:,0],a[:,1])))
        warnings.append(name+'控制点已重采样为64点。')
    return a.tolist()

def read(path):
    p=Path(path)
    if p.stat().st_size>2*1024**2:raise ValueError('XMP预设过大。')
    raw=p.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('不接受含实体声明的XMP。')
    try:root=ET.fromstring(raw)
    except ET.ParseError as e:raise ValueError('XMP格式无效。') from e
    own=root.find('.//'+AURA+'Recipe')
    if own is not None:
        try:data=color.validate(json.loads(own.text or '{}'))
        except (ValueError,TypeError,KeyError) as e:raise ValueError('AURA XMP配方无效。') from e
        report=dict(name=p.stem,mapped=['AURA完整调色配方'],unsupported=[],warnings=[],notice='AURA完整配方精确恢复；共有XMP参数在其他软件中使用各自算法。')
        dependency=root.find('.//'+AURA+'RawBase')
        if dependency is not None:
            from fuji_profiles import RAW_BASE,CALIBRATED_RAW_BASE
            value=json.loads(dependency.text or '{}')
            if value not in (RAW_BASE,CALIBRATED_RAW_BASE):raise ValueError('AURA XMP基底依赖无效。')
            report['raw_base']=value
        optical=root.find('.//'+AURA+'Optics')
        if optical is not None:
            from develop_optics import checked
            report['optics']=checked(json.loads(optical.text or '{}'))
        return data,report
    scalars={};curves={};allkeys=set()
    rdf='{http://www.w3.org/1999/02/22-rdf-syntax-ns#}'
    description=root.find('.//'+rdf+'RDF/'+rdf+'Description')
    if description is None:description=root.find('./'+rdf+'Description')
    if description is None:description=root
    # A nested Look or AI correction can carry identical CRS keys. Only the
    # main description and its direct properties define global adjustments.
    for element in [description]+list(description):
        attributes=element.attrib.items() if element is description or description is root and not element.tag.startswith(CRS) else []
        for tag,value in attributes:
            if tag.startswith(CRS):scalars[tag[len(CRS):]]=value;allkeys.add(tag[len(CRS):])
        if element.tag.startswith(CRS):
            tag=element.tag[len(CRS):];allkeys.add(tag)
            if tag.startswith('ToneCurve'):
                values=[]
                for item in element.iter():
                    if item.tag.endswith('}li') and item.text:
                        try:x,y=map(float,item.text.split(','));values.append([x/255,y/255])
                        except ValueError:raise ValueError('XMP曲线控制点无效。')
                if values:curves[tag]=values
            elif element.text and element.text.strip():scalars[tag]=element.text.strip()
    for element in description.iter():
        if element.tag.startswith(CRS):allkeys.add(element.tag[len(CRS):])
    data=dict(process=2,values=dict(color.DEFAULTS),hsl={},points={});used=set();warnings=[]
    limits={k:(lo,hi) for k,_,lo,hi in color.CONTROLS}
    for tag,key in MAPPING.items():
        if tag not in scalars:continue
        try:value=float(scalars[tag])
        except ValueError:raise ValueError('XMP数值无效：'+tag)
        lo,hi=limits[key]
        if not np.isfinite(value):raise ValueError('XMP包含非有限数值。')
        if tag=='GrainSize':
            if not 0<=value<=100:raise ValueError('XMP颗粒大小超范围。')
            value=1+7*value/100;data['values']['grain_model']=1
            warnings.append('GrainSize按0–100比例转换为AURA胶片颗粒大小，非相同物理尺度。')
        if not lo<=value<=hi:warnings.append(tag+'超出AURA范围，已限制。')
        data['values'][key]=float(np.clip(value,lo,hi));used.add(tag)
    for english,chinese in COLORS.items():
        values=[]
        for prefix in ('HueAdjustment','SaturationAdjustment','LuminanceAdjustment'):
            tag=prefix+english;value=float(scalars.get(tag,0))
            if not np.isfinite(value) or not -100<=value<=100:raise ValueError('XMP HSL超范围。')
            if tag in scalars:used.add(tag)
            values.append(value)
        if any(values):data['hsl'][chinese]=values
    for name,channel in [('ToneCurvePV2012','rgb'),('ToneCurvePV2012Red','r'),('ToneCurvePV2012Green','g'),('ToneCurvePV2012Blue','b'),('ToneCurve','rgb')]:
        if name in curves:
            points=curve_points(curves[name],name,warnings)
            data['points'][channel]=points;used.add(name)
    if 'ConvertToGrayscale' in scalars:
        value=scalars['ConvertToGrayscale'].casefold()
        if value not in ('true','false'):raise ValueError('XMP黑白开关无效。')
        data['values']['bw']=1 if value=='true' else 0;used.add('ConvertToGrayscale')
    elif 'Treatment' in scalars:
        if scalars['Treatment'].casefold() not in ('color','monochrome'):raise ValueError('XMP处理模式无效。')
        data['values']['bw']=1 if scalars['Treatment'].casefold()=='monochrome' else 0;used.add('Treatment')
    data['bw_mix']={}
    for name,chinese in COLORS.items():
        tag='GrayMixer'+name
        if tag in scalars:
            value=float(scalars[tag])
            if not np.isfinite(value) or not -100<=value<=100:raise ValueError('XMP黑白混色超范围。')
            data['bw_mix'][chinese]=value;used.add(tag)
    optical={}
    for tag,key in OPTICS_MAPPING.items():
        if tag in scalars:
            try:optical[key]=float(scalars[tag])
            except ValueError:raise ValueError('XMP透视数值无效。')
            used.add(tag)
    if optical:
        from develop_optics import checked
        optical=checked(optical)
    if not used:raise ValueError('此XMP没有可映射的调色参数；可能仅包含Adobe专用配置。')
    ignored=sorted(allkeys-used-{'Version','ProcessVersion','Name','UUID','SupportsAmount','SupportsColor','SupportsMonochrome','WhiteBalance','HasSettings','ToneCurveName2012'})
    name=description.get(CRS+'Name',p.stem)
    name_element=description.find(CRS+'Name')
    if name_element is not None:
        names=[e.text for e in name_element.iter() if e.tag==rdf+'li' and e.text]
        if names:name=names[0]
    dependencies=[]
    if scalars.get('CameraProfile') not in (None,'','Default Profile'):dependencies.append(scalars['CameraProfile'])
    look=description.find(CRS+'Look')
    if look is not None:
        for item in look.iter():
            if item.get(CRS+'Name'):dependencies.append(item.get(CRS+'Name'))
    report=dict(name=name,mapped=sorted(used),unsupported=ignored,warnings=warnings,profile_dependencies=list(dict.fromkeys(dependencies)),
        notice='独立算法的参数映射，不保证与Lightroom相同效果；Adobe专用配置和AI蒙版不导入。')
    report['patch']=dict(values={key:data['values'][key] for tag,key in MAPPING.items() if tag in used},
        points=data['points'],bw_mix=data['bw_mix'],hsl={})
    for english,chinese in COLORS.items():
        axes={str(i):float(scalars[prefix+english]) for i,prefix in enumerate(('HueAdjustment','SaturationAdjustment','LuminanceAdjustment')) if prefix+english in used}
        if axes:report['patch']['hsl'][chinese]=axes
    if set(used)&{'ConvertToGrayscale','Treatment'}:report['patch']['values']['bw']=data['values']['bw']
    if 'GrainSize' in used:report['patch']['values']['grain_model']=1
    if optical:
        report['optics']=optical;report['optics_patch']={key:optical[key] for tag,key in OPTICS_MAPPING.items() if tag in used}
    return color.validate(data),report

def merge_import(current,imported,report):
    """Preserve photograph-specific and absent fields in ordinary XMP presets."""
    import copy
    if 'patch' not in report:return color.validate(imported)
    result=copy.deepcopy(color.validate(current));patch=report['patch'];result['process']=2
    result['values'].update(patch['values']);result['points'].update(copy.deepcopy(patch['points']));result['bw_mix'].update(patch['bw_mix'])
    if set(patch['values'])&{'wb_kelvin','wb_tint'}:result['wb_sample']=None
    for name,axes in patch['hsl'].items():
        values=list(result['hsl'].get(name,[0,0,0]))
        for axis,value in axes.items():values[int(axis)]=value
        result['hsl'][name]=values
    return color.validate(result)

def write(path,settings,optics=None,raw_base=None):
    """Common CRS values plus our lossless extension; never overwrite originals."""
    data=color.validate(settings);rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#';x='adobe:ns:meta/'
    ET.register_namespace('x',x);ET.register_namespace('rdf',rdf);ET.register_namespace('crs',CRS[1:-1]);ET.register_namespace('aura',AURA[1:-1])
    root=ET.Element('{'+x+'}xmpmeta');container=ET.SubElement(root,'{'+rdf+'}RDF');description=ET.SubElement(container,'{'+rdf+'}Description')
    description.set(CRS+'ProcessVersion','11.0');description.set(CRS+'HasSettings','True')
    # Export one canonical modern key for duplicate input aliases.
    reverse={value:key for key,value in MAPPING.items()}
    reverse.update(exposure='Exposure2012',contrast='Contrast2012')
    for key,tag in reverse.items():
        value=data['values'][key]
        if tag=='GrainSize':value=(value-1)/7*100
        description.set(CRS+tag,str(value))
    for name,chinese in COLORS.items():
        for i,prefix in enumerate(('Hue','Saturation','Luminance')):description.set(CRS+prefix+'Adjustment'+name,str(data['hsl'].get(chinese,[0,0,0])[i]))
        description.set(CRS+'GrayMixer'+name,str(data['bw_mix'].get(chinese,0)))
    description.set(CRS+'ConvertToGrayscale','True' if data['values']['bw'] else 'False')
    for channel,tag in [('rgb','ToneCurvePV2012'),('r','ToneCurvePV2012Red'),('g','ToneCurvePV2012Green'),('b','ToneCurvePV2012Blue')]:
        element=ET.SubElement(description,CRS+tag);seq=ET.SubElement(element,'{'+rdf+'}Seq')
        for u,v in data['points'].get(channel,[[0,0],[1,1]]):ET.SubElement(seq,'{'+rdf+'}li').text=f'{u*255:.6f}, {v*255:.6f}'
    ET.SubElement(description,AURA+'Recipe').text=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    from fuji_profiles import required_base,RAW_BASE,CALIBRATED_RAW_BASE
    raw_base=raw_base or required_base({'color':data})
    if raw_base:
        if raw_base not in (RAW_BASE,CALIBRATED_RAW_BASE):raise ValueError('AURA XMP基底依赖无效。')
        ET.SubElement(description,AURA+'RawBase').text=json.dumps(raw_base)
    if optics is not None:
        from develop_optics import checked
        optical=checked(optics);ET.SubElement(description,AURA+'Optics').text=json.dumps(optical,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        for tag,key in OPTICS_MAPPING.items():description.set(CRS+tag,str(optical[key]))
    content=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    if len(content)>2*1024**2:raise ValueError('XMP超过2MB；含大LUT时请保存AURA预设。')
    with Path(path).open('xb') as file:file.write(content)
    return dict(common_parameters=len(reverse),notice='共有参数互通，不保证Adobe逐像素效果；AURA扩展保留完整配方。')
