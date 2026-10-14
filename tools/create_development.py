"""Create a private editable copy from a verified AURA Photo 0.2.0 installation.

Copies only the distribution manifest, then overlays this repository's source.
No user photos, preferences, recovery data or private caches are copied.
"""
from pathlib import Path,PurePosixPath
import argparse,json,hashlib,shutil,os
ROOT=Path(__file__).resolve().parents[1]
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-dir',type=Path,required=True,help='Complete installed AURA Photo 0.2.0 folder')
    parser.add_argument('--output',type=Path,default=ROOT/'work/AURA Photo')
    args=parser.parse_args();base=args.base_dir.resolve();out=args.output.resolve()
    if not out.is_relative_to(ROOT/'work') or out.exists():raise ValueError('Choose a new directory inside this repository\'s work/ folder.')
    manifest=json.loads((base/'distribution-manifest.json').read_text(encoding='utf8'))
    if manifest['version']!='0.2.0':raise ValueError('This source snapshot requires the 0.2.0 runtime.')
    checked=[]
    for item in manifest['files']:
        rel=PurePosixPath(item['file']);source=(base/rel).resolve()
        if rel.is_absolute() or '..' in rel.parts or not source.is_relative_to(base) or any(part.startswith('.aura-') for part in rel.parts):raise ValueError('Unsafe manifest path')
        if source.stat().st_size!=item['bytes'] or digest(source)!=item['sha256']:raise ValueError('Base file verification failed: '+str(rel))
        if source.name=='direct_url.json':continue
        checked.append((source,rel))
    out.mkdir(parents=True)
    for source,rel in checked:
        target=out/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    shutil.copy2(base/'distribution-manifest.json',out/'distribution-manifest.json')
    for directory,dirs,files in os.walk(ROOT/'app'):
        dirs[:]=[d for d in dirs if d not in ('__pycache__','.aura-photo-data','.aura-data')]
        for name in files:
            if name.endswith(('.pyc','.pyo','.log')):continue
            source=Path(directory)/name;target=out/source.relative_to(ROOT/'app');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    print('Development copy ready:',out)
    print('Run:',out/'AURA Photo.exe')
    print('Re-run tools/build_installer.py to generate a current manifest after editing.')
if __name__=='__main__':main()
