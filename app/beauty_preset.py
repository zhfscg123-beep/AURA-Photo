"""Portable numeric beauty recipes: never reuse another photograph's geometry."""
import json,math
from pathlib import Path
from beauty_settings import DEFAULTS,RANGES
from aura_version import VERSION

KIND='local-portrait-beauty-preset'
MAX_BYTES=64*1024

def checked(values):
    if not isinstance(values,dict) or not values:raise ValueError('配置中没有美颜参数。')
    unknown=set(values)-set(DEFAULTS)
    if unknown:raise ValueError('配置含当前版本不支持的参数：'+', '.join(sorted(unknown)))
    result=dict(DEFAULTS)
    for key,value in values.items():
        lo,hi=RANGES[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError('美颜参数超出范围：'+key)
        result[key]=value
    return result

def write_preset(path,values,name='人像美颜配置'):
    path=Path(path);parameters=checked(values)
    if path.exists():raise ValueError('配置文件已存在，请另存新文件名。')
    payload=dict(kind=KIND,schema=2,app_version=VERSION,name=str(name)[:120],parameters=parameters)
    with path.open('x',encoding='utf8') as stream:json.dump(payload,stream,ensure_ascii=False,indent=2,allow_nan=False)

def read_preset(path):
    path=Path(path)
    if path.stat().st_size>MAX_BYTES:raise ValueError('配置文件过大。')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or data.get('kind')!=KIND or type(data.get('schema')) is not int or data['schema'] not in (1,2):
        raise ValueError('这不是受支持的人像美颜配置；照片项目请使用“打开项目”。')
    values=checked(data.get('parameters'))
    return values,str(data.get('name','人像美颜配置'))[:120]
