"""Copy and verify a complete, hash-listed offline MoGe runtime."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parent
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def verify(root=ROOT):
    root=Path(root).resolve();manifest=json.loads((root/'models/relight/provenance.json').read_text(encoding='utf8'))
    if manifest['backend']!='moge-2-small-normal':raise ValueError('Wrong light backend')
    for item in manifest['files']:
        p=(root/item['file']).resolve()
        if not p.is_relative_to(root) or digest(p)!=item['sha256']:raise ValueError('MoGe asset mismatch: '+item['file'])
    return manifest
def copy_to(stage):
    stage=Path(stage).resolve();data=verify()
    if not stage.is_relative_to(ROOT):raise ValueError('MoGe payload must stay within project')
    for item in json.loads((ROOT/'installer/retired-relight-assets.json').read_text(encoding='utf8')):
        p=(stage/item['path']).resolve()
        if not p.is_relative_to(stage):raise ValueError('Retired payload asset escapes stage')
        if p.exists():
            if digest(p)!=item['sha256']:raise ValueError('Unexpected modified old staged model: '+str(p))
            p.unlink()
    for item in data['files']:
        p=stage/item['file'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/item['file'],p)
    for name in ('models/relight/provenance.json','installer/retired-relight-assets.json'):
        p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
    return verify(stage)
