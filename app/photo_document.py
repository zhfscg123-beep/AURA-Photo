"""RAW/16-bit source storage, 8-bit ML view and genuine 16-bit RGB exports."""
from dataclasses import dataclass
from pathlib import Path
from aura_version import VERSION
import hashlib,io
import numpy as np
import rawpy
import tifffile
from PIL import Image,ImageCms,ImageOps
from core import load_photo,save_photo
from camera_native import camera_image
import camera_profiles

RAW_BRANDS={'.arw':'Sony','.sr2':'Sony','.srf':'Sony','.cr2':'Canon','.cr3':'Canon','.crw':'Canon','.nef':'Nikon','.nrw':'Nikon','.raf':'Fujifilm'}
RAW_BRANDS.update({'.dng':'DNG','.rw2':'Panasonic','.orf':'Olympus','.pef':'Pentax','.3fr':'Hasselblad','.iiq':'Phase One','.rwl':'Leica','.srw':'Samsung'})
RAW_EXTENSIONS=tuple(RAW_BRANDS)
SRGB=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()

def sha256_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

@dataclass
class PhotoDocument:
    path:Path
    rgb:np.ndarray
    metadata:dict
    raw_settings:dict
    scene:object=None
    @property
    def is_raw(self):return self.path.suffix.lower() in RAW_BRANDS
    @property
    def precision(self):return 16 if self.rgb.dtype==np.uint16 else 8
    def preview(self):return np.rint(self.rgb.astype(np.float32)/257).astype(np.uint8) if self.precision==16 else self.rgb
    def base_float(self):return self.rgb.astype(np.float32)/(257 if self.precision==16 else 1)

def validate_raw_settings(settings):
    supplied=settings or {};wb=supplied.get('white_balance','camera');ev=float(supplied.get('exposure',0))
    if wb not in ('camera','auto','daylight','custom') or not np.isfinite(ev) or not -2<=ev<=3:raise ValueError('RAW 显影参数无效。')
    native=supplied.get('camera_look',True)
    if type(native)!=bool:raise ValueError('机内效果开关无效。')
    mode=supplied.get('camera_mode','profile');profile=supplied.get('camera_profile','as_shot')
    if mode not in ('profile','embedded') or not isinstance(profile,str) or len(profile)>200:raise ValueError('机内风格参数无效。')
    process=supplied.get('process',1)
    engine=supplied.get('raw_engine','rawtherapee')
    if engine not in ('rawtherapee','libraw-legacy','libraw-compat'):raise ValueError('RAW 显影引擎无效。')
    baseline_mode=supplied.get('baseline_mode','legacy')
    if baseline_mode not in ('legacy','adobe-v1','camera-v1'):raise ValueError('RAW亮度基准版本无效。')
    crop_mode=supplied.get('crop_mode','source')
    if crop_mode not in ('source','composition-v1'):raise ValueError('RAW裁切版本无效。')
    kelvin=supplied.get('kelvin',6500);tint=supplied.get('tint',0)
    if type(process) is not int or process not in (1,2) or type(kelvin) not in (int,float) or not np.isfinite(kelvin) or not 2000<=kelvin<=50000 or type(tint) not in (int,float) or not np.isfinite(tint) or not -100<=tint<=100:raise ValueError('专业RAW白平衡或算法版本无效。')
    return {'white_balance':wb,'exposure':ev,'camera_crop':bool(supplied.get('camera_crop',True)),'camera_look':native,'camera_mode':mode,'camera_profile':profile,'process':process,'kelvin':int(round(kelvin)),'tint':float(tint),'baseline_mode':baseline_mode,'crop_mode':crop_mode,'raw_engine':engine}

def new_raw_settings(**overrides):
    """Fresh imports use as-shot DCP/WB and zero additional exposure."""
    return validate_raw_settings({'baseline_mode':'legacy',**overrides})


