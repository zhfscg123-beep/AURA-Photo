"""Bounded RAW render cache; native colour and linear film bases coexist."""
from collections import OrderedDict
from pathlib import Path
import copy,json,threading

_entries=OrderedDict();_lock=threading.RLock()
MAX_BYTES=512*1024**2

def stamp(path):
    p=Path(path).resolve();s=p.stat()
    return str(p),s.st_size,s.st_mtime_ns

def key(path,settings):
    import camera_profiles
    from raw_white_balance import REVISION
    profile=None
    if settings['camera_mode']=='profile' and settings['camera_look']:
        try:
            entry,_=camera_profiles.resolve(camera_profiles.metadata(path),settings['camera_profile'])
            if entry:profile=stamp(entry['path'])
        except (OSError,ValueError,RuntimeError):return None
    from raw_baseline import REVISION as BASELINE_REVISION
    return stamp(path),json.dumps(settings,sort_keys=True),profile,BASELINE_REVISION,REVISION,camera_profiles.RENDER_REVISION

def clone(document):
    from photo_document import PhotoDocument
    return PhotoDocument(document.path,document.rgb,copy.deepcopy(document.metadata),
                         copy.deepcopy(document.raw_settings),document.scene)

def load(path,settings,read,progress=None):
    signature=key(path,settings)
    with _lock:
        cached=_entries.get(signature) if signature is not None else None
        if cached is not None:
            _entries.move_to_end(signature)
            if progress:progress('复用已准备的 RAW 来源与色彩；正在准备当前编辑…')
            return clone(cached[0])
    document=read()
    size=document.rgb.nbytes+(document.scene.nbytes if document.scene is not None else 0)
    if signature is not None and size<=MAX_BYTES:
        document.rgb.flags.writeable=False
        with _lock:
            _entries[signature]=(clone(document),size);_entries.move_to_end(signature)
            while len(_entries)>3 or sum(item[1] for item in _entries.values())>MAX_BYTES:_entries.popitem(last=False)
    return document

def info():
    with _lock:return dict(entries=len(_entries),bytes=sum(v[1] for v in _entries.values()))

def clear():
    with _lock:_entries.clear()
