"""Photometric fullness and dodge/burn on AI landmarks; no synthetic 3D model."""
import numpy as np,cv2
from region_masks import skin_blend,face_beauty_mask
from feature_catalog import VOLUME
def zones(f):
 a,b,c,d=f.box;p=f.points.astype(np.float32)-[a,b];fw=f.width
 yy,xx=np.mgrid[:d-b,:c-a].astype(np.float32);down=p[152]-p[10];down/=max(1,np.linalg.norm(down));side=np.array([down[1],-down[0]])
 def ellipse(center,rx,ry):
  dx,dy=xx-center[0],yy-center[1]
  return np.clip(1-((dx*side[0]+dy*side[1])/(fw*rx+1))**2-((dx*down[0]+dy*down[1])/(fw*ry+1))**2,0,1)**2
 return {
 'forehead':ellipse((p[10]+p[151])/2-down*fw*.035,.35,.23),
 'midface':ellipse((p[50]+p[280]+p[2])/3,.30,.19),
 'cheek':np.maximum(ellipse(p[50]+down*fw*.06,.20,.22),ellipse(p[280]+down*fw*.06,.20,.22)),
 'nosebase':ellipse(p[2]+down*fw*.05,.15,.12),
 'eye_left':ellipse((p[263]+p[362])/2+down*fw*.055,.17,.10),
 'eye_right':ellipse((p[33]+p[133])/2+down*fw*.055,.17,.10),
 'eye_inner':np.maximum(ellipse(p[133]+down*fw*.02,.055,.075),ellipse(p[362]+down*fw*.02,.055,.075)),
 'brow':np.maximum(ellipse(p[55]-down*fw*.025,.19,.10),ellipse(p[285]-down*fw*.025,.19,.10)),
 'chin':ellipse((p[17]+p[152])/2,.25,.16),
 'corner':np.maximum(ellipse(p[61]+down*fw*.04,.10,.13),ellipse(p[291]+down*fw*.04,.10,.13))}
def apply_face_volume(rgb,session,settings):
 if not any(v.get(k,0) for v in settings for k,_,_,_ in VOLUME):return rgb
 out=rgb.copy()
 for fi,(f,v) in enumerate(zip(session.faces,settings)):
  if not any(v.get(k,0) for k,_,_,_ in VOLUME):continue
  face_beauty_mask(session,fi)
  safe=f.mask>.8
  if safe.sum()<20:continue
  a,b,c,d=f.box;src=rgb[b:d,a:c].astype(np.float32);lab=cv2.cvtColor(np.clip(src/255,0,1),cv2.COLOR_RGB2LAB);light=lab[:,:,0].copy()
  broad=cv2.GaussianBlur(light,(0,0),max(2,f.width*.025));context=cv2.GaussianBlur(broad,(0,0),max(4,f.width*.09))
  delta=np.zeros(light.shape,np.float32);regions=zones(f);level=v.get('volume_all',0)/4
  for key,zone in regions.items():
   strength=max(level,v.get('vol_'+key,0)/100)
   if strength:delta+=zone*strength*(np.clip(context-broad,0,8)*.8+3.2)
   flat=v.get('vol_'+key+'_flat',0)/100;lift=v.get('vol_'+key+'_light',0)/100
   if flat:delta+=zone*np.clip(context-broad,-8,8)*flat*.8
   if lift:delta+=zone*lift*5
  feature=np.maximum.reduce([regions[k] for k in ('brow','nosebase','eye_left','eye_right','corner')])
  distance=cv2.distanceTransform((f.mask>0).astype(np.uint8),cv2.DIST_L2,5)
  contour=np.exp(-((distance/(f.width+.001)-.09)/.07)**2)
  highlight=(regions['forehead']+regions['midface']+regions['chin'])*.9
  shadow=(regions['cheek']+regions['eye_left']+regions['eye_right'])*.8
  structure=np.clip(highlight-shadow,-1,1)*4+np.clip(broad-context,-5,5)*feature*.8
  delta+=structure*v.get('stereo_features',0)/100
  delta+=(regions['midface']*1.5-contour*4.5)*v.get('stereo_contour',0)/100
  if not np.any(delta):continue
  lab[:,:,0]=np.clip(light+np.clip(delta,-6,8),0,100);desired=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
  selected=(f.beauty_mask>0)&(np.abs(delta)>1e-7);out[b:d,a:c][selected]=np.clip((src+(desired-src)*skin_blend(f)[:,:,None])[selected],0,255)
 return out
