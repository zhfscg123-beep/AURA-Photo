"""Read as-shot maker notes, exactly match local DCP camera models, render RAW16."""
from pathlib import Path
import subprocess,json,os,struct,tempfile,hashlib,functools
import numpy as np
import tifffile
ROOT=Path(__file__).resolve().parent
# A portable distribution must not silently borrow an Adobe installation.
# Users may explicitly supply profiles for which they have the required rights.
ROOTS=[ROOT/'profiles']
FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)
RENDER_REVISION='rt-unified-20261013'
def tool(name,subdir):
    found=list((ROOT/'tools'/subdir).rglob(name))
    if not found:raise ValueError('缺少本地工具：'+name)
    return found[0]
@functools.lru_cache(maxsize=32)
def _metadata(path,size,mtime):
    tags=['Make','Model','ISO','LensModel','LensID','CreativeStyle','CreativeLook','PictureStyle','PictureControlName','FilmMode','FilmSimulation','SoftSkinEffect',
          'WhiteBalance','ColorTemperature','ColorCompensationFilter','ExposureCompensation','AspectRatio','Contrast','Saturation','Sharpness','Brightness',
          'PictureProfile','PictureEffect','DynamicRangeOptimizer','AutoHDR','HighISONoiseReduction','LongExposureNoiseReduction']
    env=os.environ.copy()
    for key in ('LC_ALL','LC_CTYPE','LANG'):env.pop(key,None)
    # Windows Perl argv is ANSI; a UTF-8 argument file preserves Chinese paths.
    with tempfile.TemporaryDirectory(prefix='portrait-exif-') as temp:
        args=Path(temp)/'read.args';args.write_text('\n'.join(['-j','-charset','filename=UTF8',*['-'+x for x in tags],path])+'\n',encoding='utf8')
        result=subprocess.run([str(tool('exiftool.exe','exiftool')),'-@',str(args)],capture_output=True,timeout=40,creationflags=FLAGS,env=env)
    if result.returncode or not result.stdout.strip():raise ValueError('相机元数据读取失败：'+result.stderr.decode('utf8',errors='replace')[-200:])
    return json.loads(result.stdout.decode('utf8'))[0]
def metadata(path):
    p=Path(path);st=p.stat();return _metadata(str(p.resolve()),st.st_size,st.st_mtime_ns).copy()
def norm(value):return ''.join(c for c in value.casefold() if c.isalnum())
def model_identity(meta):
    make=meta.get('Make','').split()[0];model=meta.get('Model','')
    if norm(model).startswith(norm(make)):return norm(model)
    return norm(make+' '+model)
def dcp_info(path):
    # Registry lookup needs two identity strings, never megabytes of LUT tables.
    path=Path(path);length=path.stat().st_size;values={}
    with path.open('rb') as stream:
        header=stream.read(8)
        if not 10<=length<=20_000_000 or len(header)!=8 or header[:2] not in (b'II',b'MM'):raise ValueError('DCP无效')
        endian='<' if header[:2]==b'II' else '>';offset=struct.unpack_from(endian+'I',header,4)[0]
        if not 8<=offset<=length-2:raise ValueError('DCP目录无效')
        stream.seek(offset);count=struct.unpack(endian+'H',stream.read(2))[0]
        if count>2048 or offset+2+count*12>length:raise ValueError('DCP目录过大')
        directory=stream.read(count*12)
        for i in range(count):
            tag,type_,n,pos=struct.unpack_from(endian+'HHII',directory,i*12)
            if tag in (50708,50936) and type_==2:
                start=offset+2+i*12+8 if n<=4 else pos
                if not 1<=n<=2000 or start+n>length:raise ValueError('DCP标签无效')
                stream.seek(start);values[tag]=stream.read(n).rstrip(b'\0').decode('utf8')
    return {'path':str(Path(path).resolve()),'model':values.get(50708,''),'name':values.get(50936,'')}
@functools.lru_cache(maxsize=1)
def registry():
    entries={}
    for root in ROOTS:
        if not root.is_dir():continue
        for path in sorted(root.rglob('*.dcp')):
            if any(part.casefold() in ('abpy-tables','fuji-reference') for part in path.parts):continue
            try:info=dcp_info(path)
            except (ValueError,OSError,struct.error,UnicodeError):continue
            if info['name'].casefold().startswith('abpy reference '):continue
            if root==ROOT/'assets/fuji-linear-profiles':
                info['linear_base']=True
                if info['name']!='Adobe Standard Linear':info['name']='线性基底 · '+info['name']
            if info['model'] and info['name']:entries.setdefault((norm(info['model']),info['name']),info)
    return list(entries.values())
def matching(meta):
    return [p for p in registry() if norm(p['model'])==model_identity(meta)]
