"""Use actual camera-rendered pixels, never pretend to reproduce camera firmware."""
import hashlib, io
import numpy as np
import rawpy
from PIL import Image, ImageCms, ImageOps

def pixel_digest(rgb):
    h=hashlib.sha256();h.update(str((rgb.shape,str(rgb.dtype))).encode('ascii'));h.update(np.ascontiguousarray(rgb).tobytes());return h.hexdigest()

def camera_image(raw):
    thumb=raw.extract_thumb()
    profile=None;orientation=None;model='';make=''
    if thumb.format==rawpy.ThumbFormat.JPEG:
        with Image.open(io.BytesIO(thumb.data)) as image:
            if image.width*image.height>110_000_000:raise ValueError('机内预览超过1.1亿像素。')
            exif=image.getexif();orientation=exif.get(274);model=exif.get(272,'');make=exif.get(271,'')
            profile=image.info.get('icc_profile')
            rgb_image=ImageOps.exif_transpose(image).convert('RGB')
            if profile:
                rgb_image=ImageCms.profileToProfile(rgb_image,ImageCms.ImageCmsProfile(io.BytesIO(profile)),ImageCms.createProfile('sRGB'),outputMode='RGB')
            rgb=np.array(rgb_image,dtype=np.uint8)
    elif thumb.format==rawpy.ThumbFormat.BITMAP:
        rgb=np.asarray(thumb.data)
        if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:raise ValueError('机内预览不是支持的8位 RGB 图像。')
        if rgb.shape[0]*rgb.shape[1]>110_000_000:raise ValueError('机内预览超过1.1亿像素。')
    else:raise ValueError('机内预览格式不支持。')
    # EXIF orientation takes priority; do not rotate already-transposed JPEG twice.
    if orientation is None:
        rotation={3:2,5:1,6:3}.get(raw.sizes.flip,0)
        if rotation:rgb=np.rot90(rgb,rotation)
    rgb=np.ascontiguousarray(rgb)
    return rgb,{'camera_source':'embedded_preview','camera_look_applied':True,
        'camera_model':str(model),'camera_make':str(make),'camera_beauty_status':'unknown',
        'camera_image_sha256':pixel_digest(rgb),'bit_depth':8,
        'color_profile':'embedded_icc_to_srgb' if profile else 'untagged_assumed_srgb',
        'camera_note':'保留机内已渲染效果；不推断美颜开关。' + ('' if profile else ' 未标记颜色配置，按 sRGB 显示。')}
