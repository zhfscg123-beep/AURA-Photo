"""Persistent ratings for original file identities; never modify photo files."""
import json,os,time,hashlib
from pathlib import Path
from core import ROOT
import cv2,numpy as np

def identity(path,stamp):
    value=str(Path(path).resolve()).casefold()+'|'+str(tuple(stamp))
    return hashlib.sha256(value.encode()).hexdigest()

class Catalog:
    def __init__(self):
        self.path=Path(os.environ.get('AURA_DATA_DIR',str(ROOT/'.aura-data')))/'photo-catalog.json'
        try:
            data=json.loads(self.path.read_text(encoding='utf8'))
            self.records=data['records'] if data.get('schema')==1 and isinstance(data.get('records'),dict) else {}
        except (OSError,ValueError,KeyError,TypeError):self.records={}
    def get(self,entry):
        data=self.records.get(identity(entry['path'],entry['stamp']),{})
        if not isinstance(data,dict):data={}
        return dict(rating=data.get('rating',0) if type(data.get('rating',0)) is int and 0<=data.get('rating',0)<=5 else 0,
                    flag=data.get('flag','未标记') if data.get('flag','未标记') in ('未标记','保留','待剔除') else '未标记',
                    label=data.get('label','无') if data.get('label','无') in ('无','红','黄','绿','蓝','紫') else '无')
    def set(self,entries,**changes):
        if 'rating' in changes and (type(changes['rating']) is not int or not 0<=changes['rating']<=5):raise ValueError('评分应为0–5')
        if 'flag' in changes and changes['flag'] not in ('未标记','保留','待剔除'):raise ValueError('标记无效')
        if 'label' in changes and changes['label'] not in ('无','红','黄','绿','蓝','紫'):raise ValueError('颜色标签无效')
        updated=dict(self.records)
        for entry in entries:updated[identity(entry['path'],entry['stamp'])]=dict(self.get(entry),**changes,path=str(entry['path']),updated=time.time())
        self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_suffix('.tmp')
        try:temp.write_text(json.dumps(dict(schema=1,records=updated),ensure_ascii=False,indent=2),encoding='utf8');temp.replace(self.path)
        finally:temp.unlink(missing_ok=True)
        self.records=updated
    def select(self,entries,query='',rating=0,flag='全部',sort='文件名'):
        result=[(key,e) for key,e in entries.items() if query.casefold() in e['path'].name.casefold() and self.get(e)['rating']>=rating and (flag=='全部' or self.get(e)['flag']==flag)]
        return sorted(result,key=lambda pair:(-self.get(pair[1])['rating'],pair[1]['path'].name.casefold()) if sort=='评分' else pair[1]['path'].name.casefold())

def quality_hint(thumb):
    """Thumbnail indicators for manual review, not semantic/closed-eye predictions."""
    gray=cv2.cvtColor(np.asarray(thumb.convert('RGB')),cv2.COLOR_RGB2GRAY)
    return dict(sharpness=round(float(cv2.Laplacian(gray,cv2.CV_32F).var()),1),
                dark_percent=round(float((gray<12).mean()*100),1),bright_percent=round(float((gray>243).mean()*100),1))
