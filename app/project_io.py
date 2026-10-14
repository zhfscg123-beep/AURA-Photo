"""Portable edit recipe with source identity and packed masks; no pickle."""
from pathlib import Path
from aura_version import VERSION
import io,json,zipfile
import numpy as np
from photo_document import sha256_file,validate_raw_settings
from damo_engine import MODEL_HASH
from patch_repair import validate_patches
from beauty_settings import normalized,RANGES
from region_masks import validate_layers,packed_layers,unpacked_layers,MAX_LAYERS
import liquify
import manual_retouch

def save_project(path,document,parameters,threshold,selection,done,small,defaults,tool_settings=None,face_settings=None,patches=None,layers=None,liquify_record=None,liquify_settings=None,manual_records=None,manual_tools=None,manual_enabled=True,source_sha256=None,extensions=None):
    path=Path(path)
    if path.exists():raise ValueError('项目已存在，请另存新文件名。')
    metadata={'schema':9,'app_version':VERSION,'source':str(document.path),'source_sha256':source_sha256 or sha256_file(document.path),
      'shape':list(selection.mask.shape),'raw_settings':document.raw_settings,'parameters':parameters,
      'threshold':threshold,'defaults':defaults,'repair_model_sha256':MODEL_HASH,
      'camera_image_sha256':document.metadata.get('camera_image_sha256'),
      'camera_source':document.metadata.get('camera_source','rgb'),'profile_sha256':document.metadata.get('profile_sha256')}
    metadata['retouch_engine']=document.metadata.get('retouch_engine',1)
    if type(metadata['retouch_engine']) is not int or metadata['retouch_engine'] not in (1,2):raise ValueError('皮肤引擎版本无效。')
    metadata['protect_dark_points']=document.metadata.get('protect_dark_points',False)
    if type(metadata['protect_dark_points']) is not bool:raise ValueError('深色点保护开关无效。')
    if metadata['protect_dark_points'] and metadata['retouch_engine']!=2:raise ValueError('旧皮肤引擎不支持深色点保护开关。')
    metadata['tool_settings']=tool_settings or {'radius':8,'feather':0}
    metadata['face_settings']=face_settings or []
    metadata['liquify_settings']=liquify_settings or {'enabled':False,'radius':150,'strength':50}
    metadata['has_liquify']=liquify_record is not None
    metadata['manual_records']=manual_retouch.validate_records(manual_records or [],selection.mask.shape)
    metadata['manual_tools']=manual_retouch.validate_tools(manual_tools)
    if type(manual_enabled) is not bool:raise ValueError('手动修饰开关无效。')
    metadata['manual_enabled']=manual_enabled
    if document.is_raw and document.raw_settings.get('process',1)==2 or any(l.get('color_process',1)==2 for l in layers or []):metadata['schema']=11
    if extensions is not None:
        from workflow_extensions import validate_extensions,pack_extensions
        metadata['extensions'],extra_arrays=pack_extensions(validate_extensions(extensions,selection.mask.shape))
        if any(v.get('relight') is not None for v in extensions.get('people',{}).values()):metadata['schema']=10
        if 'color' in extensions or 'optics' in extensions or 'output' in extensions or document.is_raw and document.raw_settings.get('process',1)==2 or any(l.get('color_process',1)==2 for l in layers or []):metadata['schema']=11
    else:extra_arrays={}
    if any(any(key in layer for key in ('mask_alpha','color_recipe','color_preparation','filter_link','ai_region')) or any(layer.get('parameters',{}).get(k,0) for k in ('shadow_color','shadow_luma','highlight_color','highlight_luma')) for layer in layers or []):metadata['schema']=12
    if document.raw_settings.get('baseline_mode','legacy')!='legacy' or (extensions or {}).get('fuji_source',{}).get('raw_settings',{}).get('baseline_mode','legacy')!='legacy':metadata['schema']=13
    if document.raw_settings.get('crop_mode','source')!='source' or (extensions or {}).get('fuji_source',{}).get('raw_settings',{}).get('crop_mode','source')!='source':metadata['schema']=13
    if metadata['retouch_engine']==2:metadata['schema']=14
    liquid=None
    if liquify_record is not None:
        liquify.restore(liquify_record,selection.mask.shape)
        liquid=liquify.encode(liquify_record)
    metadata['patches']=validate_patches(patches or [],selection.mask.shape)
    arrays={name:np.packbits((mask if mask is not None else np.zeros(selection.mask.shape,bool))>0) for name,mask in
      [('selected',selection.mask),('automatic',selection.auto),('processed',done),('small',small)]}
    buffer=io.BytesIO();np.savez_compressed(buffer,**arrays)
    packed=packed_layers(validate_layers(layers or [],selection.mask.shape))
    metadata['region_layers']=[dict({k:v for k,v in l.items() if k not in ('mask','mask_alpha')},**({'alpha_shape':list(l['mask_alpha'].shape)} if 'mask_alpha' in l else {})) for l in packed]
    region_arrays={f'm{i}':l['mask'] for i,l in enumerate(packed)}
    region_arrays.update({f'a{i}':l['mask_alpha'] for i,l in enumerate(packed) if 'mask_alpha' in l})
    regions=io.BytesIO();np.savez_compressed(regions,**region_arrays)
    with path.open('xb') as file:
        try:
            with zipfile.ZipFile(file,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('recipe.json',json.dumps(metadata,ensure_ascii=False,indent=2))
                archive.writestr('masks.npz',buffer.getvalue())
                if packed:archive.writestr('regions.npz',regions.getvalue())
                if liquid is not None:archive.writestr('liquify.npz',liquid)
                if extra_arrays:
                    extras=io.BytesIO();np.savez_compressed(extras,**extra_arrays);archive.writestr('extensions.npz',extras.getvalue())
        except Exception:file.close();path.unlink(missing_ok=True);raise

def read_project(path):
    with zipfile.ZipFile(path) as archive:
        if 'masks.npz' not in archive.namelist() and 'source.image' in archive.namelist():
            from mobile_project_bridge import read_mobile_project
            return read_mobile_project(path)
        if archive.getinfo('recipe.json').file_size>2_000_000 or archive.getinfo('masks.npz').file_size>60_000_000:raise ValueError('项目文件过大或格式异常。')
        meta=json.loads(archive.read('recipe.json'))
        if meta.get('schema') not in tuple(range(1,15)) or meta.get('repair_model_sha256')!=MODEL_HASH:raise ValueError('项目版本或修复模型不兼容。')
        meta.setdefault('retouch_engine',1)
        meta.setdefault('protect_dark_points',False)
        if type(meta['protect_dark_points']) is not bool:raise ValueError('深色点保护开关无效。')
        if meta['protect_dark_points'] and meta['retouch_engine']!=2:raise ValueError('旧皮肤引擎不支持深色点保护开关。')
        if type(meta['retouch_engine']) is not int or meta['retouch_engine'] not in (1,2) or meta['retouch_engine']==2 and meta['schema']<14:raise ValueError('项目皮肤引擎版本无效。')
        shape=meta.get('shape');
        if not isinstance(shape,list) or len(shape)!=2 or any(type(v)!=int or v<1 for v in shape) or shape[0]*shape[1]>110_000_000:raise ValueError('项目尺寸无效。')
        meta['manual_records']=manual_retouch.validate_records(meta.get('manual_records',[]),shape)
        meta['manual_tools']=manual_retouch.validate_tools(meta.get('manual_tools'))
        meta.setdefault('manual_enabled',True)
        if type(meta['manual_enabled']) is not bool:raise ValueError('手动修饰开关无效。')
        if meta['manual_records'] and meta['schema'] not in tuple(range(3,15)):raise ValueError('手动修饰项目版本无效。')
        if meta['schema'] in tuple(range(3,15)) and type(meta.get('has_liquify')) is not bool:raise ValueError('项目液化记录标记无效。')
        meta['patches']=validate_patches(meta.get('patches',[]),shape)
        meta['parameters']=normalized(meta['parameters'])
        for name,(lo,hi) in RANGES.items():
            v=meta['parameters'][name]
            if type(v) not in (int,float) or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('项目参数无效。')
        records=meta.setdefault('face_settings',[])
        if not isinstance(records,list) or len(records)>20:raise ValueError('项目人像列表无效。')
        for person in records:
            box=person.get('box',[])
            if len(box)!=4 or any(type(v) not in (int,float) or not np.isfinite(v) for v in box):raise ValueError('项目人像范围无效。')
            person['parameters']=normalized(person.get('parameters',{}))
            for name,(lo,hi) in RANGES.items():
                value=person.get('parameters',{}).get(name)
                if type(value) not in (int,float) or not np.isfinite(value) or not lo<=value<=hi:raise ValueError('项目独立人像参数无效。')
        if not .15<=float(meta['threshold'])<=.65:raise ValueError('项目检测阈值无效。')
        settings=meta.setdefault('tool_settings',{'radius':8,'feather':0})
        for name,lo,hi in [('radius',1,250),('feather',0,100)]:
            value=settings.get(name)
            if type(value) not in (int,float) or not np.isfinite(value) or not lo<=value<=hi:raise ValueError('项目画笔参数无效。')
        # Old projects were developed from sensor RAW. Keep their original source.
        legacy=dict(meta['raw_settings']);legacy.setdefault('camera_look',False)
        legacy.setdefault('camera_mode','embedded' if legacy['camera_look'] and meta.get('app_version')=='0.4' else 'profile')
        # A new default must not recolour a saved LibRaw source underneath local repairs.
        # New recipes persist raw_engine; old DCP/scene/embedded sources keep their paths.
        if 'raw_engine' not in legacy and meta.get('camera_source','raw')=='raw':
            legacy['raw_engine']='libraw-legacy'
        meta['raw_settings']=validate_raw_settings(legacy)
        packed_bytes=(shape[0]*shape[1]+7)//8
        buffer=io.BytesIO(archive.read('masks.npz'))
        with zipfile.ZipFile(buffer) as inner:
            if len(inner.infolist())!=4 or any(x.file_size>packed_bytes+512 for x in inner.infolist()):raise ValueError('项目蒙版异常。')
        buffer.seek(0)
        with np.load(buffer,allow_pickle=False) as arrays:
            masks={}
            for name in ('selected','automatic','processed','small'):
                a=arrays[name]
                if a.dtype!=np.uint8 or a.shape!=(packed_bytes,):raise ValueError('项目蒙版尺寸不一致。')
                masks[name]=np.unpackbits(a,count=shape[0]*shape[1]).reshape(shape).astype(bool)
        records=meta.get('region_layers',[])
        if not isinstance(records,list) or len(records)>MAX_LAYERS:raise ValueError('部位蒙版数量无效。')
        layers=[]
        if records:
            sizes={f'm{i}.npy':packed_bytes for i in range(len(records))}
            for i,record in enumerate(records):
                dims=record.get('alpha_shape')
                if dims is not None:
                    if meta['schema'] not in (12,13,14) or not isinstance(dims,list) or len(dims)!=2 or any(type(v)!=int or not 1<=v<=1600 for v in dims):raise ValueError('AI 柔边蒙版形状无效。')
                    sizes[f'a{i}.npy']=dims[0]*dims[1]
            if archive.getinfo('regions.npz').file_size>sum(sizes.values())+4096*len(sizes):raise ValueError('部位蒙版过大。')
            region_buffer=io.BytesIO(archive.read('regions.npz'))
            with zipfile.ZipFile(region_buffer) as inner:
                if set(inner.namelist())!=set(sizes) or len(inner.infolist())!=len(sizes) or any(x.file_size>sizes[x.filename]+512 for x in inner.infolist()):raise ValueError('部位蒙版数据无效。')
            region_buffer.seek(0)
            with np.load(region_buffer,allow_pickle=False) as arrays:
                for i,record in enumerate(records):
                    data=arrays[f'm{i}']
                    if data.dtype!=np.uint8 or data.shape!=(packed_bytes,):raise ValueError('部位蒙版尺寸不一致。')
                    layer={k:v for k,v in record.items() if k!='alpha_shape'};layer['mask']=data.copy()
                    if record.get('alpha_shape') is not None:
                        prob=arrays[f'a{i}']
                        if prob.dtype!=np.uint8 or list(prob.shape)!=record['alpha_shape']:raise ValueError('AI 柔边蒙版数据无效。')
                        layer['mask_alpha']=prob.copy()
                    layers.append(layer)
            layers=unpacked_layers(layers,shape)
        masks['region_layers']=validate_layers(layers,shape)
        settings=meta.setdefault('liquify_settings',{'enabled':False,'radius':150,'strength':50})
        if type(settings.get('enabled')) is not bool:raise ValueError('液化开关无效。')
        for key,lo,hi in [('radius',5,1000),('strength',0,100)]:
            value=settings.get(key)
            if type(value) not in (int,float) or not np.isfinite(value) or not lo<=value<=hi:raise ValueError('液化笔刷参数无效。')
        for key in ('density','rate'):
            value=settings.setdefault(key,50.)
            if type(value) not in (int,float) or not np.isfinite(value) or not 0<=value<=100:raise ValueError('液化密度或速度无效。')
        for key in ('guide_face','guide_body','fix_nodes'):
            value=settings.setdefault(key,True)
            if type(value) is not bool:raise ValueError('液化辅助线设置无效。')
        masks['liquify']=None
        if meta['schema']==2 or meta['schema'] in tuple(range(3,15)) and meta['has_liquify']:
            if archive.getinfo('liquify.npz').file_size>liquify.MAX_GRID**2*12+4096:raise ValueError('液化项目过大。')
            masks['liquify']=liquify.decode(archive.read('liquify.npz'),shape)
        if 'extensions' in meta:
            from workflow_extensions import unpack_extensions
            meta['extensions']=unpack_extensions(meta['extensions'],archive,shape)
    return meta,masks
