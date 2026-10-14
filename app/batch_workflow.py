"""Selective parameter synchronization; original-coordinate strokes never copied."""
from pathlib import Path
import re
import cv2,numpy as np
from beauty_settings import EXTRA,ZONES,neutral_values
from feature_catalog import FACE_REPAIR,FACE_DETAILS,BODY,COLOR_FACE,COLOR_DATA,VOLUME,FORM
from reshape_settings import KEYS as SHAPE_KEYS
GROUPS={
 '基础美颜':['repair','smooth','whiten','texture'],
 '肤色与质感':[k for k,_,_,_ in EXTRA+COLOR_FACE+COLOR_DATA],
 '身体美颜':[k for k,_,_,_ in BODY],
 '分区域祛纹':[k for k,_,_,_ in ZONES],
 '瑕疵与保护':[k for k,_,_,_ in FACE_REPAIR+FACE_DETAILS],
 '光影丰盈':[k for k,_,_,_ in VOLUME],
 '脸型与五官':list(SHAPE_KEYS),
 '打光与改色':[],
}
COLOR_GROUPS={
 '基本影调与白平衡':('exposure','contrast','highlights','shadows','whites','blacks','temperature','tint','wb_kelvin','wb_tint','saturation','vibrance'),
 '曲线与HSL':(),
 '点颜色与分级':('shadow_hue','shadow_color','midtone_hue','midtone_color','highlight_hue','highlight_color','global_hue','global_color','shadow_luma','midtone_luma','highlight_luma','grading_balance','grading_blend','skin_protect'),
 '全图细节与效果':('texture','clarity','dehaze','denoise_luma','denoise_chroma','sharpen','sharpen_radius','sharpen_detail','sharpen_mask','bw','vignette','grain','grain_size'),
 '自动匹配各图镜头':(),
 '复制镜头校正参数':(),
 '透视与构图':(),
 '色彩输出设置':()}
COLOR_GROUPS['曲线与HSL']=tuple(k for k in __import__('creative_color').DEFAULTS if k.startswith('curve_'))
COLOR_GROUPS['点颜色与分级']+=('cal_shadow_tint',)+tuple(k for k in __import__('creative_color').DEFAULTS if k.startswith('cal_') and k!='cal_shadow_tint')
COLOR_GROUPS['全图细节与效果']+=tuple(k for k in __import__('creative_color').DEFAULTS if k.startswith(('vignette_','grain_','denoise_')) and k not in COLOR_GROUPS['全图细节与效果'])

NON_COLOR_GROUPS={'镜头与透视','自动匹配各图镜头','复制镜头校正参数','透视与构图','色彩输出设置'}
LEGACY_VALUES={'exposure','contrast','highlights','shadows','whites','blacks','temperature','tint','saturation','vibrance','shadow_hue','shadow_color','highlight_hue','highlight_color','skin_protect','lut_strength'}

def sync_color_groups(target,source,groups,metadata=None):
    import copy
    planned=copy.deepcopy(target)
    _sync_color_groups(planned,source,groups,metadata)
    target.clear();target.update(planned)

def _sync_color_groups(target,source,groups,metadata=None):
    import copy,creative_color as color
    src=color.validate(source.get('color',{}));dst=color.validate(target.get('color',{}))
    if {'自动匹配各图镜头','复制镜头校正参数'}<=set(groups):raise ValueError('镜头自动匹配与复制来源参数不能同时选择。')
    if dst['process']==1:
        fields={k for name in groups for k in COLOR_GROUPS.get(name,())}
        unsupported={k for k in fields-LEGACY_VALUES if src['values'][k]!=color.DEFAULTS[k]}
        if '点颜色与分级' in groups and src['point_colors']:unsupported.add('点颜色')
        if '全图细节与效果' in groups and any(src['bw_mix'].values()):unsupported.add('黑白混合')
        if unsupported:raise ValueError('目标照片使用旧调色引擎，无法同步：'+ '、'.join(sorted(unsupported))+'。请先在调色工作台切换为专业调色并确认效果，再重新同步。')
    for name in groups:
        for key in COLOR_GROUPS.get(name,()):dst['values'][key]=src['values'][key]
        if name=='基本影调与白平衡':dst['wb_sample']=copy.deepcopy(src.get('wb_sample'))
        if name=='曲线与HSL':
            for k in ('curve','points','hsl'):dst[k]=copy.deepcopy(src[k])
            dst['values']['curve_saturation']=src['values']['curve_saturation']
        if name=='点颜色与分级':dst['point_colors']=copy.deepcopy(src['point_colors'])
        if name=='全图细节与效果':dst['bw_mix']=copy.deepcopy(src['bw_mix']);dst['lut']=copy.deepcopy(src['lut']);dst['values']['lut_strength']=src['values']['lut_strength']
        if name=='镜头与透视':
            if 'optics' in source:target['optics']=copy.deepcopy(source['optics'])
            else:target.pop('optics',None)
        if name in ('自动匹配各图镜头','复制镜头校正参数','透视与构图'):
            from develop_optics import checked,LENS_KEYS,TRANSFORM_KEYS,DEFAULTS
            optics=copy.deepcopy(checked(target.get('optics',{})))
            source_optics=checked(source.get('optics',{}))
            if name=='自动匹配各图镜头':
                from lens_profiles import match
                meta=metadata or {};profile,crop=match(meta)
                if not profile:raise ValueError('当前照片没有唯一匹配的镜头配置，已保留原设置；请手动选择镜头配置后重试。')
                source_optics=checked(dict(DEFAULTS,enabled=True,profile=profile,crop_factor=crop or 1,focal=meta.get('focal_length',50) or 50,aperture=meta.get('aperture',5.6) or 5.6))
            for key in TRANSFORM_KEYS if name=='透视与构图' else LENS_KEYS:optics[key]=copy.deepcopy(source_optics[key])
            target['optics']=checked(optics)
        if name=='色彩输出设置':
            from develop_output import synced
            target['output']=synced(target.get('output',{}),source.get('output',{}))
    if any(name not in NON_COLOR_GROUPS for name in groups):
        # A partial sync must not reinterpret parameters outside its group.
        target['color']=color.validate(dst);target.pop('color_filter',None)

