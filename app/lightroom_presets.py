"""Turn explicit XMP adjustments into portable, non-accumulating styles.

No Adobe assets or renderer. Exposure/WB, optical corrections, sharpening and
noise reduction belong to the photograph and are excluded from a style.
"""
from pathlib import Path
import hashlib
import copy
import xmp_color_style as xmp
import creative_color as color
import point_curves

PHOTO_VALUES={'exposure','wb_kelvin','wb_tint','sharpen','sharpen_radius','sharpen_detail','sharpen_mask',
              'denoise_luma','denoise_chroma','denoise_detail','denoise_contrast','denoise_color_detail','denoise_color_smooth'}

def converted(path,name=None,group='我的',source=None):
    import color_presets as presets
    path=Path(path);data,report=xmp.read(path)
    patch=report.get('patch')
    if patch is None:
        recipe={k:copy.deepcopy(data[k]) for k in ('values','points','hsl','bw_mix','curve','point_colors')}
        if data['lut'] is not None:recipe['lut']=copy.deepcopy(data['lut'])
    else:
        recipe=dict(values=copy.deepcopy(patch['values']))
        for key in ('points','bw_mix'):
            if patch[key]:recipe[key]=copy.deepcopy(patch[key])
        if patch['hsl']:recipe['hsl']={key:list(data['hsl'].get(key,[0,0,0])) for key in patch['hsl']}
    removed={key:recipe['values'].pop(key) for key in PHOTO_VALUES if key in recipe['values']}
    if not recipe.get('point_colors') and not any(value!=color.DEFAULTS[key] for key,value in recipe['values'].items()) and not any(any(row) for row in recipe.get('hsl',{}).values()) and not any(point_curves.active(p) for p in recipe.get('points',{}).values()) and not any(recipe.get('bw_mix',{}).values()) and not any(recipe.get('curve',[])) and recipe.get('lut') is None:
        raise ValueError('此预设没有可迁移的有效风格；可能只包含曝光、降噪或Adobe专用配置。')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if patch is not None:
        recipe['values']['hue_stability']=100
        channels=recipe.get('points',{})
        if all(k in channels for k in ('r','g','b')) and channels['r']==channels['g']==channels['b']:
            recipe['values']['channel_curve_saturation']=100
        report['aura_color_protection']={'neutral_hue':True,'identical_channel_curves':bool(recipe['values'].get('channel_curve_saturation'))}
    label=(name or report['name']).strip()[:30] or path.stem[:30]
    description='Lightroom参数适配；保留照片曝光、拍摄白平衡与修图。'
    if report.get('profile_dependencies'):description+=' Adobe配置未迁移，观感会有差异。'
    item=dict(id='xmp-'+digest[:32],name=label,group=group,description=description,recipe=recipe,
              source=source or dict(label='用户导入的Lightroom XMP',url='',license='用户提供',sha256=digest))
    report['preserved_photo_fields']=sorted(removed)
    if report.get('raw_base'):item['raw_base']=report['raw_base']
    report['optics_imported']=False
    return presets.checked_preset(item),report
