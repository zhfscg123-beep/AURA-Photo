"""Offline display localization. Editing values, paths and project keys stay canonical."""
from pathlib import Path
import json,os,re,threading
ROOT=Path(__file__).resolve().parent
LANGUAGES=('zh_CN','en_US')
_catalog={};_templates=[];_language=None;_installed=False;_lock=threading.RLock()
def _read(path):
    try:
        value=json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}
def preferences_path():return Path(os.environ.get('AURA_DATA_DIR',str(ROOT/'.aura-photo-data')))/'preferences.json'
def language():
    global _language
    if _language is None:
        value=os.environ.get('AURA_LANGUAGE') or _read(preferences_path()).get('language') or _read(ROOT/'installed-language.json').get('language','zh_CN')
        _language=value if value in LANGUAGES else 'zh_CN'
    return _language
def load_catalog():
    global _catalog,_templates
    _catalog=_read(ROOT/'locales/en_US.json')
    records=_read(ROOT/'locales/templates-en_US.json');_templates=[]
    for source,target in sorted(records.items(),key=lambda item:len(item[0]),reverse=True):
        parts=re.split(r'(\{\d+\})',source);pattern='';seen=set()
        for part in parts:
            if re.fullmatch(r'\{\d+\}',part):
                key='p'+part[1:-1]
                pattern+=f'(?P={key})' if key in seen else f'(?P<{key}>.*?)';seen.add(key)
            else:pattern+=re.escape(part)
        _templates.append((re.compile('^'+pattern+'$',re.S),target))
def tr(value,lang=None):
    if not isinstance(value,str) or (lang or language())=='zh_CN':return value
    if value in _catalog:return _catalog[value]
    marker=re.match(r'^([▾▸▶▼→✓•]\s+)(.+)$',value,re.S)
    if marker:return marker[1]+tr(marker[2],lang)
    for pattern,target in _templates:
        match=pattern.fullmatch(value)
        if match:
            return re.sub(r'\{(\d+)\}',lambda m:tr(match.group('p'+m[1]),lang),target)
    # Translate known concatenated messages without translating file paths or
    # arbitrary user-authored names inside them.
    if '\n' in value:return '\n'.join(tr(line,lang) for line in value.split('\n'))
    for separator in (' · ',' › ',' → '):
        if separator in value:return separator.join(tr(part,lang) for part in value.split(separator))
    for source in _prefixes:
        if value.startswith(source):return _catalog[source]+value[len(source):]
    luminance=re.fullmatch(r'(红|橙|黄|绿|青|蓝|紫|洋红)明度',value)
    if luminance:return tr(luminance[1],lang)+' luminance'
    return value
_prefixes=[]
def set_language(value):
    global _language
    if value not in LANGUAGES:raise ValueError('Unsupported interface language')
    with _lock:
        path=preferences_path();data=_read(path);data['language']=value
        path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.language.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)
        _language=value
    from localized_tk import refresh
    refresh()
def install():
    global _installed,_prefixes
    if _installed:return
    load_catalog();_prefixes=sorted((s for s in _catalog if s.endswith(('：',':',' ')) and s.strip()),key=len,reverse=True)
    from localized_tk import install as install_tk
    install_tk();_installed=True
