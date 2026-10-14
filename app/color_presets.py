"""AURA and licensed adapted recipes with non-accumulating preset amounts.

Recipes change only named controls. Exposure, neutral WB samples, optics,
local masks and retouching remain photo-specific. No Adobe preset assets.
"""
import copy, hashlib, json, math, uuid
import numpy as np
import creative_color as color
import point_curves


def preset(key, name, group, description, values, hsl=None, points=None, bw_mix=None):
    recipe={'values':values}
    if hsl:recipe['hsl']=hsl
    if points:recipe['points']=points
    if bw_mix:recipe['bw_mix']=bw_mix
    return dict(id=key,name=name,group=group,description=description,recipe=recipe)


from filter_recipes import build as revised_looks
BUILTINS=revised_looks(preset)
GROUPS=['全部','人像','日系','日系参考','胶片','电影','风光','黑白','开源精选','收藏','我的']
from reference_filter_recipes import build as reference_looks
BUILTINS+=reference_looks(preset)
RECIPE_KEYS={'values','hsl','points','curve','bw_mix','lut','point_colors','wb_sample'}
PHOTO_KEYS={'exposure','wb_kelvin','wb_tint','lut_strength','sharpen_radius','sharpen_detail','sharpen_mask','denoise_luma','denoise_chroma'}


def checked_recipe(recipe):
    if not isinstance(recipe,dict) or set(recipe)-RECIPE_KEYS:raise ValueError('滤镜配方格式无效。')
    checked=color.validate(dict(recipe,process=2))
    from portable_lut import pack
    return {k:pack(checked[k]) if k=='lut' else copy.deepcopy({n:checked[k][n] for n in recipe[k]} if k in ('values','hsl','points','bw_mix') else checked[k]) for k in recipe}


def checked_preset(item):
    if not isinstance(item,dict):raise ValueError('滤镜记录无效。')
    for k,limit in [('id',80),('name',30),('description',200)]:
        if not isinstance(item.get(k),str) or not 1<=len(item[k])<=limit:raise ValueError('滤镜名称或说明无效。')
    group='富士' if item.get('group')=='富士RAW' else item.get('group')
    if group not in GROUPS:raise ValueError('滤镜分类无效。')
    out=dict(id=item['id'],name=item['name'],description=item['description'],group=group,recipe=checked_recipe(item['recipe']))
    if item.get('raw_base') is not None:
        if item['raw_base'] not in ({'process':1,'profile':'Adobe Standard Linear'},{'process':1,'profile':'Adobe Standard Linear','baseline_mode':'adobe-v1'}):raise ValueError('RAW滤镜基底无效。')
        out['raw_base']=dict(item['raw_base'])
    from fuji_profiles import required_base
    dependency=required_base({'color':out['recipe']})
    if dependency and 'raw_base' not in out:out['raw_base']=dependency
    if item.get('source') is not None:
        source=item['source']
        if not isinstance(source,dict) or set(source)!={'label','url','license','sha256'}:raise ValueError('滤镜来源记录无效。')
        for key,limit in [('label',160),('url',1000),('license',80),('sha256',64)]:
            if not isinstance(source[key],str) or len(source[key])>limit:raise ValueError('滤镜来源记录无效。')
        if source['url'] and not source['url'].startswith('https://'):raise ValueError('滤镜来源网址无效。')
        if len(source['sha256'])!=64 or any(c not in '0123456789abcdef' for c in source['sha256']):raise ValueError('滤镜来源校验无效。')
        out['source']=copy.deepcopy(source)
    return out


def plain(data):
    return color.validate(copy.deepcopy(data))


