"""Conservative foreground-only deformation, cached LaMa vacancy repair.

Optional experiments: no double-chin/armpit-specific classifier is claimed.
Confidence gates skip hidden armpits; no background pixel is resampled.
"""
import copy,hashlib
import cv2,numpy as np
from body_details import body_scope
from portrait_effects import face_alpha
from region_masks import soft_edge
from feature_catalog import FORM,FORM_GEOMETRY
def spec(session,fi,key,layers):
 if getattr(session,'body_owner',None) is None:return None
 f=session.faces[fi];p=f.points.astype(np.float32);down=p[152]-p[10];down/=max(1,np.linalg.norm(down));scope=body_scope(session,fi,layers)
 h,w=scope.shape;fw=f.width
 if key=='double_chin':
  centre=p[152]+down*fw*.035;rx,ry=fw*.4,fw*.22;movement=-down*fw*.025
 else:
  pose=getattr(session,'person_landmarks',{}).get(fi)
  ids=(11,13) if key=='armpit_left' else (12,14)
  if pose is None or float(np.min(pose[list(ids),2:]))<.7:return None
  left,right=pose[11,:2],pose[12,:2];sw=float(np.linalg.norm(left-right))
  if sw<fw*.8:return None
  shoulder,elbow=pose[ids[0],:2],pose[ids[1],:2];middle=(left+right)/2
  centre=shoulder+(elbow-shoulder)*.22+down*sw*.04;rx,ry=sw*.20,sw*.22
  inward=middle-shoulder;inward/=max(1,np.linalg.norm(inward));movement=inward*sw*.025
  x,y=int(centre[0]),int(centre[1]);a,b=max(0,int(x-rx)),max(0,int(y-ry));c,d=min(w,int(x+rx+1)),min(h,int(y+ry+1))
  if a>=c or b>=d or scope[b:d,a:c].sum()<max(25,sw*sw*.003):return None
 radius=max(rx,ry);a,b=max(0,int(centre[0]-radius*2)),max(0,int(centre[1]-radius*2));c,d=min(w,int(centre[0]+radius*2+1)),min(h,int(centre[1]+radius*2+1))
 if c-a<8 or d-b<8:return None
 mask=scope[b:d,a:c].copy()
 if key=='double_chin':
  x,y,z,t=f.box;alpha=face_alpha(session,fi)>0
  aa,bb,cc,dd=max(a,x),max(b,y),min(c,z),min(d,t)
  if aa<cc and bb<dd:mask[bb-b:dd-b,aa-a:cc-a]|=alpha[bb-y:dd-y,aa-x:cc-x]
 for oi,other in enumerate(session.faces):
  if oi==fi:continue
  x,y,z,t=other.box;aa,bb,cc,dd=max(a,x),max(b,y),min(c,z),min(d,t)
  if aa<cc and bb<dd:mask[bb-b:dd-b,aa-a:cc-a]=False
 alpha=soft_edge(mask,2)
 owner=getattr(session,'person_owner',session.body_owner);allowed=(owner[b:d,a:c]==0)|(owner[b:d,a:c]==fi+1)
 # Competition gates protect any other detected person, including their clothes.
 signature=hashlib.sha256(np.packbits(mask).tobytes()+np.packbits(allowed).tobytes()).hexdigest()
 return dict(box=[a,b,c,d],alpha=alpha,allowed=allowed,center=centre-[a,b],rx=rx,ry=ry,down=down,vector=movement,signature=signature)
def maps(item,strength):
 h,w=item['alpha'].shape;yy,xx=np.mgrid[:h,:w].astype(np.float32);vec=item['vector']*strength/100
 center=item['center']+vec
 down=item['down'];side=np.array([down[1],-down[0]]);dx,dy=xx-center[0],yy-center[1]
 weight=np.clip(1-((dx*side[0]+dy*side[1])/(item['rx']+1))**2-((dx*down[0]+dy*down[1])/(item['ry']+1))**2,0,1)**2
 return (xx-vec[0]*weight).astype(np.float32),(yy-vec[1]*weight).astype(np.float32)
