"""Versioned extension bundle for effect masks and new creative settings."""
import copy,io,json,zipfile
import numpy as np
MAX_MASKS=40

def validate_extensions(data,shape):
    if not isinstance(data,dict):raise ValueError('扩展编辑记录无效。')
    result=copy.deepcopy(data);masks=result.setdefault('masks',{})
    if 'fuji_source' in result:
        record=result['fuji_source']
        if not isinstance(record,dict) or set(record)!= {'version','raw_settings'} or record['version']!=1:raise ValueError('富士 RAW 来源记录无效。')
        from photo_document import validate_raw_settings
        record['raw_settings']=validate_raw_settings(record['raw_settings'])
    if result.get('color',{}).get('lut') is not None:
        from creative_color import validate
        from portable_lut import pack
        result['color']=validate(result['color']);result['color']['lut']=pack(result['color']['lut'])
    if not isinstance(masks,dict) or len(masks)>MAX_MASKS:raise ValueError('扩展蒙版数量无效。')
    for key,mask in masks.items():
        if not isinstance(key,str) or len(key)>100 or np.asarray(mask).shape!=tuple(shape):raise ValueError('扩展蒙版尺寸无效。')
        masks[key]=np.asarray(mask,bool)
    assets=result.setdefault('assets',{})
    if not isinstance(assets,dict) or len(assets)>384:raise ValueError('修复缓存数量无效。')
    total=0
    for k,a in assets.items():
        if not isinstance(k,str) or len(k)>100:raise ValueError('修复缓存名称无效。')
        a=np.asarray(a)
        if a.dtype!=np.float32 or a.ndim!=3 or a.shape[2]!=3 or a.shape[0]>shape[0] or a.shape[1]>shape[1] or not np.isfinite(a).all() or np.max(np.abs(a),initial=0)>512:raise ValueError('修复缓存数据无效。')
        total+=a.nbytes
    if total>512*1024**2:raise ValueError('修复缓存过大，请分图处理。')
    plain={k:v for k,v in result.items() if k not in ('masks','assets')}
    try:text=json.dumps(plain,allow_nan=False)
    except (ValueError,TypeError):raise ValueError('扩展参数无效。')
    if len(text.encode())>1700000:raise ValueError('扩展参数过大。')
    if 'color' in result:
        from creative_color import validate
        result['color']=validate(result['color'])
    if 'color_filter' in result:
        from color_presets import checked_state
        result['color_filter']=checked_state(result['color_filter'])
    if 'composition' in result:
        from composition import checked
        result['composition']=checked(result['composition'])
    if 'output' in result:
        from develop_output import portable
        result['output']=portable(result['output'])
    if 'optics' in result:
        from develop_optics import checked
        result['optics']=checked(result['optics'])
    if 'people' in result:
        from creative_portrait import person_values
        if not isinstance(result['people'],dict) or len(result['people'])>20:raise ValueError('创作人物记录无效。')
        for key,value in result['people'].items():
            if not isinstance(key,str) or not key.isdigit() or not 0<=int(key)<20 or not isinstance(value,dict):raise ValueError('创作人物编号无效。')
            person_values(value)
    for effect,value in result.get('effects',{}).items():
        from effect_controls import TITLES,settings
        if effect not in TITLES:raise ValueError('未知效果记录。')
        settings(result,effect)
    bg=result.get('background',{})
    from creative_portrait import BACKGROUND
    for key,_,lo,hi in BACKGROUND:
        v=bg.get(key,0)
        if type(v) not in (int,float) or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('背景参数无效。')
    ref=result.get('reference',{})
    if ref:
        from reference_regions import SCOPES
        if ref.get('scope') not in SCOPES or not isinstance(ref.get('name'),str):raise ValueError('参考图信息无效。')
        for key in ('target_person','source_person'):
            value=ref.get(key)
            if value is not None and (type(value) is not int or not 0<=value<20):raise ValueError('追色人物编号无效。')
        for key in ('target_roi','source_roi'):
            value=ref.get(key)
            if value is not None:
                box=np.asarray(value,dtype=np.float64)
                if box.shape!=(4,) or not np.isfinite(box).all() or np.any(box<0) or np.any(box>1) or box[0]>=box[2] or box[1]>=box[3]:raise ValueError('追色取样框无效。')
        for key in ('color','tone'):
            v=ref.get(key,0)
            if type(v) not in (int,float) or not np.isfinite(v) or not 0<=v<=100:raise ValueError('参考图强度无效。')
        stats=ref.get('stats',{})
        for key,count in [('mean',3),('std',3),('quantiles',7)]:
            a=np.asarray(stats.get(key,[]))
            if a.shape!=(count,) or not np.isfinite(a).all():raise ValueError('参考色彩统计无效。')
        if min(stats['std'])<=0 or np.any(np.diff(stats['quantiles'])<0):raise ValueError('参考色彩范围无效。')
    for key,rec in result.get('clean_records',{}).items():
        if key not in assets or 'apply-'+key not in masks:raise ValueError('AI清理缓存不完整。')
        box=rec.get('box',[])
        if len(box)!=4 or any(type(x) is not int for x in box):raise ValueError('AI清理位置无效。')
        a,b,c,d=box
        if not 0<=a<c<=shape[1] or not 0<=b<d<=shape[0] or assets[key].shape!=(d-b,c-a,3):raise ValueError('AI清理缓存尺寸不符。')
        if not isinstance(rec.get('source_hash'),str) or len(rec['source_hash'])!=32:raise ValueError('AI清理来源校验无效。')
    return result