def camera_crop_rectangle(shape,sizes):
    # Insets describe unrotated visible sensor coordinates; rawpy has already
    # applied orientation. Honor valid camera aspect crops, not arbitrary guesses.
    x=sizes.crop_left_margin-sizes.left_margin;y=sizes.crop_top_margin-sizes.top_margin
    w=sizes.crop_width;h=sizes.crop_height;W=sizes.width;H=sizes.height
    if w<=0 or h<=0 or x<0 or y<0 or x+w>W or y+h>H:return None
    if sizes.flip==5:x,y,w,h=y,W-x-w,h,w
    elif sizes.flip==6:x,y,w,h=H-y-h,x,h,w
    elif sizes.flip==3:x,y=W-x-w,H-y-h
    elif sizes.flip!=0:return None
    if x<0 or y<0 or x+w>shape[1] or y+h>shape[0]:return None
    return x,y,x+w,y+h

def apply_camera_crop(rgb,sizes):
    box=camera_crop_rectangle(rgb.shape,sizes)
    if box is None:return rgb,False
    x,y,c,d=box;w,h=c-x,d-y
    if x+w>rgb.shape[1] or y+h>rgb.shape[0]:return rgb,False
    return np.ascontiguousarray(rgb[y:y+h,x:x+w]),True

def open_document(path,raw_settings=None,progress=None):
    settings=new_raw_settings() if raw_settings is None and Path(path).suffix.lower() in RAW_BRANDS else validate_raw_settings(raw_settings)
    if Path(path).suffix.lower() in RAW_BRANDS:
        from raw_source_cache import load
        return load(path,settings,lambda:_open_document(path,settings,progress),progress)
    return _open_document(path,settings,progress)

