"""Cached still-photo body pose and conservative inverse body geometry."""
import numpy as np,cv2
from person_masks import pose_instances,match_faces
from live_body import BODY_KEYS,body_controls,build_body_field,apply_body_field

def values(people,fallback):
    source=people[0] if len(people)==1 else fallback
    return {k:float(source.get(k,0)) for k in BODY_KEYS}

def active(people,fallback):
    return any(values(people,fallback).values()) or any(row.get(k,0) for row in people for k in BODY_KEYS)

def analyze(session,cancel=None):
    if cancel is not None and cancel.is_set():raise InterruptedError('已取消人体识别。')
    poses,masks=pose_instances(session.original,confidence=.55)
    if cancel is not None and cancel.is_set():raise InterruptedError('已取消人体识别。')
    if len(poses)!=1 or len(session.faces)>1:return {'reason':'当前照片模式仅支持唯一、可靠的人体；多人或未检出时不应用。'}
    pose=poses[0]
    if session.faces and not match_faces(session.faces,[pose])[0]:return {'reason':'人脸与身体归属不能确认，未应用身体美型。'}
    return {'pose':pose,'mask':masks[0],'shape':session.original.shape[:2],'face':session.faces[0] if session.faces else None}

def apply(rgb,session,people,fallback,cache):
    parameters=values(people,fallback)
    if not active(people,fallback):return rgb,False,'身体美型已关闭。',cache
    analysis=cache.get('analysis')
    if analysis is None:return rgb,False,'身体美型待识别。',cache
    if analysis.get('reason'):return rgb,False,analysis['reason'],cache
    signature=tuple(round(parameters[k],4) for k in BODY_KEYS)
    fields=dict(cache.get('fields',{}));entry=fields.get(signature)
    if entry is None:
        control,reason,features=body_controls(analysis['pose'],analysis['mask'],analysis['shape'],parameters)
        field=None if control is None else build_body_field(session.original,analysis['mask'],control,analysis['face'],protect_lines=True)
        if control is None:note=reason
        elif field is None:note='当前参数会过度挤压网格，身体美型未应用。'
        else:
            note='已应用：'+'、'.join(features)
            if control['notes']:note+='；'+'；'.join(control['notes'])
            if field['effective_scale']<1:note+='；已降低强度保护背景和边缘'
        entry={'field':field,'note':note,'features':features};fields[signature]=entry
        if len(fields)>3:fields.pop(next(iter(fields)))
    updated=dict(cache,fields=fields,last_signature=signature)
    if entry['field'] is None:return rgb,False,entry['note'],updated
    return apply_body_field(rgb,entry['field']),True,entry['note'],updated

def current_field(cache):return cache.get('fields',{}).get(cache.get('last_signature'),{}).get('field')

def inverse_points(points,field):
    q=np.asarray(points,dtype=np.float32).copy()
    if field is None:return q
    a,b,c,d=field['roi'];grid=field['grid'];h,w=grid.shape[:2]
    inside=(q[:,0]>=a)&(q[:,0]<=c-1)&(q[:,1]>=b)&(q[:,1]<=d-1)
    delta=cv2.remap(grid,((q[:,0]-a)*(w-1)/(c-a-1))[:,None],((q[:,1]-b)*(h-1)/(d-b-1))[:,None],cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)[:,0]
    q[inside]+=delta[inside];return q

def display_mask(mask,cache):
    field=current_field(cache)
    if field is None:return mask
    return apply_body_field(mask.astype(np.uint8),field)>0