def merge_people(existing,source,groups,person=0,all_people=False):
    selected={k for name in groups for k in GROUPS[name]}
    targets=list(range(len(existing))) if all_people else ([person] if 0<=person<len(existing) else [])
    if not targets:raise ValueError('目标照片没有所选人物编号，请确认人物对应关系。')
    result=[dict(v) for v in existing]
    for i in targets:
        for k in selected:result[i][k]=source[k]
    return result

def raw_requirement(target,source,groups,metadata=None):
    """Plan the final colour before changing a target photograph."""
    import copy
    selected=[g for g in groups if g in COLOR_GROUPS]
    planned=copy.deepcopy(target)
    if '全局调色' in groups:
        ref=source.get('reference',{})
        if ref.get('target_roi') is not None or ref.get('target_person') is not None:
            raise ValueError('参考追色指定了单图人物或取样框，请逐图确认区域后再应用；不能直接复制到其他照片。')
        for key in ('color','color_filter','reference'):
            if key in source:planned[key]=copy.deepcopy(source[key])
            else:planned.pop(key,None)
    if selected:sync_color_groups(planned,source,selected,metadata)
    if '全局调色' not in groups and not any(g not in NON_COLOR_GROUPS for g in selected):return None
    from fuji_profiles import required_base
    return {'raw_base':required_base(planned)}

def prepare(app,values):
    """Called in app worker, using this photo's masks/landmarks and cached models."""
    from damo_engine import inpaint_portrait
    from face_details import prepare_face_repairs
    from body_details import prepare_body
    from portrait_effects import prepare_eye_wrinkles,eye_wrinkle_pending
    from body_shape import prepare_forms
    import face_reshape
    session=app.session;selected=app.selection.mask;done=app.done_mask.copy();generated=app.generated
    wanted=np.zeros(selected.shape,bool)
    for i,v in enumerate(values):
        if v['repair']<=0:continue
        f=session.faces[i];a,b,c,d=f.box;wanted[b:d,a:c]|=selected[b:d,a:c]&app.selection.auto[b:d,a:c]&session.repair_safe[i]
    needed=wanted&~(done>0)
    if needed.any():
        fresh,_=inpaint_portrait(session.original,needed&~(app.small_mask>0),app.progress,app.cancel,precision=True,retouch_engine=getattr(session,'retouch_engine',1))
        if generated is not None:
            output=generated.copy();output[needed]=fresh[needed];generated=output
        else:generated=fresh
        done|=needed
    session.detail_cache=prepare_face_repairs(session,values,app.region_layers,app.progress,app.cancel)
    prepare_body(session,values,app.region_layers,app.progress,app.cancel)
    if eye_wrinkle_pending(session,values):session.eye_wrinkle_cache=prepare_eye_wrinkles(session,values,app.progress,app.cancel)
    forms=prepare_forms(app.document.base_float(),session,values,app.region_layers,app.progress,app.cancel)
    reshape=face_reshape.prepare(session,values,app.reshape_cache,app.progress,app.cancel)
    return generated,done,forms,reshape

def destination(folder,stem,extension,index):
    folder=Path(folder);stem=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',stem).strip(' .')[:110] or 'photo'
    suffix=extension.lower()
    if suffix not in ('.tif','.png','.jpg'):raise ValueError('批量导出格式无效。')
    p=folder/f'{stem}-AURA-{index:03d}{suffix}';counter=2
    while p.exists():p=folder/f'{stem}-AURA-{index:03d}-{counter}{suffix}';counter+=1
    return p

def resize_output(image,max_edge):
    edge=int(max_edge)
    if not 0<=edge<=16000:raise ValueError('导出长边需在0–16000像素范围。')
    if not edge or max(image.shape[:2])<=edge:return image
    h,w=image.shape[:2];factor=edge/max(h,w)
    return cv2.resize(image,(max(1,round(w*factor)),max(1,round(h*factor))),interpolation=cv2.INTER_AREA)