def _open_document(path,raw_settings=None,progress=None):
    path=Path(path).resolve();extension=path.suffix.lower();settings=validate_raw_settings(raw_settings);scene=None
    if extension in RAW_BRANDS:
        if progress:progress('正在读取专业浮点RAW…' if settings['process']==2 and settings['camera_mode']!='embedded' else '正在读取机内已渲染图像…' if settings['camera_mode']=='embedded' and settings['camera_look'] else '正在准备 RAW 显影，保留 16 位精度…')
        try:
            with path.open('rb') as stream,rawpy.imread(stream) as raw:
                camera_meta={}
                try:camera_meta=camera_profiles.metadata(path)
                except (ValueError,OSError,RuntimeError):pass
                sizes=raw.sizes
                if sizes.width*sizes.height>110_000_000:raise ValueError('此版本最多支持1.1亿像素，请先裁切或另存较小副本。')
                rgb=None;native_metadata={};crop_applied=False;profile=None
                if settings['process']==2 and settings['camera_mode']!='embedded':
                    from raw_develop import render_scene
                    scene,native_metadata=render_scene(path,raw,settings,progress)
                    native_metadata['raw_engine']='LibRaw (scene)'
                    if settings['camera_crop'] and settings['crop_mode']=='source':scene,crop_applied=apply_camera_crop(scene,sizes)
                    from color_science import to_srgb
                    rgb=to_uint16(to_srgb(scene))
                if settings['camera_mode']=='profile':
                    try:
                        cm=camera_meta or camera_profiles.metadata(path);profile,style=camera_profiles.resolve(cm,settings['camera_profile'])
                        native_metadata.update(camera_model=cm.get('Model',''),camera_make=cm.get('Make',''),camera_style=style,
                            lens_model=cm.get('LensModel',''),camera_beauty_status=cm.get('SoftSkinEffect','unknown'),profile_choices=[p['name'] for p in camera_profiles.matching(cm)])
                    except (ValueError,OSError,RuntimeError) as e:
                        if rgb is None and settings['camera_look'] and settings['camera_profile']!='as_shot':raise
                        profile=None
                        if rgb is None:native_metadata.update(camera_source='raw',camera_look_applied=False,camera_note='相机配置读取失败，使用基础相机色彩。'+str(e))
                    if rgb is None and settings['camera_look']:
                        if profile:
                            # Rendering errors propagate: never silently swap engines or drop a selected DCP.
                            rgb=camera_profiles.render(path,settings,profile,progress)
                            if settings['camera_crop'] and settings['crop_mode']=='source':rgb,crop_applied=apply_camera_crop(rgb,sizes)
                            native_metadata.update(camera_source='dcp_raw',camera_look_applied=True,profile_name=profile['name'],profile_path=profile['path'],
                                linear_base_profile=profile.get('linear_base',False),raw_engine='RawTherapee',
                                white_balance_engine='RawTherapee',white_balance_method=settings['white_balance'],
                                profile_sha256=sha256_file(profile['path']),camera_note='RawTherapee · 机型匹配 DCP → 16位 RAW；不复刻专有机内美颜。')
                            from raw_baseline import correction
                            native_metadata['raw_baseline']=correction(path,settings,profile,camera_meta)
                        elif settings['camera_profile']!='as_shot':
                            raise ValueError('未找到所选机型配置：'+settings['camera_profile']+'。请重新导入 DCP 或选择按拍摄风格匹配。')
                        else:
                            native_metadata.setdefault('camera_note','未匹配到拍摄风格 DCP，使用基础相机色彩。')
                elif rgb is None and settings['camera_look']:
                    try:rgb,native_metadata=camera_image(raw)
                    except (rawpy.LibRawNoThumbnailError,rawpy.LibRawUnsupportedThumbnailError,ValueError,OSError) as e:
                        native_metadata={'camera_look_applied':False,'camera_source':'raw','camera_note':'无可用机内预览，已回退16位 RAW。原因：'+str(e)}
                if rgb is None and settings['raw_engine']=='rawtherapee':
                    rgb=camera_profiles.render(path,settings,None,progress)
                    note=native_metadata.get('camera_note','风格配置未启用，使用基础相机色彩。')
                    native_metadata.update(camera_source='raw',camera_look_applied=False,raw_engine='RawTherapee',
                        input_profile='camera_matrix',white_balance_engine='RawTherapee',white_balance_method=settings['white_balance'],
                        raw_baseline={'mode':settings['baseline_mode'],'ev':0.,'verified':False,'status':'profile_only'},
                        camera_note='RawTherapee · 16位 RAW；'+note)
                    if settings['camera_crop'] and settings['crop_mode']=='source':rgb,crop_applied=apply_camera_crop(rgb,sizes)
                if rgb is None:
                    # Only an explicit recovery choice or a historical project uses LibRaw.
                    from raw_white_balance import options,provenance
                    selected=options(raw,settings)
                    rgb=raw.postprocess(output_bps=16,output_color=rawpy.ColorSpace.sRGB,
                        gamma=(2.4,12.92),**selected,no_auto_bright=True,
                        exp_shift=2**settings['exposure'],exp_preserve_highlights=.8,
                        highlight_mode=rawpy.HighlightMode.Blend)
                    native_metadata.update(provenance(raw,settings,selected))
                    compatibility=settings['raw_engine']=='libraw-compat'
                    native_metadata.update(camera_source='raw',camera_look_applied=False,raw_engine='LibRaw (compatibility)' if compatibility else 'LibRaw (legacy project)',
                        camera_note='用户选择兼容显影 · LibRaw；未应用 DCP，相机风格和色彩可能不同。' if compatibility else '旧项目兼容显影 · LibRaw；保留历史基础 RAW 外观。')
                    if settings['camera_crop'] and settings['crop_mode']=='source':rgb,crop_applied=apply_camera_crop(rgb,sizes)
                other=raw.other
                metadata={'brand':RAW_BRANDS[extension],'format':extension[1:].upper(),
                    'rawpy':rawpy.__version__,'libraw':'.'.join(map(str,rawpy.libraw_version)),
                    'iso':other.iso_speed,'aperture':other.aperture,'shutter':other.shutter_speed,
                    'focal_length':other.focal_length,'camera_white_balance':list(raw.camera_whitebalance),
                    'applied_white_balance':list(raw.camera_whitebalance) if settings['white_balance']=='camera' else [],'orientation':sizes.flip,
                    'camera_crop_applied':crop_applied,'color_space':'sRGB','bit_depth':16}
                metadata.update(native_metadata)
                virtual_box=camera_crop_rectangle(rgb.shape,sizes) if settings['crop_mode']=='composition-v1' and settings['camera_crop'] and metadata.get('camera_source')!='embedded_preview' else None
                if virtual_box is not None:metadata['camera_crop_box']=list(virtual_box);metadata['camera_crop_composition']=True
                from camera_import import report as camera_report
                metadata['camera_import']=camera_report(camera_meta,settings,metadata.get('camera_source','raw'),metadata.get('bit_depth',16),crop_applied or virtual_box is not None,metadata)
                metadata['camera_settings']=camera_meta.copy()
        except (rawpy.LibRawFileUnsupportedError,rawpy.LibRawDataError,rawpy.LibRawIOError) as e:
            raise ValueError('无法解码此 RAW：机型/压缩格式不受当前 LibRaw 支持，或文件不完整。请尝试相机软件或转换为 TIFF。') from e
    elif extension in ('.tif','.tiff'):
        with tifffile.TiffFile(path) as tif:
            if len(tif.pages)!=1:raise ValueError('不支持多页 TIFF。')
            page=tif.pages[0];bits=page.bitspersample
            if bits in (16,32) and (page.dtype==np.uint16 or np.issubdtype(page.dtype,np.floating)) and page.photometric==2 and page.samplesperpixel==3:
                profile=page.tags.get(34675);profile=profile.value if profile else None
                if profile:
                    name=ImageCms.getProfileName(ImageCms.ImageCmsProfile(io.BytesIO(profile)))
                if page.imagewidth*page.imagelength>110_000_000:raise ValueError('照片超过1.1亿像素。')
                rgb=page.asarray()
                if profile or np.issubdtype(rgb.dtype,np.floating):
                    from icc_runtime import working_from_input
                    from color_science import to_srgb,icc_profile
                    floating=np.issubdtype(rgb.dtype,np.floating)
                    scene=working_from_input(rgb.astype(np.float32)/(1 if floating else 65535),profile or icc_profile('ProPhoto',linear=True))
                    rgb=to_uint16(to_srgb(scene))
                orientation=page.tags.get(274);orientation=orientation.value if orientation else 1
                transformations={2:lambda a:a[:,::-1],3:lambda a:a[::-1,::-1],4:lambda a:a[::-1],5:lambda a:a.transpose(1,0,2),6:lambda a:np.rot90(a,3),7:lambda a:a.transpose(1,0,2)[::-1,::-1],8:lambda a:np.rot90(a)}
                if orientation in transformations:
                    rgb=np.ascontiguousarray(transformations[orientation](rgb))
                    if scene is not None:scene=np.ascontiguousarray(transformations[orientation](scene))
                metadata={'format':'TIFF','bit_depth':int(bits),'color_space':'sRGB'}
                if profile:metadata['input_profile']=name.strip()
            elif bits==8:
                rgb=load_photo(path,apply_profile=False);metadata={'format':'TIFF','bit_depth':8,'color_space':'sRGB'}
                with Image.open(path) as im:
                    profile=im.info.get('icc_profile')
                    if profile:
                        from icc_runtime import working_from_input
                        from color_science import to_srgb
                        scene=working_from_input(np.array(ImageOps.exif_transpose(im).convert('RGB'),np.float32)/255,profile);rgb=to_uint16(to_srgb(scene))
                        metadata['input_profile']=ImageCms.getProfileName(ImageCms.ImageCmsProfile(io.BytesIO(profile))).strip()
            else:raise ValueError('支持8/16位 RGB TIFF，不支持浮点、灰度或透明 TIFF。')
    else:
        rgb=load_photo(path,apply_profile=False);metadata={'format':extension[1:].upper(),'bit_depth':8,'color_space':'sRGB'}
        with Image.open(path) as im:
            profile=im.info.get('icc_profile')
            if profile:
                from icc_runtime import working_from_input
                from color_science import to_srgb
                scene=working_from_input(np.array(ImageOps.exif_transpose(im).convert('RGB'),np.float32)/255,profile);rgb=to_uint16(to_srgb(scene));metadata['input_profile']=ImageCms.getProfileName(ImageCms.ImageCmsProfile(io.BytesIO(profile))).strip()
    metadata['dimensions']=[int(rgb.shape[1]),int(rgb.shape[0])]
    if scene is not None:
        scene=np.ascontiguousarray(scene,np.float32);scene.flags.writeable=False
        metadata.update(working_space='Linear ProPhoto D50',floating_headroom=True)
    return PhotoDocument(path,np.ascontiguousarray(rgb),metadata,settings,scene)

