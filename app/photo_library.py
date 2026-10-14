"""Bounded RAM photo states with safe, local disk spill; no inference during restore."""
import atexit,json,tempfile,shutil,hashlib,zipfile,io
from pathlib import Path
from collections import OrderedDict
import numpy as np
from core import Face
from photo_document import PhotoDocument
from damo_engine import PortraitAISession
from editing import Selection,Viewport

CLASSES={c.__name__:c for c in (Face,PhotoDocument,PortraitAISession,Selection,Viewport)}
def array_bytes(value,seen=None):
    seen=set() if seen is None else seen
    if id(value) in seen:return 0
    seen.add(id(value))
    if isinstance(value,np.ndarray):return value.nbytes
    if isinstance(value,dict):return sum(array_bytes(v,seen) for v in value.values())
    if isinstance(value,(list,tuple)):return sum(array_bytes(v,seen) for v in value)
    if type(value).__name__ in CLASSES:return array_bytes(vars(value),seen)
    return 0

def write_state(path,state):
    arrays={};array_ids={}
    def encode(v):
        if isinstance(v,np.ndarray):
            if id(v) not in array_ids:
                key='a'+str(len(arrays));arrays[key]=v;array_ids[id(v)]=key
            return {'array':array_ids[id(v)]}
        if isinstance(v,np.generic):return v.item()
        if isinstance(v,Path):return {'path':str(v)}
        if isinstance(v,dict):return {'dict':[[encode(k),encode(x)] for k,x in v.items()]}
        if isinstance(v,(list,tuple)):return {'tuple' if isinstance(v,tuple) else 'list':[encode(x) for x in v]}
        if type(v).__name__ in CLASSES:return {'class':type(v).__name__,'attrs':encode(vars(v))}
        if v is None or isinstance(v,(str,int,float,bool)):return v
        raise TypeError('Unsupported cache value '+str(type(v)))
    tree=encode(state);temp=path.with_suffix('.tmp')
    try:
        with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            archive.writestr('state.json',json.dumps(tree,ensure_ascii=False))
            for key,value in arrays.items():
                with archive.open(key+'.npy','w',force_zip64=True) as stream:np.lib.format.write_array(stream,value,allow_pickle=False)
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)

def read_state(path):
    with zipfile.ZipFile(path) as archive:
        tree=json.loads(archive.read('state.json'));loaded={}
        def decode(v):
            if not isinstance(v,dict):return v
            if 'array' in v:
                key=v['array']
                if key not in loaded:
                    with archive.open(key+'.npy') as stream:loaded[key]=np.lib.format.read_array(stream,allow_pickle=False)
                return loaded[key]
            if 'path' in v:return Path(v['path'])
            if 'dict' in v:return {decode(k):decode(x) for k,x in v['dict']}
            if 'list' in v:return [decode(x) for x in v['list']]
            if 'tuple' in v:return tuple(decode(x) for x in v['tuple'])
            if 'class' in v:
                obj=CLASSES[v['class']].__new__(CLASSES[v['class']]);obj.__dict__.update(decode(v['attrs']));return obj
            raise ValueError('Invalid cache entry')
        return decode(tree)

class PhotoLibrary:
    def __init__(self,budget=1800*1024**2):
        import os
        from core import ROOT
        self.parent=Path(os.environ.get('AURA_DATA_DIR',str(ROOT/'.aura-data'))).resolve()/'session-temp';self.parent.mkdir(parents=True,exist_ok=True)
        self.folder=Path(tempfile.mkdtemp(prefix='portrait-library-',dir=self.parent));self.budget=budget
        self.entries=OrderedDict();self.hot=OrderedDict();atexit.register(self.close)
    def key(self,path):return str(Path(path).resolve()).casefold()
    def remember(self,path,state,thumb):
        key=self.key(path);st=Path(path).stat()
        entry=self.entries.setdefault(key,{'path':Path(path),'file':self.folder/(hashlib.sha256(key.encode()).hexdigest()+'.cache')})
        entry.update(thumb=thumb,stamp=(st.st_size,st.st_mtime_ns))
        if state.get('document') is not None:
            import copy,liquify
            from types import SimpleNamespace
            doc=state['document'];liquid=state.get('liquify_state')
            # The planning descriptor retains no image/prediction arrays, so a
            # preflight need not reload and re-evict gigabytes of AI caches.
            entry['preflight_state']=dict(document=SimpleNamespace(rgb=SimpleNamespace(shape=tuple(doc.rgb.shape)),is_raw=doc.is_raw,
                precision=doc.precision,metadata=copy.deepcopy(doc.metadata)),
                face_settings=copy.deepcopy(state.get('face_settings',[])),face_count=len(state['session'].faces),
                workflow_extensions=copy.deepcopy(state.get('workflow_extensions',{})),
                liquify_locked=bool(liquid is not None and (liquify.active(liquid) or liquid['freeze'].any())))
        self.hot[key]=state;self.hot.move_to_end(key);return key
    def state_for_preflight(self,key):
        entry=self.entries[key];st=entry['path'].stat()
        if (st.st_size,st.st_mtime_ns)!=entry['stamp']:raise ValueError('原图已改变，请重新导入后再预检；原编辑记录保留。')
        return entry.get('preflight_state') or self.load(key)
    def trim(self,keep=None):
        while len(self.hot)>1 and sum(array_bytes(s) for s in self.hot.values())>self.budget:
            key=next(k for k in self.hot if k!=keep)
            write_state(self.entries[key]['file'],self.hot[key]);del self.hot[key]
    def load(self,key):
        entry=self.entries[key];st=entry['path'].stat()
        if (st.st_size,st.st_mtime_ns)!=entry['stamp']:raise ValueError('原图已在其他软件中改变。请先保存原编辑项目，再移出视图区重新导入。')
        if key not in self.hot:self.hot[key]=read_state(entry['file'])
        self.hot.move_to_end(key);self.trim(keep=key);return self.hot[key]
    def remove(self,key):
        self.hot.pop(key,None);entry=self.entries.pop(key);entry['file'].unlink(missing_ok=True)
    def close(self):
        if self.folder.exists() and self.folder.resolve().parent==self.parent.resolve() and self.folder.name.startswith('portrait-library-'):shutil.rmtree(self.folder)
