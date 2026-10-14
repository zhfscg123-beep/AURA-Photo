"""Display-only cached anatomy paths and inverse-map projection; no inference."""
import cv2,numpy as np
from core import OVAL,FEATURES
import liquify,face_reshape

def resample(points,step=4):
    p=np.asarray(points,np.float32)
    if len(p)<2:return p
    distances=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
    if distances[-1]<1e-4:return p[:1]
    at=np.linspace(0,distances[-1],max(2,min(1400,int(np.ceil(distances[-1]/step))+1)))
    return np.column_stack([np.interp(at,distances,p[:,i]) for i in (0,1)]).astype(np.float32)

def contours(mask,origin=(0,0),scale=(1,1),min_length=8):
    found,_=cv2.findContours(np.ascontiguousarray(mask,dtype=np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    output=[]
    for contour in found:
        if len(contour)<3 or cv2.arcLength(contour,True)<min_length:continue
        p=contour[:,0].astype(np.float32)*scale+origin
        p=np.vstack((p,p[:1]));output.append(resample(p,max(2,max(scale))))
    return output

def finite_runs(points,valid):
    """Never join a hidden landmark or failed inverse through another feature."""
    result=[];start=None
    for i,value in enumerate(np.r_[valid,False]):
        if value and start is None:start=i
        elif not value and start is not None:
            if i-start>=2:result.append(points[start:i])
            start=None
    return result

def build(session,person):
    face_paths=[];body_paths=[];nodes=[];groups={}
    if not 0<=person<len(session.faces):return dict(face=[],body=[],nodes=[],body_confirmed=False)
    face=session.faces[person];p=np.asarray(getattr(face,'points',None))
    width=float(getattr(face,'width',max(1,face.box[2]-face.box[0])))
    labels=getattr(session,'part_labels',[])
    local=labels[person] if person<len(labels) else None
    def add(indices,closed=True,group='contour'):
        if p.ndim!=2 or p.shape[1]!=2 or len(p)<=max(indices):return
        line=p[indices].astype(np.float32)
        if closed:line=np.vstack((line,line[:1]))
        line=resample(line,max(2,width*.018));valid=np.isfinite(line).all(1)
        if isinstance(local,np.ndarray) and local.ndim==2 and local.size:
            a,b,_,_=face.box;q=line-[a,b]
            sampled=cv2.remap(local.astype(np.uint8),q[:,0].astype(np.float32)[:,None],q[:,1].astype(np.float32)[:,None],cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)[:,0]
            valid &= sampled!=17 # parser-confirmed hair occlusion
        runs=finite_runs(line,valid);face_paths.extend(runs);groups.setdefault(group,[]).extend(runs)
    add(OVAL)
    if p.ndim==2 and len(p)>max(OVAL):
        groups['contour']=[resample(np.vstack((p[OVAL],p[OVAL[:1]])),max(2,width*.018))]
    # The safety-mask feature sets in core.py are convex-hull inputs. Their
    # ordering is not a drawable contour: use connected MediaPipe paths here.
    paths=[[263,249,390,373,374,380,381,382,362,398,384,385,386,387,388,466],
           [33,7,163,144,145,153,154,155,133,173,157,158,159,160,161,246],
           [276,283,282,295,285,336,296,334,293,300],
           [46,53,52,65,55,107,66,105,63,70],FEATURES[4]]
    for ids,name in zip(paths,('eye-left','eye-right','brow-left','brow-right','mouth')):add(ids,group=name)
    if p.ndim==2 and len(p)>=478:
        add([469,470,471,472],group='eye-right');add([474,475,476,477],group='eye-left')
    if isinstance(local,np.ndarray) and local.ndim==2 and local.size:
        nose_paths=contours(local==10,face.box[:2],min_length=max(4,width*.04))
        face_paths.extend(nose_paths)
        groups['nose']=nose_paths
    else:add(FEATURES[5],group='nose')
    add([168,6,1,2],closed=False,group='nose')
    assignment=getattr(session,'body_assignment',{})
    confirmed=person in getattr(session,'person_landmarks',{}) or person+1 in assignment.get('matched_people',[])
    owner=getattr(session,'person_owner',None)
    if confirmed and isinstance(owner,np.ndarray) and owner.ndim==2:
        h,w=owner.shape;factor=min(1,1536/max(h,w));size=(max(2,round(w*factor)),max(2,round(h*factor)))
        small=cv2.resize(owner,size,interpolation=cv2.INTER_NEAREST) if factor<1 else owner
        body_paths=contours(small==person+1,scale=(w/size[0],h/size[1]),min_length=max(8,width*factor*.8))
    if p.ndim==2 and p.shape[1]==2 and len(p)>=468:
        for index,name,radius in ((33,'眼角',.14),(133,'眼角',.14),(159,'上眼睑',.12),(145,'下眼睑',.12),
            (263,'眼角',.14),(362,'眼角',.14),(386,'上眼睑',.12),(374,'下眼睑',.12),
            (46,'眉尾',.16),(55,'眉头',.16),(105,'眉弓',.16),(276,'眉尾',.16),(285,'眉头',.16),(334,'眉弓',.16),(168,'鼻根',.10),(6,'鼻梁',.10),(1,'鼻尖',.10),(98,'鼻翼',.10),(327,'鼻翼',.10),(2,'鼻基底',.10),(61,'唇角',.14),(291,'唇角',.14),
            (0,'上唇',.12),(17,'下唇',.12),(152,'下巴',.26),(172,'下颌',.26),(397,'下颌',.26),
            (234,'面颊外缘',.25),(454,'面颊外缘',.25),(10,'额头轮廓',.23)):
            q=p[index].astype(np.float32)
            if not np.isfinite(q).all():continue
            if isinstance(local,np.ndarray) and local.ndim==2 and local.size:
                a,b,_,_=face.box;x,y=map(int,np.rint(q-[a,b]))
                if 0<=y<local.shape[0] and 0<=x<local.shape[1] and local[y,x]==17 and index not in (10,234,454,172,397,152):continue
            group='nose' if index in (168,6,1,98,327,2) else 'eye-right' if index in (33,133,159,145) else 'eye-left' if index in (263,362,386,374) else 'brow-right' if index in (46,55,105) else 'brow-left' if index in (276,285,334) else 'mouth' if index in (61,291,0,17) else 'contour'
            nodes.append(dict(key='face-'+str(index),kind='face',group=group,name=name,point=q,radius=max(5,width*radius)))
        center=(p[10]+p[152])*.5
    else:center=np.array([(face.box[0]+face.box[2])/2,(face.box[1]+face.box[3])/2])
    for ci,line in enumerate(body_paths):
        groups['body-'+str(ci)]=[line]
        candidates=resample(line,max(width*.65,float(np.linalg.norm(np.diff(line,axis=0),axis=1).sum())/20))
        for ni,q in enumerate(candidates[:-1]):
            if isinstance(owner,np.ndarray):
                h,w=owner.shape
                if min(q[0],q[1],w-1-q[0],h-1-q[1])<max(3,2*max(h,w)/1536):continue
            # Keep face handles separate; raised arms outside the head still get nodes.
            if np.linalg.norm((q-center)/[max(1,width*.7),max(1,width*.8)])<1:continue
            nodes.append(dict(key=f'body-{ci}-{ni}',kind='body',group='body-'+str(ci),name='身体外缘',point=q,radius=1000.))
    return dict(face=face_paths,body=body_paths,nodes=nodes,groups=groups,body_confirmed=confirmed and bool(body_paths))

def sample_grid(grid,points,roi):
    a,b,c,d=roi;gh,gw=grid.shape[:2];q=np.asarray(points,np.float32)
    x=((q[:,0]-a)*(gw-1)/max(1,c-a-1)).astype(np.float32)
    y=((q[:,1]-b)*(gh-1)/max(1,d-b-1)).astype(np.float32)
    values=cv2.remap(grid,x[:,None],y[:,None],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)[:,0]
    inside=(q[:,0]>=a)&(q[:,0]<=c-1)&(q[:,1]>=b)&(q[:,1]<=d-1)
    return values*inside[:,None]

def invert_points(points,mapping,step=2):
    """Damped Newton solve p + inverse_flow(p) = original_point.

    Invalid/convergence-failed points are omitted rather than shown in a wrong
    place. Only sparse guide points are sampled, never full RAW mapping arrays.
    """
    original=np.asarray(points,np.float32);guess=original.copy()
    if not len(guess):return guess,np.zeros(0,bool)
    for _ in range(12):
        mapped=mapping(guess);error=mapped-original;norm=np.linalg.norm(error,axis=1)
        if np.max(norm,initial=0)<.08:break
        dx=(mapping(guess+[step,0])-mapping(guess-[step,0]))/(2*step)
        dy=(mapping(guess+[0,step])-mapping(guess-[0,step]))/(2*step)
        det=dx[:,0]*dy[:,1]-dy[:,0]*dx[:,1];safe=np.abs(det)>.03
        delta=error.copy()
        delta[safe,0]=(error[safe,0]*dy[safe,1]-error[safe,1]*dy[safe,0])/det[safe]
        delta[safe,1]=(dx[safe,0]*error[safe,1]-dx[safe,1]*error[safe,0])/det[safe]
        length=np.linalg.norm(delta,axis=1);delta*=np.minimum(1,128/np.maximum(length,1e-6))[:,None]
        best=guess.copy();best_norm=norm.copy()
        for amount in (1.,.5,.25,.125):
            candidate=(guess-delta*amount).astype(np.float32)
            candidate_norm=np.linalg.norm(mapping(candidate)-original,axis=1)
            use=np.isfinite(candidate_norm)&(candidate_norm<best_norm)
            best[use]=candidate[use];best_norm[use]=candidate_norm[use]
        if np.array_equal(best,guess):break
        guess=best
    residual=np.linalg.norm(mapping(guess)-original,axis=1)
    return guess,np.isfinite(guess).all(1)&(residual<.6)

def project(points,shape,reshape_cache,settings,state=None):
    q=np.asarray(points,np.float32);valid=np.isfinite(q).all(1)
    fields=face_reshape._fields(reshape_cache,settings)
    if fields:
        def face_mapping(p):
            p=np.asarray(p,np.float32);delta=np.zeros_like(p)
            for field in fields:delta+=sample_grid(field['grid'],p,field['roi'])
            return p+delta
        q,ok=invert_points(q,face_mapping);valid &= ok
    if liquify.active(state):
        h,w=state['shape']
        def liquid_mapping(p):
            p=np.asarray(p,np.float32)
            return p+sample_grid(state['flow'],p,(0,0,w,h))
        q,ok=invert_points(q,liquid_mapping);valid &= ok
    h,w=shape;valid &= (q[:,0]>=0)&(q[:,0]<w)&(q[:,1]>=0)&(q[:,1]<h)
    return q,valid

def clipped_lines(points,rectangle):
    """Merge adjacent clipped segments; original/result halves keep their maps."""
    x0,y0,x1,y1=rectangle
    if x1<=x0 or y1<=y0:return []
    rect=(int(x0),int(y0),int(x1-x0),int(y1-y0));paths=[];current=[]
    for a,b in zip(points[:-1],points[1:]):
        yes,p,q=cv2.clipLine(rect,tuple(np.rint(a).astype(int)),tuple(np.rint(b).astype(int)))
        if not yes:
            if len(current)>1:paths.append(current)
            current=[];continue
        if not current:current=[p,q]
        elif current[-1]==p:current.append(q)
        else:paths.append(current);current=[p,q]
    if len(current)>1:paths.append(current)
    return paths
