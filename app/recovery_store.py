"""Atomic draft recipes and bounded reusable AI caches, inside AURA data only."""
import copy,hashlib,json,os,threading,time,uuid,zipfile
from pathlib import Path
import numpy as np
from photo_library import write_state,read_state,CLASSES
from photo_document import sha256_file
from project_io import save_project,read_project
ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('AURA_DATA_DIR',str(ROOT/'.aura-data'))).resolve()

def identity():
    h=hashlib.sha256()
    names=('models-manifest.json','core.py','photo_segmentation.py','ai_engine.py','damo_engine.py','damo_blend_engine.py','person_masks.py','portrait_effects.py',
           'region_masks.py','face_reshape.py','project_io.py','recovery_store.py','app_v3.py',
           'manual_retouch.py','patch_repair.py','responsive_render_ui.py','render_queue.py',
           'relight_engine.py','relight_math.py','relight_models.py','relight_settings.py','relight_ui.py',
           'creative_color.py','develop_engine.py','color_science.py','icc_runtime.py','raw_develop.py','local_develop.py','develop_optics.py','develop_output.py',
           'photo_document.py','camera_native.py','camera_profiles.py','raw_white_balance.py','raw_baseline.py','assets/raw-baseline-v1.json',
           'complexion.py','skin_detail_protection.py','portrait_patch_blend.py','skin_texture.py')
    for name in names:
        p=ROOT/name
        if p.exists():h.update(name.encode());h.update(p.read_bytes())
    for p in sorted((ROOT/'models').glob('*')):
        if p.is_file():s=p.stat();h.update(f'{p.name}:{s.st_size}:{s.st_mtime_ns}'.encode())
    return h.hexdigest()

