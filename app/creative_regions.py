"""Shared original-coordinate regions for color, lighting and creative retouch."""
import hashlib
import cv2,numpy as np
from region_masks import part_mask,face_beauty_mask
from body_details import body_scope

def regions(session,layers=None):
    layers=layers or [];h,w=session.original.shape[:2]
    custom=[l for l in layers if l.get('feature_key')=='body_skin']
    signature=tuple((l.get('person_index'),l.get('enabled',True),l.get('parameters',{}).get('expand',0),hashlib.blake2b(np.packbits(l['mask']),digest_size=8).hexdigest()) for l in custom)
    edits=tuple((name,fi,hashlib.blake2b(np.packbits(mask),digest_size=8).hexdigest())
                for name in ('body_beauty_include','body_beauty_exclude')
                for fi,mask in sorted(getattr(session,name,{}).items()))
    signature=(3,signature,edits,tuple(hashlib.blake2b(np.packbits(face_beauty_mask(session,i)>0),digest_size=8).hexdigest() for i in range(len(session.faces))))
    old=getattr(session,'creative_regions',None)
    if old and old.get('signature')==signature:return old
    people=[];skin=np.zeros((h,w),bool);whole=np.zeros_like(skin);clothes=np.zeros_like(skin)
    for fi,f in enumerate(session.faces):
        face=part_mask(session,fi,'skin');body=body_scope(session,fi,layers);person=part_mask(session,fi,'person')
        # Share corrected cheek/chin coverage with beauty, but never sample
        # brows, eyes or lip makeup as skin colour. Beauty also treats those.
        a,b,c,d=f.box
        corrected=face_beauty_mask(session,fi)>0
        parts=session.part_regions[fi]
        mouth=np.isin(session.part_labels[fi],[11,12,13]).astype(np.uint8)
        if hasattr(f,'points'):
            ids=[78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95]
            cv2.fillPoly(mouth,[(f.points[ids]-[a,b]).astype(np.int32)],1)
        face[b:d,a:c]=corrected&~(parts['eyes']|parts['brows']|parts['lips']|parts['teeth']|(mouth>0))
        hair=part_mask(session,fi,'hair');cloth=part_mask(session,fi,'clothes');lips=part_mask(session,fi,'lips')
        # Semantic head hair supplements coarse whole-person segmentation.
        a,b,c,d=f.box;local=getattr(session,'part_labels',[])
        if fi<len(local):hair[b:d,a:c]|=local[fi]==17
        own=getattr(session,'person_owner',None)
        if isinstance(own,np.ndarray):hair&=(own==0)|(own==fi+1)
        illumination=body.copy();a,b,c,d=f.box;illumination[b:d,a:c]|=face_beauty_mask(session,fi)>0
        veto=np.zeros((h,w),bool)
        if isinstance(own,np.ndarray):veto|=(own>0)&(own!=fi+1)
        for other,g in enumerate(session.faces):
            if other==fi:continue
            x,y,z,t=g.box;veto[y:t,x:z]|=g.mask>0
        face&=~veto;body&=~veto;lips&=~veto;hair&=~veto;illumination&=~veto;cloth&=~veto
        cloth&=~(face|body|hair|lips)
        # Confirmed skin/hair cannot simultaneously be classified as background.
        person|=face|body|hair|cloth|lips
        record=dict(skin=face|body,light=illumination,face=face,body=body,person=person,hair=hair,clothes=cloth,lips=lips)
        people.append(record);skin|=record['skin'];whole|=person;clothes|=cloth
    result=dict(signature=signature,people=people,skin=skin,person=whole,clothes=clothes,background=~whole)
    for key in ('face','body','hair'):
        result[key]=np.logical_or.reduce([p[key] for p in people]) if people else np.zeros_like(skin)
    session.creative_regions=result;return result