def pack_extensions(data):
    plain={k:v for k,v in data.items() if k not in ('masks','assets')};arrays={}
    if plain.get('color',{}).get('lut') is not None:
        from portable_lut import pack
        plain['color']=copy.deepcopy(plain['color']);plain['color']['lut']=pack(plain['color']['lut'])
    names=list(data.get('masks',{}));plain['mask_keys']=names
    for i,k in enumerate(names):arrays['m'+str(i)]=np.packbits(data['masks'][k])
    plain['asset_keys']=list(data.get('assets',{}))
    for i,k in enumerate(plain['asset_keys']):arrays['a'+str(i)]=data['assets'][k]
    return plain,arrays

def unpack_extensions(meta,archive,shape):
    plain=dict(meta);keys=plain.pop('mask_keys',[]);asset_keys=plain.pop('asset_keys',[])
    if not isinstance(keys,list) or len(keys)>MAX_MASKS or len(set(keys))!=len(keys):raise ValueError('扩展蒙版索引无效。')
    if not isinstance(asset_keys,list) or len(asset_keys)>384 or len(set(asset_keys))!=len(asset_keys):raise ValueError('修复缓存索引无效。')
    masks={};assets={};size=(int(np.prod(shape))+7)//8
    if keys or asset_keys:
        info=archive.getinfo('extensions.npz')
        if info.file_size>(size+2048)*len(keys)+512*1024**2+4096:raise ValueError('扩展缓存过大。')
        buf=io.BytesIO(archive.read(info))
        with zipfile.ZipFile(buf) as inner:
            if len(inner.infolist())!=len(keys)+len(asset_keys) or sum(x.file_size for x in inner.infolist())>(size+512)*len(keys)+512*1024**2+4096:raise ValueError('扩展缓存数据异常。')
            if any(x.file_size>size+512 for x in inner.infolist() if x.filename.startswith('m')):raise ValueError('扩展蒙版数据异常。')
        buf.seek(0)
        with np.load(buf,allow_pickle=False) as arrays:
            for i,k in enumerate(keys):
                a=arrays['m'+str(i)]
                if a.dtype!=np.uint8 or a.shape!=(size,):raise ValueError('扩展蒙版格式无效。')
                masks[k]=np.unpackbits(a,count=int(np.prod(shape))).reshape(shape).astype(bool)
            for i,k in enumerate(asset_keys):assets[k]=arrays['a'+str(i)].copy()
    return validate_extensions(dict(plain,masks=masks,assets=assets),shape)

def packed_state(data):
    meta,arrays=pack_extensions(data);return dict(meta=meta,arrays=arrays)

def restore_state(bundle,shape):
    if bundle is None:return {}
    meta=dict(bundle['meta']);keys=meta.pop('mask_keys',[]);asset_keys=meta.pop('asset_keys',[]);arrays=bundle['arrays']
    masks={key:np.unpackbits(arrays['m'+str(i)],count=int(np.prod(shape))).reshape(shape).astype(bool) for i,key in enumerate(keys)}
    return validate_extensions(dict(meta,masks=masks,assets={k:arrays['a'+str(i)] for i,k in enumerate(asset_keys)}),shape)

def equal_state(a,b):
    default=dict(meta={'mask_keys':[],'asset_keys':[]},arrays={});a=a or default;b=b or default
    return a['meta']==b['meta'] and a['arrays'].keys()==b['arrays'].keys() and all(np.array_equal(a['arrays'][k],b['arrays'][k]) for k in a['arrays'])
