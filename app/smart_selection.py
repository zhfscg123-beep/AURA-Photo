"""Interactive color/edge expansion, assisted by existing per-person AI labels."""
import cv2,numpy as np

def select(rgb,point,radius,mode='skin',allowed=None,veto=None):
    h,w=rgb.shape[:2];x,y=map(int,np.rint(point));r=max(20,min(4000,int(radius)))
    if not 0<=x<w or not 0<=y<h:raise ValueError('请点击照片内的目标区域。')
    if veto is not None and veto[y,x]:raise ValueError('该点在已确认的五官、头发或其他人物保护区内。')
    a,b=max(0,x-r),max(0,y-r);c,d=min(w,x+r+1),min(h,y+r+1)
    crop=rgb[b:d,a:c];scale=min(1,640/max(c-a,d-b));size=(max(2,round((c-a)*scale)),max(2,round((d-b)*scale)))
    small=cv2.resize(crop,size,interpolation=cv2.INTER_AREA) if scale<1 else crop.copy()
    lab=cv2.cvtColor(np.clip(small.astype(np.float32)/255,0,1),cv2.COLOR_RGB2LAB)
    px=min(size[0]-1,round((x-a)*scale));py=min(size[1]-1,round((y-b)*scale))
    center=np.median(lab[max(0,py-2):py+3,max(0,px-2):px+3].reshape(-1,3),axis=0)
    chroma=np.linalg.norm(lab[:,:,1:]-center[1:],axis=2);light=np.abs(lab[:,:,0]-center[0])
    candidate=(chroma<(19 if mode=='skin' else 25))&(light<(48 if mode=='skin' else 55))
    permitted=np.ones(small.shape[:2],bool)
    if allowed is not None:permitted &= cv2.resize(allowed[b:d,a:c].astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
    if veto is not None:permitted &= cv2.resize((~veto[b:d,a:c]).astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
    if not permitted[py,px]:raise ValueError('该处未可靠归属当前人物，可换用物体选区或手动添加画笔。')
    marks=np.full(small.shape[:2],cv2.GC_PR_BGD,np.uint8);marks[~permitted]=cv2.GC_BGD
    marks[candidate&permitted]=cv2.GC_PR_FGD
    seed=np.zeros(small.shape[:2],np.uint8);cv2.circle(seed,(px,py),max(2,round(5*scale)),1,-1)
    marks[(seed>0)&permitted]=cv2.GC_FGD
    border=np.zeros_like(seed);border[[0,-1]]=1;border[:,[0,-1]]=1
    marks[(border>0)&(seed==0)&~candidate]=cv2.GC_BGD
    if np.count_nonzero(marks!=cv2.GC_FGD)<8:marks[[0,-1]]=cv2.GC_BGD;marks[:,[0,-1]]=cv2.GC_BGD
    try:cv2.grabCut(small,marks,None,np.zeros((1,65)),np.zeros((1,65)),3,cv2.GC_INIT_WITH_MASK)
    except cv2.error:pass
    result=np.isin(marks,[cv2.GC_FGD,cv2.GC_PR_FGD])&permitted
    if mode=='skin':result &= (chroma<26)&(light<58)
    count,labels=cv2.connectedComponents(result.astype(np.uint8),8)
    index=labels[py,px]
    if not index:raise ValueError('这次点选未得到稳定区域，请缩小范围或手动补选。')
    result=labels==index;large=cv2.resize(result.astype(np.uint8),(c-a,d-b),interpolation=cv2.INTER_NEAREST)>0
    output=np.zeros((h,w),bool);output[b:d,a:c]=large
    if veto is not None:output &= ~veto
    if allowed is not None:output &= allowed
    return output

def skin_constraints(session,person):
    h,w=session.original.shape[:2];face=session.faces[person];owner=getattr(session,'person_owner',None)
    allowed=np.zeros((h,w),np.uint8);veto=np.zeros((h,w),bool)
    if isinstance(owner,np.ndarray):
        known=(owner==person+1).astype(np.uint8);radius=max(3,min(150,round(face.width*.16)))
        allowed=cv2.dilate(known,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,)*2));veto|=(owner>0)&(owner!=person+1)
    a,b,c,d=face.box;allowed[b:d,a:c]=1
    for i,f in enumerate(session.faces):
        x,y,z,t=f.box
        if i!=person:veto[y:t,x:z]|=f.mask>0
    labels=getattr(session,'part_labels',[])
    if person<len(labels):
        lab=labels[person]
        veto[b:d,a:c]|=np.isin(lab,[2,3,4,5,6,9,11,12,13,17,18])
    return allowed.astype(bool)&~veto,veto

def refine(mask,expand):
    size=int(round(float(expand)))
    if not size:return mask
    k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(abs(size)*2+1,)*2)
    return (cv2.dilate if size>0 else cv2.erode)(mask.astype(np.uint8),k)>0
