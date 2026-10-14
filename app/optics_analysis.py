"""Small-image / guide analysis only; full-resolution warp stays in render GPU."""
import numpy as np
import cv2

def line(guide):
    a=np.array([*guide['start'],1.]);b=np.array([*guide['end'],1.]);return np.cross(a,b)

def rectify(guides,mode='full'):
    vertical=[g for g in guides if g['axis']=='vertical'];horizontal=[g for g in guides if g['axis']=='horizontal']
    if mode in ('vertical','full') and len(vertical)<2:raise ValueError('需要两条可靠的垂直参考线。')
    if mode=='full' and len(horizontal)<2:raise ValueError('完整透视需要两条垂直线和两条水平线。')
    v=np.cross(line(vertical[0]),line(vertical[1])) if len(vertical)>=2 else np.array([0.,1.,0.])
    h=np.cross(line(horizontal[0]),line(horizontal[1])) if mode=='full' else np.array([1.,0.,0.])
    horizon=np.cross(v,h)
    if abs(horizon[2])<1e-8:raise ValueError('参考线退化，请重新选择。')
    horizon/=horizon[2];projective=np.eye(3);projective[2]=horizon
    def direction(g):
        points=np.array([[*g['start'],1.],[*g['end'],1.]])@projective.T
        if np.min(np.abs(points[:,2]))<1e-5:raise ValueError('参考线过近消失点，无法可靠校正。')
        pts=points[:,:2]/points[:,2:3];d=pts[1]-pts[0];return d/max(1e-8,np.linalg.norm(d))
    dv=direction(vertical[0]) if vertical else np.array([0.,1.]);dh=direction(horizontal[0]) if horizontal else np.array([1.,0.])
    if dv[1]<0:dv=-dv
    if dh[0]<0:dh=-dh
    basis=np.column_stack([dh,dv])
    if abs(np.linalg.det(basis))<.15:raise ValueError('水平与垂直参考线夹角过小。')
    affine=np.eye(3);affine[:2,:2]=np.linalg.inv(basis);matrix=affine@projective
    center=matrix@np.array([.5,.5,1]);center/=center[2];matrix[:2]+=np.outer([.5-center[0],.5-center[1]],matrix[2])
    corners=np.array([[0,0,1],[1,0,1],[1,1,1],[0,1,1]])@matrix.T
    if np.min(corners[:,2])<=.1 or np.linalg.cond(matrix)>100:raise ValueError('透视校正过强，请使用较温和的参考线。')
    return matrix.tolist()

def analyze(rgb,mode):
    h,w=rgb.shape[:2];factor=min(1,1200/max(h,w));small=cv2.resize(rgb,(max(32,round(w*factor)),max(32,round(h*factor))))
    gray=cv2.cvtColor(np.clip(small,0,255).astype(np.uint8),cv2.COLOR_RGB2GRAY)
    segments=cv2.HoughLinesP(cv2.Canny(gray,60,160),1,np.pi/1800,80,minLineLength=max(40,min(gray.shape)//5),maxLineGap=12)
    if segments is None:raise ValueError('未检测到可靠建筑或水平线，请使用引导线。')
    groups={'vertical':[],'horizontal':[]};angles=[]
    sh,sw=gray.shape
    for x,y,a,b in np.asarray(segments).reshape(-1,4):
        dx=a-x;dy=b-y;angle=np.rad2deg(np.arctan2(dy,dx));angle=(angle+90)%180-90;length=np.hypot(dx,dy)
        axis='vertical' if abs(angle)>65 else 'horizontal' if abs(angle)<25 else None
        if axis:
            guide=dict(axis=axis,start=[float(x/(sw-1)),float(y/(sh-1))],end=[float(a/(sw-1)),float(b/(sh-1))]);groups[axis].append((length,guide))
        if abs(angle)<10:angles.append(angle)
    if mode=='level':
        if len(angles)<2:raise ValueError('未检测到可靠水平线。')
        return dict(rotation=-float(np.median(angles)),guides=[])
    guides=[]
    for axis in ('vertical','horizontal'):
        candidates=sorted(groups[axis],key=lambda r:-r[0]);picked=[]
        for _,g in candidates:
            center=np.mean([g['start'],g['end']],axis=0)
            if all(abs(center[0 if axis=='vertical' else 1]-np.mean([p['start'],p['end']],axis=0)[0 if axis=='vertical' else 1])>.12 for p in picked):picked.append(g)
            if len(picked)==2:break
        guides+=picked
    return dict(homography=rectify(guides,mode),guides=guides)