def signature(data):
    def normalized(value):
        if isinstance(value,dict):return {k:normalized(v) for k,v in value.items()}
        if isinstance(value,list):return [normalized(v) for v in value]
        if type(value) in (int,float):return float(value)
        return value
    canonical=plain(data)
    if canonical['lut'] is not None:
        from portable_lut import pack
        canonical['lut']=pack(canonical['lut'])
    from develop_advanced import CONTROLS
    for key,_,_,_,default in CONTROLS:
        if canonical['values'].get(key)==default:canonical['values'].pop(key,None)
    for record in canonical['point_colors']:
        if record.get('variance')==0:record.pop('variance',None)
    return hashlib.sha256(json.dumps(normalized(canonical),sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def overlay(base,recipe):
    out=plain(base)
    for k,v in recipe.items():
        if k in ('curve','lut','point_colors','wb_sample'):out[k]=copy.deepcopy(v)
        else:out[k].update(copy.deepcopy(v))
    return out


def capture_base(base,recipe):
    source=plain(base);out={'process':source['process']}
    for k,v in recipe.items():
        if k=='lut':
            from portable_lut import pack
            out[k]=pack(source[k])
        elif k in ('curve','point_colors','wb_sample'):out[k]=copy.deepcopy(source[k])
        else:out[k]={n:copy.deepcopy(source[k][n]) for n in v if n in source[k]}
    return out


def restore_base(current,state):
    base=plain(current)
    for k,values in state['preset']['recipe'].items():
        if k not in ('values','curve','lut','point_colors','wb_sample'):
            for name in values:
                if name not in state['base'][k]:base[k].pop(name,None)
    base=overlay(base,{k:v for k,v in state['base'].items() if k!='process'})
    base['process']=state['base']['process'];return base


def blend(base,recipe,amount):
    if type(amount) not in (float,int) or not math.isfinite(amount) or not 0<=amount<=200:raise ValueError('滤镜强度须为 0–200。')
    base=plain(base);target=overlay(base,checked_recipe(recipe));t=amount/100
    if t==0:return base
    if t==1:target['process']=2;return plain(target)
    out=copy.deepcopy(base);out['process']=2
    if 'wb_sample' in recipe:out['wb_sample']=copy.deepcopy(target['wb_sample'])
    for k in recipe.get('values',{}):
        a,b=base['values'][k],target['values'][k]
        # A hue with zero saturation has no meaning: avoid a rotating tint as
        # intensity rises from a neutral starting point.
        if k in ('grain_model','vignette_style','hue_stability','channel_curve_saturation','grading_warm_protect'):out['values'][k]=b
        elif k.endswith('_hue') and k[:-4]+'_color' in color.DEFAULTS:
            sat=k[:-4]+'_color'
            out['values'][k]=b if base['values'][sat]==0 else a if target['values'][sat]==0 else (a+((b-a+180)%360-180)*t)%360
        else:out['values'][k]=a+(b-a)*t
    for k in ('hsl','bw_mix'):
        for n in recipe.get(k,{}):
            a=base[k].get(n,[0,0,0] if k=='hsl' else 0);b=target[k][n]
            out[k][n]=[x+(y-x)*t for x,y in zip(a,b)] if k=='hsl' else a+(b-a)*t
    if 'curve' in recipe:out['curve']=[a+(b-a)*t for a,b in zip(base['curve'],target['curve'])]
    if 'point_colors' in recipe:
        # Interpolate each selection slot; keep the portable eight-slot limit.
        fields=('hue_shift','saturation','luminance','variance')
        old=base['point_colors'];new=target['point_colors']
        out['point_colors']=[]
        for index in range(max(len(old),len(new))):
            a=old[index] if index<len(old) else dict(new[index],**dict.fromkeys(fields,0))
            b=new[index] if index<len(new) else dict(old[index],**dict.fromkeys(fields,0))
            record=copy.deepcopy(b)
            for key in record:
                if key not in fields:
                    record[key]=(a[key]+((b[key]-a[key]+180)%360-180)*min(t,1))%360 if key=='hue' else a[key]+(b[key]-a[key])*min(t,1)
            for field in fields:
                record[field]=float(np.clip(a[field]+(b[field]-a[field])*t,-100,100))
            out['point_colors'].append(record)
    if 'lut' in recipe:
        from portable_lut import mix_effects
        out['lut'],out['values']['lut_strength']=mix_effects(base['lut'],base['values']['lut_strength'],target['lut'],target['values']['lut_strength'],t)
    for channel in recipe.get('points',{}):
        a=base['points'].get(channel,point_curves.IDENTITY);b=target['points'][channel]
        # A shared sampling grid preserves cubic curve shape while keeping the
        # persisted curve within the engine's 64-point limit.
        xs=np.linspace(0,1,64);ys=point_curves.evaluate(xs,a)*(1-t)+point_curves.evaluate(xs,b)*t
        out['points'][channel]=np.column_stack((xs,ys)).tolist()
    limits={k:(lo,hi) for k,_,lo,hi in color.CONTROLS}
    for k,value in out['values'].items():
        lo,hi=limits[k];out['values'][k]=float(np.clip(value,lo,hi))
    for k in ('hsl','bw_mix'):
        for name,value in out[k].items():out[k][name]=np.clip(value,-100,100).tolist() if isinstance(value,list) else float(np.clip(value,-100,100))
    out['curve']=np.clip(out['curve'],-100,100).tolist()
    keys=('curve_split_shadow','curve_split_mid','curve_split_highlight');splits=sorted(out['values'][k] for k in keys)
    splits[0]=float(np.clip(splits[0],1,97));splits[1]=float(np.clip(splits[1],splits[0]+1,98));splits[2]=float(np.clip(splits[2],splits[1]+1,99))
    for k,value in zip(keys,splits):out['values'][k]=value
    for pts in out['points'].values():
        for point in pts:point[1]=float(np.clip(point[1],0,1))
    return plain(out)


def checked_state(state):
    if not isinstance(state,dict) or set(state)!={'preset','base','amount','signature'}:raise ValueError('滤镜项目记录无效。')
    item=checked_preset(state['preset']);amount=state['amount'];base=state['base']
    if not isinstance(base,dict) or type(base.get('process')) is not int or base['process'] not in (1,2):raise ValueError('滤镜原始状态无效。')
    checked_recipe({k:v for k,v in base.items() if k!='process'})
    if set(base)-{'process'}!=set(item['recipe']):raise ValueError('滤镜原始状态不完整。')
    for k in item['recipe']:
        if k not in ('curve','lut','point_colors','wb_sample') and not set(base[k])<=set(item['recipe'][k]):raise ValueError('滤镜原始参数无效。')
        if k=='values' and set(base[k])!=set(item['recipe'][k]):raise ValueError('滤镜原始参数不完整。')
    if type(amount) not in (float,int) or not math.isfinite(amount) or not 0<=amount<=200:raise ValueError('滤镜强度无效。')
    if not isinstance(state['signature'],str) or len(state['signature'])!=64 or any(c not in '0123456789abcdef' for c in state['signature']):raise ValueError('滤镜参数校验无效。')
    result=copy.deepcopy(state);result['preset']=item
    return result


def switching_base(current,state):
    """Remove the previous preset while retaining independent manual edits."""
    current=plain(current)
    if not state:return current
    restored=restore_base(current,state)
    if signature(current)==state['signature']:return restored
    expected=blend(restored,state['preset']['recipe'],state['amount'])
    def same_lut(a,b):
        if a is None or b is None:return a is b
        from portable_lut import pack
        a,b=pack(a),pack(b)
        return all(a.get(k)==b.get(k) for k in ('size','min','max','data_sha256'))
    for key,values in state['preset']['recipe'].items():
        if key=='lut':
            if not same_lut(current[key],expected[key]):restored[key]=current[key]
        elif key in ('curve','point_colors','wb_sample'):
            if current[key]!=expected[key]:restored[key]=current[key]
        else:
            for name in values:
                if current[key].get(name)!=expected[key].get(name):
                    if name in current[key]:restored[key][name]=copy.deepcopy(current[key][name])
                    else:restored[key].pop(name,None)
    return restored

def apply_preset(current,item,amount=100,state=None):
    item=checked_preset(item);current=plain(current)
    base=switching_base(current,state)
    out=blend(base,item['recipe'],amount)
    record=dict(preset=item,base=capture_base(base,item['recipe']),amount=amount,signature=signature(out))
    return out,record


def capture_style(current,name,raw_base=None):
    data=plain(current)
    recipe={k:copy.deepcopy(data[k]) for k in ('hsl','points','curve','bw_mix','point_colors')}
    recipe['values']={k:v for k,v in data['values'].items() if k not in PHOTO_KEYS}
    if data['lut'] is not None:
        from portable_lut import pack
        recipe['lut']=pack(data['lut']);recipe['values']['lut_strength']=data['values']['lut_strength']
    item=preset('user-'+uuid.uuid4().hex,name,'我的','个人风格；保留曝光与拍摄白平衡，包含已使用的LUT。',recipe['values']) | {'recipe':recipe}
    if raw_base:item['raw_base']=raw_base
    return checked_preset(item)


class PresetLibrary:
    def __init__(self,path):self.path=path;self.error='';self.custom=[];self.external=[];self.favorites=[];self.load()
    def load(self):
        if not self.path.exists():return
        try:
            if self.path.stat().st_size>48_000_000:raise ValueError('个人滤镜库过大。')
            data=json.loads(self.path.read_text(encoding='utf8'))
            if data.get('schema')!=1 or not isinstance(data.get('custom'),list) or len(data['custom'])>100:raise ValueError('个人滤镜库格式无效。')
            custom=[checked_preset(x) for x in data['custom']]
            ids={x['id'] for x in BUILTINS+custom}
            if len(ids)!=len(BUILTINS)+len(custom):raise ValueError('个人滤镜编号重复。')
            favorites=data.get('favorites',[])
            if not isinstance(favorites,list) or any(not isinstance(x,str) for x in favorites):raise ValueError('收藏记录无效。')
            self.custom=custom;self.favorites=list(dict.fromkeys(favorites))
        except (OSError,ValueError,TypeError,KeyError,AttributeError) as e:self.error=str(e)
    def save(self):
        if self.error:raise ValueError('个人滤镜库读取失败，已保留原文件：'+self.error)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        text=json.dumps(dict(schema=1,custom=self.custom,favorites=self.favorites),ensure_ascii=False,allow_nan=False,indent=2)
        if len(text.encode('utf8'))>48_000_000:raise ValueError('个人滤镜库超过48MB。')
        temp=self.path.with_suffix('.tmp');temp.write_text(text,encoding='utf8');temp.replace(self.path)
    def items(self,group='全部',query=''):
        if group=='富士RAW':group='富士'  # Existing callers and saved categories.
        return [copy.deepcopy(x) for x in BUILTINS+self.external+self.custom if
                (group=='全部' or group=='收藏' and x['id'] in self.favorites or x['group']==group)
                and query.casefold().strip() in (x['name']+' '+x['description']+' '+x['group']).casefold()]

COLLECTION_ERROR=''
try:
    from pathlib import Path
    collection=json.loads((Path(__file__).resolve().parent/'assets/color-filters/open-presets.json').read_text(encoding='utf8'))
    if collection.get('schema')!=1:raise ValueError('开源滤镜集格式无效。')
    added=[checked_preset(item) for item in collection['presets']]
    if len({item['id'] for item in BUILTINS+added})!=len(BUILTINS+added):raise ValueError('开源滤镜编号重复。')
    BUILTINS+=added
except (OSError,ValueError,KeyError,TypeError) as error:
    COLLECTION_ERROR=str(error)

# Only newly selected builtin cards opt in; checked_state/checked_preset must
# never rewrite an embedded historical recipe or a personal style.
for item in BUILTINS:
    item['recipe']['values']['hue_stability']=100