def frozen(value,key=''):
    """Copy mutable edit masks/containers; share read-only sensor/prediction arrays."""
    if isinstance(value,np.ndarray):
        mutable=key in ('mask','mask_alpha','auto','flow','freeze','done_mask','small_mask') or value.dtype==bool
        return value.copy() if mutable else value
    if isinstance(value,dict):return {k:frozen(v,str(k)) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return type(value)(frozen(v,key) for v in value)
    if type(value).__name__ in CLASSES:
        result=copy.copy(value);result.__dict__={k:frozen(v,k) for k,v in vars(value).items() if k!='creative_regions'};return result
    return value

def compact(state):
    excluded=('output','output_float','manual_input','liquify_input','creative_input','creative_output','color_input','edit_states','form_changed','slim_changed')
    result={k:(None if k in excluded else frozen(v,k)) for k,v in state.items()}
    result.update(edit_states=[],edit_index=-1,_recovery_render=True)
    return result

def analysis_key(state):
    s=state['session']
    return tuple([id(s),id(state.get('generated'))]+[id(v) for k,v in sorted(vars(s).items()) if k.endswith('cache') or k=='person_owner']+[
        id(v.get('geometry')) for v in state.get('reshape_cache',{}).values()])

class RecoveryStore:
    def __init__(self,folder=None,cache_limit=2*1024**3):
        self.folder=Path(folder or DATA/'recovery').resolve();self.folder.mkdir(parents=True,exist_ok=True)
        self.index=self.folder/'index.json';self.cache_limit=cache_limit;self.lock=threading.Lock();self.signature=identity()
    def entries(self):
        try:data=json.loads(self.index.read_text(encoding='utf8'))
        except (OSError,ValueError):return {}
        return data if isinstance(data,dict) else {}
    def child(self,name):
        p=(self.folder/name).resolve()
        if p.parent!=self.folder or not isinstance(name,str) or Path(name).name!=name:raise ValueError('自动恢复文件名无效。')
        return p
    def _index(self,entries):
        p=self.child('index-'+uuid.uuid4().hex+'.tmp')
        p.write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf8');os.replace(p,self.index)
    def save(self,state,recipe_args,write_cache=True):
        source=Path(state['path']).resolve();digest=sha256_file(source)
        key=hashlib.sha256((str(source).casefold()+'|'+digest).encode()).hexdigest()
        with self.lock:
            entries=self.entries();entry=entries.get(key,{})
            draft=self.child(key+'.beauty');temp=self.child(key+'-'+uuid.uuid4().hex+'.beauty')
            cache=self.child(key+'.cache')
            # Cache first, draft second, index last. Interrupted writes leave the
            # previous index and portable draft recoverable, never a partial ZIP.
            if self.cache_limit>0 and (write_cache or not cache.exists() or entry.get('environment')!=self.signature):
                write_state(cache,compact(state))
            save_project(temp,source_sha256=digest,**recipe_args)
            os.replace(temp,draft)
            entry=dict(source=str(source),source_sha256=digest,recipe=draft.name,cache=cache.name if cache.exists() else None,
                       environment=self.signature,saved_at=time.time(),version=__import__('workspace_ui').VERSION)
            entries[key]=entry
            caches=[(self.child(e['cache']),e) for e in entries.values() if e.get('cache') and self.child(e['cache']).exists()]
            total=sum(p.stat().st_size for p,e in caches)
            for p,e in sorted(caches,key=lambda item:item[1]['saved_at']):
                if total<=self.cache_limit:break
                total-=p.stat().st_size;p.unlink();e['cache']=None
            self._index(entries);return entry
    def find(self,source):
        path=str(Path(source).resolve()).casefold();items=[e for e in self.entries().values() if str(Path(e['source']).resolve()).casefold()==path]
        return max(items,key=lambda e:e['saved_at']) if items else None
    def backup_before_import(self,source):
        """Retain a portable prior draft before an explicit fresh RAW import."""
        with self.lock:
            entry=self.find(source)
            if not entry or not entry.get('recipe'):return None
            original=self.child(entry['recipe'])
            if not original.is_file():return None
            folder=(self.folder/'import-backups').resolve()
            if not folder.is_relative_to(self.folder):raise ValueError('恢复备份目录不在用户数据目录内。')
            folder.mkdir(exist_ok=True)
            destination=folder/(original.stem+'-'+str(time.time_ns())+'.beauty')
            if destination.resolve().parent!=folder:raise ValueError('恢复备份路径无效。')
            with original.open('rb') as src,destination.open('xb') as dst:
                import shutil
                shutil.copyfileobj(src,dst)
            return destination
    def prune(self):
        with self.lock:
            entries=self.entries();files=[(self.child(e['cache']),e) for e in entries.values() if e.get('cache') and self.child(e['cache']).exists()]
            total=sum(p.stat().st_size for p,e in files)
            for p,e in sorted(files,key=lambda item:item[1]['saved_at']):
                if total<=self.cache_limit:break
                total-=p.stat().st_size;p.unlink();e['cache']=None
            self._index(entries)
    def load(self,entry):
        source=Path(entry['source'])
        if not source.exists() or sha256_file(source)!=entry['source_sha256']:return None,None
        meta,masks=read_project(self.child(entry['recipe']))
        if entry.get('environment')!=self.signature or not entry.get('cache') or not self.child(entry['cache']).exists():return None,(meta,masks)
        try:state=read_state(self.child(entry['cache']))
        except (OSError,ValueError,KeyError,TypeError,EOFError,zipfile.BadZipFile):return None,(meta,masks)
        if state['document'].raw_settings!=meta['raw_settings']:return None,(meta,masks)
        if getattr(state['session'],'retouch_engine',1)!=meta['retouch_engine'] or getattr(state['session'],'protect_dark_points',False)!=meta['protect_dark_points']:return None,(meta,masks)
        document=state['document'];profile=document.metadata.get('profile_path');digest=document.metadata.get('profile_sha256')
        if profile and digest:
            try:
                if sha256_file(profile)!=digest:return None,(meta,masks)
            except OSError:return None,(meta,masks)
        # Apply latest small draft to a reused analysis, rather than rewriting a
        # large AI cache whenever only a slider or a brush record changes.
        state['selection'].mask=masks['selected'];state['selection'].auto=masks['automatic']
        state['done_mask']=masks['processed'];state['small_mask']=masks['small'].astype(np.uint8)*255
        state['face_settings']=[p['parameters'] for p in meta['face_settings']]
        state['patches']=meta['patches'];state['region_layers']=masks['region_layers'];state['active_layer']=0 if masks['region_layers'] else -1
        state['manual_records']=meta['manual_records'];state['liquify_state']=masks['liquify'];state['history']=state.get('history',[])[-20:]
        state['vars'].update(meta['parameters']);state['vars']['threshold']=meta['threshold']
        state['vars'].update(radius=meta['tool_settings']['radius'],feather=meta['tool_settings']['feather'],manual_enabled=meta['manual_enabled'])
        for k,v in meta['liquify_settings'].items():
            mapping={'enabled':'liquify_enabled','guide_face':'liquify_guide_face','guide_body':'liquify_guide_body','fix_nodes':'liquify_fix_nodes'}
            state['vars'][mapping.get(k,'liquify_'+k)]=v
        state['_recovery_manual_tools']=meta['manual_tools']
        state['_recovery_extensions']=meta.get('extensions',{})
        return state,(meta,masks)
