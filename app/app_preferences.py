"""Persistent per-user import preference, independent of photo edit state."""
import json,os
from pathlib import Path
from core import ROOT
CONFIG=Path(os.environ.get('AURA_DATA_DIR',str(ROOT/'.aura-data')))/'preferences.json'
LEGACY=CONFIG

def preferences():
    try:data=json.loads((CONFIG if CONFIG.exists() else LEGACY).read_text(encoding='utf8'))
    except (OSError,ValueError):return {}
    return data if isinstance(data,dict) else {}

def save_preferences(values):
    data=preferences();data.update(values);CONFIG.parent.mkdir(parents=True,exist_ok=True)
    temp=CONFIG.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(CONFIG)

def auto_recommend_enabled():
    value=preferences().get('auto_recommend',True)
    return value if type(value) is bool else True

def save_auto_recommend(enabled):
    if type(enabled) is not bool:raise ValueError('自动推荐开关无效。')
    save_preferences(dict(auto_recommend=enabled))
