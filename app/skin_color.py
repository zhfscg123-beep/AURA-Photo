"""Bounded LAB tone matching on AI-owned skin, preserving luminance detail."""
import cv2,numpy as np
from region_masks import skin_blend,face_beauty_mask
from body_details import body_scope,body_blend
COLORS=[('冷白','#eee9e7'),('粉白','#ead9d7'),('清冷','#dce7e9'),('奶油','#eadfca'),
 ('自然暖','#d2b397'),('蜜桃','#c69f91'),('小麦','#b98f75'),('深暖','#946a55')]
FACE_KEYS=('color_face','sample_face','match_face_bright','face_hf')
BODY_KEYS=('color_body','sample_body','match_body_bright')
def tone(rgb):return cv2.cvtColor(np.asarray(rgb,np.float32).reshape(1,1,3)/255,cv2.COLOR_RGB2LAB)[0,0]
def adjust(src,alpha,v,face,bright):
 safe=alpha>.8
 if safe.sum()<8:return src
 lab=cv2.cvtColor(np.clip(src.astype(np.float32)/255,0,1),cv2.COLOR_RGB2LAB);current=np.median(lab[safe],axis=0)
 requests=[];strength=v.get('color_face' if face else 'color_body',0);choice=int(round(v.get('skin_choice',0)))
 if strength and 1<=choice<=len(COLORS):
  h=COLORS[choice-1][1];target=tone([int(h[i:i+2],16) for i in (1,3,5)])
  target[0]=current[0]+np.clip(target[0]-current[0],-6,6);requests.append((strength,target))
 strength=v.get('sample_face' if face else 'sample_body',0)
 if strength and sum(v.get('sample_'+c,0) for c in 'rgb')>0:requests.append((strength,tone([v['sample_'+c] for c in 'rgb'])))
 strength=v.get('match_face_bright' if face else 'match_body_bright',0)
 if strength and bright is not None and (not face or current[0]<bright[0]-.1):requests.append((strength,bright))
 shift=np.zeros(3,np.float32)
 for strength,target in requests:shift+=np.clip(target-current,[-12,-8,-8],[12,8,8])*strength/100*.7
 lab+=np.clip(shift,[-12,-10,-10],[12,10,10])
 if face and v.get('face_hf',0):
  light=lab[:,:,0].copy();fine=cv2.GaussianBlur(light,(0,0),max(.7,min(light.shape)*.003))
  lab[:,:,0]+=(light-fine)*v['face_hf']/100*.5
 if not requests and not (face and v.get('face_hf',0)):return src
 lab[:,:,0]=np.clip(lab[:,:,0],0,100);desired=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)*255
 out=src.copy();use=alpha>0;out[use]=np.clip((src+(desired-src)*alpha[:,:,None])[use],0,255);return out
def apply_skin_color(rgb,session,settings,layers,mode='all'):
 keys=FACE_KEYS if mode=='face' else BODY_KEYS if mode=='body' else FACE_KEYS+BODY_KEYS
 if not any(v.get(k,0) for v in settings for k in keys):return rgb
 tones=[]
 for fi,f in enumerate(session.faces):
  a,b,c,d=f.box;safe=f.mask>.8
  if safe.sum()>=8:tones.append((fi,np.median(cv2.cvtColor(np.clip(rgb[b:d,a:c].astype(np.float32)/255,0,1),cv2.COLOR_RGB2LAB)[safe],axis=0)))
 reference,bright=max(tones,key=lambda item:item[1][0]) if tones else (None,None)
 out=rgb.copy()
 for fi,(f,v) in enumerate(zip(session.faces,settings)):
  if mode!='body' and any(v.get(k,0) for k in FACE_KEYS):
   face_beauty_mask(session,fi)
   a,b,c,d=f.box;out[b:d,a:c]=adjust(out[b:d,a:c],skin_blend(f),v,True,bright if fi!=reference and len(tones)>1 else None)
  if mode!='face' and any(v.get(k,0) for k in BODY_KEYS) and getattr(session,'body_owner',None) is not None:
   mask=body_scope(session,fi,layers);pts=cv2.findNonZero(mask.astype(np.uint8))
   if pts is not None:
    a,b,w,h=cv2.boundingRect(pts);out[b:b+h,a:a+w]=adjust(out[b:b+h,a:a+w],body_blend(mask[b:b+h,a:a+w],f.width),v,False,bright)
 return out