def to_uint16(rgb_float):return np.clip(np.rint(rgb_float*257),0,65535).astype(np.uint16)
def to_uint8(rgb_float):return np.clip(np.rint(rgb_float),0,255).astype(np.uint8)

def exclusive_export(path,writer):
    with path.open('xb') as stream:
        try:writer(stream)
        except Exception:
            stream.close();path.unlink(missing_ok=True);raise

def export_document(path,rgb_float,depth=16,options=None):
    path=Path(path)
    if path.exists():raise ValueError('导出路径已存在，请选择新文件名。')
    if path.suffix.lower() not in ('.tif','.tiff','.png','.jpg','.jpeg'):raise ValueError('请选择 TIFF、PNG 或 JPEG 导出格式。')
    if rgb_float.ndim!=3 or rgb_float.shape[2]!=3 or min(rgb_float.shape[:2])<1 or not np.isfinite(rgb_float).all():
        raise ValueError('成片像素无效，请重新渲染后导出。')
    if options:
        from develop_output import checked,encoded_output
        from color_science import icc_profile,decode,convert_linear
        settings=checked(options)
        if settings['hdr']:
            if path.suffix.lower() not in ('.tif','.tiff'):raise ValueError('HDR浮点数据请导出TIFF。')
            from gpu_render import execute_pixel,output_pixels
            try:values=execute_pixel(output_pixels,rgb_float,settings['space'],True,32,host_result=True)
            except Exception as error:
                from gpu_render import record_cpu_recovery
                record_cpu_recovery('HDR 输出转换',error);values=convert_linear(decode(rgb_float/255),'sRGB',settings['space'])
            profile=icc_profile(settings['space'],linear=True)
            exclusive_export(path,lambda stream:tifffile.imwrite(stream,values.astype(np.float32),photometric='rgb',compression='deflate',predictor=3,metadata=None,software='AURA '+VERSION,extratags=[(34675,'B',len(profile),profile,False),(274,'H',1,1,False)]))
            return
        from gpu_render import execute_pixel,output_pixels
        bits=16 if path.suffix.lower() in ('.tif','.tiff') and depth==16 else 8
        try:pixels=execute_pixel(output_pixels,rgb_float,settings['space'],False,bits,host_result=True)
        except Exception as error:
            from gpu_render import record_cpu_recovery
            record_cpu_recovery('输出色彩转换',error)
            values=encoded_output(rgb_float,settings['space']);pixels=np.clip(np.rint(values*(65535 if bits==16 else 255)),0,65535 if bits==16 else 255).astype(np.uint16 if bits==16 else np.uint8)
        profile=icc_profile(settings['space'])
        if path.suffix.lower() in ('.tif','.tiff') and depth==16:
            exclusive_export(path,lambda stream:tifffile.imwrite(stream,pixels,photometric='rgb',compression='deflate',predictor=True,metadata=None,software='AURA '+VERSION,extratags=[(34675,'B',len(profile),profile,False),(274,'H',1,1,False)]))
        else:
            image=Image.fromarray(pixels)
            exclusive_export(path,lambda stream:image.save(stream,format={'.png':'PNG','.jpg':'JPEG','.jpeg':'JPEG','.tif':'TIFF','.tiff':'TIFF'}[path.suffix.lower()],icc_profile=profile,**({'quality':95,'subsampling':0} if path.suffix.lower() in ('.jpg','.jpeg') else {})))
        return
    if path.suffix.lower() in ('.tif','.tiff') and depth==16:
        from gpu_render import execute_pixel,quantize_pixels,record_cpu_recovery
        try:pixels=execute_pixel(quantize_pixels,rgb_float,16,host_result=True)
        except Exception as error:record_cpu_recovery('16 位输出量化',error);pixels=to_uint16(rgb_float)
        with path.open('xb') as stream:
            try:
                tifffile.imwrite(stream,pixels,photometric='rgb',compression='deflate',predictor=True,
                    metadata=None,software='AURA '+VERSION,extratags=[(34675,'B',len(SRGB),SRGB,False),(274,'H',1,1,False)])
            except Exception:stream.close();path.unlink(missing_ok=True);raise
    else:
        from gpu_render import execute_pixel,quantize_pixels,record_cpu_recovery
        try:pixels=execute_pixel(quantize_pixels,rgb_float,8,host_result=True)
        except Exception as error:record_cpu_recovery('8 位输出量化',error);pixels=to_uint8(rgb_float)
        save_photo(path,pixels)
