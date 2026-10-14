"""Fujifilm sRGB looks on developed RGB, with a model-matched base for RAW."""
from pathlib import Path
import hashlib,json,shutil
import creative_color as color
from portable_lut import pack
STYLES=[('astia','Astia · 柔和人像'),('bleach bypass','Bleach Bypass · 银盐'),('classic chrome','Classic Chrome · 经典'),('classic neg','Classic Neg · 复古'),('eterna','Eterna · 电影'),('nostalgic neg','Nostalgic Neg · 暖调'),('pro neg hi','Pro Neg Hi · 高对比'),('pro neg std','Pro Neg Std · 肖像'),('provia','Provia · 标准'),('reala ace','Reala Ace · 自然'),('velvia','Velvia · 鲜艳')]
SHORT_NAMES={'fuji-'+key.replace(' ','-'):code for key,code in zip((key for key,_ in STYLES),('AST','EB','CC','NC','ET','NN','PNH','PNS','PRO','RA','VEL'))}
RAW_BASE={'process':1,'profile':'Adobe Standard Linear'}
CALIBRATED_RAW_BASE=dict(RAW_BASE,baseline_mode='adobe-v1')
# Historical contract accepted when reading saved styles; new styles use RAW_BASE.
SOURCE='https://github.com/abpy/FujifilmCameraProfiles'


def asset_directory():
    from app_preferences import CONFIG
    user=CONFIG.parent/'film-simulations'/'fujifilm-srgb'
    return user if (user/'manifest.json').is_file() else Path(__file__).resolve().parent/'assets/fujifilm-srgb'


def import_folder(source,destination=None):
    from app_preferences import CONFIG
    source=Path(source).resolve();destination=Path(destination or CONFIG.parent/'film-simulations'/'fujifilm-srgb').resolve()
    prepared=[]
    for key,label in STYLES:
        filename=key+'_sRGB.cube';path=source/filename
        if not path.is_file():raise ValueError('缺少 sRGB LUT：'+filename+'；请选择包含全部11款sRGB文件的目录。')
        header=path.read_text(encoding='utf-8-sig').splitlines()[:12]
        if not any(line.strip().casefold()=='# srgb' for line in header):raise ValueError('LUT未明确标注sRGB，请使用上游sRGB版本：'+filename)
        lut=color.read_cube(path)
        if lut['size']!=32 or lut['min']!=[0,0,0] or lut['max']!=[1,1,1]:raise ValueError('富士风格需要32阶、0–1范围的sRGB LUT。')
        target=destination/filename
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=lut['sha256']:raise ValueError('已有不同内容的同名LUT，请保留原文件后再导入：'+filename)
        prepared.append(dict(key=key,label=label,file=filename,sha256=lut['sha256'],lut=pack(lut)))
    destination.mkdir(parents=True,exist_ok=True)
    for entry in prepared:
        target=destination/entry['file']
        if not target.exists():
            with (source/entry['file']).open('rb') as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
    document=dict(schema=1,source=SOURCE,licence='CC BY-NC-SA 4.0',styles=prepared)
    path=destination/'manifest.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(document,ensure_ascii=False,allow_nan=False),encoding='utf8');tmp.replace(path)
    (destination/'来源与使用条件.txt').write_text('LUT来源：'+SOURCE+'\n作者标注：CC BY-NC-SA 4.0。完整学习安装包内置已标注来源的LUT；用户另外导入的资源保存在用户目录。\n需配合机型对应的Adobe Standard Linear DCP；效果尚未与Lightroom逐像素验证。\n',encoding='utf8')
    return len(prepared)


def presets():
    return [],''


def required_base(extensions):
    state=extensions.get('color_filter',{}).get('preset',{})
    if state.get('raw_base') or extensions.get('fuji_source'):
        raise ValueError('此项目含旧版富士风格，请在原版导出普通照片后再导入独立版。')
    return None


def standard_settings(document,extensions):
    """Source restoration is shared by committed changes and comparisons."""
    from photo_document import validate_raw_settings
    settings=validate_raw_settings(extensions.get('fuji_source',{}).get('raw_settings'))
    for key in ('exposure','white_balance','kelvin','tint'):settings[key]=document.raw_settings[key]
    return settings

def base_ready(document):
    return bool(document is not None and document.is_raw and document.raw_settings.get('process')==1 and document.raw_settings.get('camera_mode')=='profile' and document.raw_settings.get('camera_look') and document.metadata.get('camera_source')=='dcp_raw' and (document.metadata.get('profile_name')=='Adobe Standard Linear' or document.metadata.get('linear_base_profile')))


def filter_base_ready(document):
    """Developed images are already sRGB; never re-develop them as RAW."""
    return bool(document is not None and (not document.is_raw or base_ready(document)))

def repair_legacy_filter(extensions,document):
    """Repair the verified 0.34.3 builtin-preset/Fuji-LUT carryover in memory."""
    import copy,color_presets
    current=extensions.get('color',{});state=extensions.get('color_filter')
    if not base_ready(document) or not state or not current.get('lut'):return False
    item=state['preset']
    if item.get('raw_base') or item['recipe'].get('lut') or item['id'] not in {x['id'] for x in color_presets.BUILTINS}:return False
    if color_presets.signature(current)!=state['signature']:return False
    from portable_lut import pack
    candidate=pack(current['lut']);items,error=presets()
    if error or not any(pack(x['recipe']['lut'])['data_sha256']==candidate['data_sha256'] for x in items):return False
    cleaned=copy.deepcopy(current);cleaned['lut']=None
    corrected=copy.deepcopy(state);corrected['signature']=color_presets.signature(cleaned)
    extensions['color']=cleaned;extensions['color_filter']=corrected
    return True