def as_shot_names(meta):
    style=next((str(meta[k]) for k in ('CreativeStyle','CreativeLook','PictureStyle','PictureControlName','FilmMode','FilmSimulation') if k in meta),'')
    sony={'Portrait':'PT','Standard':'ST','Vivid':'VV','Vivid 2':'VV2','Neutral':'NT','B&W':'BW','Sepia':'SE'}
    names=['Camera '+style]
    if meta.get('Make','').upper().startswith('SONY'):names.insert(0,'Camera '+sony.get(style,style))
    fuji={'F0/Standard (Provia)':'PROVIA/STANDARD','F1/Studio Portrait':'PRO Neg. Std','F1a/Studio Portrait Enhanced Saturation':'PRO Neg. Hi','F2/Fujichrome (Velvia)':'Velvia/VIVID','F3/Studio Portrait Ex':'ASTIA/SOFT','F4/Velvia':'Velvia/VIVID','Classic Chrome':'CLASSIC CHROME','Classic Negative':'CLASSIC Neg.','ETERNA':'ETERNA/CINEMA','Acros':'ACROS'}
    if meta.get('Make','').upper().startswith('FUJI'):names.insert(0,'Camera '+fuji.get(style,style))
    return style,names
def resolve(meta,choice='as_shot'):
    profiles=matching(meta);style,names=as_shot_names(meta)
    wanted=names if choice=='as_shot' else [choice]
    for name in wanted:
        found=next((p for p in profiles if norm(p['name'])==norm(name)),None)
        if found:return found,style
    if choice=='Adobe Standard Linear':
        bases=[p for p in profiles if p.get('linear_base')]
        if len(bases)==1:return bases[0],style
    return None,style
def render(path,settings,profile=None,progress=None):
    # DCP is optional colour management, never a choice of RAW decoder.
    if profile:
        if not Path(profile['path']).is_file():raise ValueError('所选 DCP 文件不存在，请重新导入配置。')
        if model_identity(metadata(path))!=norm(profile['model']):raise ValueError('DCP机型不匹配，已拒绝套用。')
    if progress:progress('正在使用 RawTherapee 显影：'+(profile['name'] if profile else '基础相机色彩')+'，输出16位…')
    wb={'camera':'Camera','auto':'Auto','daylight':'Daylight','custom':'Custom'}[settings['white_balance']]
    from raw_baseline import correction
    baseline=correction(path,settings,profile,metadata(path)) if profile else {'ev':0.}
    exposure=settings['exposure']+baseline['ev']
    input_profile='file:'+Path(profile['path']).as_posix() if profile else '(camera)'
    with tempfile.TemporaryDirectory(prefix='portrait-raw-') as temp:
        pp3=Path(temp)/'settings.pp3';out=Path(temp)/'result.tif'
        text=f'''[Version]\nAppVersion=5.13\nVersion=353\n\n[Exposure]\nAuto=false\nCompensation={settings['exposure']}\n\n[White Balance]\nEnabled=true\nSetting={wb}\n\n[Color Management]\nInputProfile={input_profile}\nToneCurve=true\nApplyLookTable=true\nApplyBaselineExposureOffset=true\nApplyHueSatMap=true\nDCPIlluminant=0\nWorkingProfile=ProPhoto\nOutputProfile=RTv4_sRGB\n\n[Crop]\nEnabled=false\n\n[Resize]\nEnabled=false\n'''
        text=text.replace('Compensation='+str(settings['exposure']),'Compensation='+str(exposure))
        if wb=='Custom':text=text.replace('Setting=Custom','Setting=Custom\nTemperature='+str(int(round(settings.get('kelvin',6500))))+'\nGreen='+str(np.exp(settings.get('tint',0)*.006)))
        pp3.write_text(text,encoding='utf8')
        env=os.environ.copy();env['OMP_NUM_THREADS']='4'
        result=subprocess.run([str(tool('rawtherapee-cli.exe','rawtherapee')),'-q','-o',str(out),'-p',str(pp3),'-t','-b16','-c',str(Path(path).resolve())],capture_output=True,timeout=240,env=env,creationflags=FLAGS)
        if result.returncode or not out.exists():raise ValueError('RawTherapee 显影失败，未切换其他引擎：'+(result.stderr+result.stdout).decode('utf8',errors='replace')[-900:])
        with tifffile.TiffFile(out) as tif:
            rgb=tif.asarray();tag=tif.pages[0].tags.get(34675)
            if not tag:raise ValueError('RAW显影缺少输出色彩配置。')
        if rgb.dtype!=np.uint16 or rgb.ndim!=3 or rgb.shape[2]!=3:raise ValueError('RAW显影未返回16位 RGB。')
        return rgb