def prepare_forms(rgb,session,settings,layers,progress=None,cancel=None):
 from person_masks import ensure_body_owners
 from ai_engine import inpaint_selected
 if not any(v.get(k,0) for v in settings for k,_,_,_ in FORM):return {}
 ensure_body_owners(session,need_pose=any(v.get(k,0) for v in settings for k in ('armpit_left','armpit_right')))
 cache={};notes=[];unavailable=[]
 for fi,v in enumerate(settings):
  for key in FORM_GEOMETRY:
   if not v.get(key,0):continue
   item=spec(session,fi,key,layers)
   if item is None:notes.append(f'人像 {fi+1} {key}：未找到清晰可见且归属确定的皮肤范围，未应用');unavailable.append((fi,key,None));continue
   alpha=item['alpha'];holes=np.zeros(alpha.shape,bool)
   for strength in range(5,101,5):
    mx,my=maps(item,strength);warped=cv2.remap(alpha,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)*item['allowed']
    holes|=(alpha-warped)>.001
   if not holes.any():notes.append(f'人像 {fi+1} {key}：没有可移动的轮廓，未应用');unavailable.append((fi,key,item['signature']));continue
   a,b,c,d=item['box'];source=rgb[b:d,a:c]
   mask=cv2.dilate(holes.astype(np.uint8),np.ones((3,3),np.uint8))>0
   if progress:progress(f'人像 {fi+1} · LaMa 补全 {key} 空出区域…')
   generated,info=inpaint_selected(source,mask,progress,cancel,precision=True)
   item.update(background=generated,repair_mask=mask,model=info['model']);cache.setdefault(fi,{})[key]=item
 session.form_notes=notes;session.form_unavailable=unavailable;return cache
def apply_forms(rgb,session,settings,layers,cache):
 out=rgb;changed=np.zeros(rgb.shape[:2],bool)
 for fi,v in enumerate(settings):
  for key in FORM_GEOMETRY:
   strength=v.get(key,0);item=cache.get(fi,{}).get(key)
   if not strength or item is None:continue
   current=spec(session,fi,key,layers)
   if current is None or current['signature']!=item['signature']:continue
   a,b,c,d=item['box'];source=out[b:d,a:c].astype(np.float32);alpha=item['alpha'];mx,my=maps(item,strength)
   warped=cv2.remap(alpha,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)*item['allowed']
   premult=cv2.remap(source*alpha[:,:,None],mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)*item['allowed'][:,:,None]
   holes=np.maximum(alpha-warped,0);background=item['background'];patched=source+(background-source)*item['repair_mask'][:,:,None]
   destination=source*(1-warped[:,:,None])+premult+(patched-source)*holes[:,:,None]
   displacement=(np.abs(mx-np.arange(c-a)[None,:])>.001)|(np.abs(my-np.arange(d-b)[:,None])>.001)
   region=((alpha>0)|(warped>0))&displacement&item['allowed']
   if out is rgb:out=rgb.copy()
   out[b:d,a:c][region]=np.clip(destination[region],0,255);changed[b:d,a:c]|=region
 return out,changed
def forms_pending(session,settings,layers,cache):
 for fi,v in enumerate(settings):
  for key in FORM_GEOMETRY:
   if not v.get(key,0):continue
   item=cache.get(fi,{}).get(key);current=spec(session,fi,key,layers)
   signature=None if current is None else current['signature']
   if item is None and (fi,key,signature) in getattr(session,'form_unavailable',[]):continue
   if item is None or current is None or current['signature']!=item['signature']:return True
 return bool(any(v.get('double_chin_shadow',0) for v in settings) and getattr(session,'body_owner',None) is None)
def chin_shadow(rgb,session,settings,layers):
 if not any(v.get('double_chin_shadow',0) for v in settings):return rgb
 if getattr(session,'body_owner',None) is None:return rgb
 out=rgb.copy()
 for fi,v in enumerate(settings):
  strength=v.get('double_chin_shadow',0)
  if not strength:continue
  f=session.faces[fi];p=f.points.astype(np.float32);down=p[152]-p[10];down/=max(1,np.linalg.norm(down));side=np.array([down[1],-down[0]])
  centre=p[152]+down*f.width*.07;h,w=rgb.shape[:2];r=f.width*.5
  a,b,c,d=max(0,int(centre[0]-r)),max(0,int(centre[1]-r)),min(w,int(centre[0]+r+1)),min(h,int(centre[1]+r+1))
  scope=body_scope(session,fi,layers)[b:d,a:c];yy,xx=np.mgrid[b:d,a:c];dx,dy=xx-centre[0],yy-centre[1]
  band=np.clip(1-((dx*side[0]+dy*side[1])/(f.width*.36+1))**2-((dx*down[0]+dy*down[1])/(f.width*.22+1))**2,0,1)
  source=rgb[b:d,a:c].astype(np.float32);lab=cv2.cvtColor(np.clip(source/255,0,1),cv2.COLOR_RGB2LAB);light=lab[:,:,0].copy();context=cv2.GaussianBlur(light,(0,0),max(2,f.width*.07))
  lift=np.clip(context-light,0,10)*band*soft_edge(scope,2)*strength/100*.7;use=lift>1e-7
  if use.any():lab[:,:,0]=np.clip(light+lift,0,100);out[b:d,a:c][use]=np.clip((cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255)[use],0,255)
 return out
