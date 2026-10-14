"""Offline face-guided, conservative skin retouch. No network calls."""
from pathlib import Path
from dataclasses import dataclass
import io
import hashlib
import numpy as np
import cv2
from PIL import Image, ImageOps, ImageCms

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / 'models/face_landmarker.task'
OVAL = [10,338,297,332,284,251,389,356,454,323,361,288,397,365,379,378,400,377,152,148,176,149,150,136,172,58,132,93,234,127,162,21,54,103,67,109]
FEATURES = [[263,249,390,373,374,380,381,382,362,466,388,387,386,385,384,398], [33,7,163,144,145,153,154,155,133,246,161,160,159,158,157,173], [276,283,282,295,285,300,293,334,296,336], [46,53,52,65,55,70,63,105,66,107], [61,146,91,181,84,17,314,405,321,375,291,409,270,269,267,0,37,39,40,185], [98,97,2,326,327,294,278,48,64]]

def load_photo(path,apply_profile=True):
    with Image.open(path) as src:
        if src.mode not in ('RGB', 'RGBA', 'L', 'P'):
            raise ValueError('第一版只支持 8 位照片；请从 Lightroom 导出 sRGB JPEG / PNG / 8位 RGB TIFF。')
        if src.format not in ('JPEG', 'MPO', 'PNG', 'TIFF'):
            raise ValueError('请打开 JPEG、PNG 或 8位 RGB TIFF；RAW 需先从 Lightroom 导出。')
        # Phone JPEGs can contain auxiliary MP images. Pillow opens the primary
        # full-resolution photo as frame zero; auxiliary images are not pages
        # to retouch and must never replace the primary photo.
        if src.format == 'MPO':
            src.seek(0)
        elif getattr(src, 'n_frames', 1) != 1:
            raise ValueError('暂不支持多页照片。')
        if (src.mode == 'RGBA' or 'transparency' in src.info) and src.convert('RGBA').getchannel('A').getextrema()[0] != 255:
            raise ValueError('请先将透明 PNG 合成到背景；此版本处理不透明照片。')
        if src.format == 'PNG':
            with Path(path).open('rb') as stream: header=stream.read(29)
            if len(header)<29 or header[24]>8:
                raise ValueError('暂不支持16位 PNG；请导出8位 sRGB 副本。')
        # Pillow converts 16-bit RGB TIFF to RGB silently: inspect TIFF metadata first.
        bits = src.tag_v2.get(258, (8,)) if src.format == 'TIFF' else (8,)
        if isinstance(bits, int): bits = (bits,)
        if any(b != 8 for b in bits):
            raise ValueError('暂不支持16位 TIFF；请导出8位 sRGB 副本。')
        if src.width * src.height > 60_000_000:
            raise ValueError('请先导出不超过6000万像素的照片。')
        icc = src.info.get('icc_profile')
        im = ImageOps.exif_transpose(src).convert('RGB')
        if icc and apply_profile:
            im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(icc)), ImageCms.createProfile('sRGB'), outputMode='RGB')
        return np.array(im, dtype=np.uint8)

def save_photo(path, rgb):
    path = Path(path)
    if path.exists(): raise ValueError('导出路径已存在，请选择新文件名。')
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.tif', '.tiff'):
        raise ValueError('请选择 PNG、JPEG 或 TIFF 扩展名。')
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    args = {'icc_profile': icc}
    if path.suffix.lower() in ('.jpg', '.jpeg'): args.update(quality=96, subsampling=0)
    if path.suffix.lower() in ('.tif', '.tiff'): args['compression'] = 'tiff_lzw'
    # Exclusive creation prevents an export racing with another program from overwriting.
    with path.open('xb') as out:
        try: Image.fromarray(rgb).save(out, format={'.png':'PNG','.jpg':'JPEG','.jpeg':'JPEG','.tif':'TIFF','.tiff':'TIFF'}[path.suffix.lower()], **args)
        except Exception:
            out.close(); path.unlink(missing_ok=True); raise

@dataclass
class Face:
    box: tuple
    mask: np.ndarray
    protected: np.ndarray
    width: float
    points: object = None

def face_mask(points, shape, extend_forehead=True, expand_sides=True):
    h,w = shape[:2]
    p = np.rint(points * [w,h]).astype(np.int32)
    absolute_points=p.copy()
    fw = float(np.linalg.norm(p[234] - p[454]))
    outline=p[OVAL].astype(np.float32)
    if extend_forehead:
        # The mesh's upper oval is not the hairline. Expand only its upper arc
        # along the face axis; semantic parsing later removes hair/background.
        up=p[10].astype(np.float32)-p[152]
        up/=max(1,float(np.linalg.norm(up)))
        projection=(outline-p[10])@up
        weight=np.clip(1+projection/max(1,fw*.42),0,1)**1.5
        outline+=up[None]*weight[:,None]*fw*.32
    outline=np.rint(outline).astype(np.int32)
    x,y,bw,bh = cv2.boundingRect(outline)
    pad = max(8, int(fw * (.14 if expand_sides else .06)))
    x0,y0,x1,y1 = max(0,x-pad),max(0,y-pad),min(w,x+bw+pad),min(h,y+bh+pad)
    p -= [x0,y0]
    mask = np.zeros((y1-y0,x1-x0), np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(outline-[x0,y0]), 255)
    if expand_sides:
        r=max(2,round(fw*.11))
        mask=cv2.dilate(mask,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(r*2+1,r*2+1)))
    protected = np.zeros_like(mask)
    # Nose skin belongs to beauty masks. Nostrils are protected separately using
    # actual image darkness within the landmark-guided lower-nose region.
    for ids in FEATURES[:-1]: cv2.fillConvexPoly(protected, cv2.convexHull(p[ids]), 255)
    # Feature margins and an inward boundary falloff avoid skin-edge halos.
    radius = max(2, round(fw*.018))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1))
    protected = cv2.dilate(protected,k)
    mask[protected > 0] = 0
    mask = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)))
    dist = cv2.distanceTransform(mask,cv2.DIST_L2,5)
    soft = np.clip(dist / max(2,fw*.008),0,1).astype(np.float32)
    return Face((x0,y0,x1,y1),soft,protected,fw,absolute_points)

def detect_faces(rgb):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, RunningMode
    if not MODEL.exists(): raise FileNotFoundError('缺少本地关键点模型，请运行安装脚本。')
    # Use a buffer because some Windows ML runtimes do not handle Unicode model paths.
    opt = FaceLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=MODEL.read_bytes()),running_mode=RunningMode.IMAGE,num_faces=5,min_face_detection_confidence=.45,min_face_presence_confidence=.55)
    h,w=rgb.shape[:2]; ratio=min(1,1600/max(h,w))
    small=cv2.resize(rgb,(round(w*ratio),round(h*ratio))) if ratio<1 else rgb
    with FaceLandmarker.create_from_options(opt) as lm:
        result=lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(small)))
        points=[np.array([[l.x,l.y] for l in face]) for face in result.face_landmarks]
        # The landmarker internally downsizes its input again. A face in a full-body
        # composition can disappear even when the supplied image is 1600 pixels.
        # Overlapping native-resolution tiles enlarge small faces without lowering confidence.
        tile_pass=not points or any(np.ptp(p[:,0])*w<min(h,w)*.20 for p in points)
        if tile_pass:
            detector_path=ROOT/'models/face_detection_yunet_2023mar.onnx'
            if detector_path.exists():
                if hashlib.sha256(detector_path.read_bytes()).hexdigest()!='8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4':raise ValueError('小脸定位模型校验失败。')
                detector=cv2.FaceDetectorYN.create('onnx',np.frombuffer(detector_path.read_bytes(),np.uint8),np.empty(0,np.uint8),(small.shape[1],small.shape[0]),.85,.3,100)
                _,candidates=detector.detect(cv2.cvtColor(small,cv2.COLOR_RGB2BGR))
                for candidate in [] if candidates is None else candidates:
                    x,y,bw,bh=candidate[:4]/ratio;side=max(bw,bh)*1.75;cx=x+bw/2;cy=y+bh/2
                    a,b=max(0,round(cx-side/2)),max(0,round(cy-side/2));c,d=min(w,round(cx+side/2)),min(h,round(cy+side/2))
                    if c<=a or d<=b:continue
                    patch=np.ascontiguousarray(rgb[b:d,a:c]);detected=lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=patch))
                    for face in detected.face_landmarks:
                        p=np.array([[l.x,l.y] for l in face]);points.append((p*[c-a,d-b]+[a,b])/[w,h])
        if tile_pass and not points and min(h,w)>600:
            side=max(600,round(min(h,w)*.5));step=max(1,round(side*.65))
            xs=sorted(set([*range(0,max(1,w-side+1),step),max(0,w-side)]))
            ys=sorted(set([*range(0,max(1,h-side+1),step),max(0,h-side)]))
            for y in ys:
                for x in xs:
                    patch=np.ascontiguousarray(rgb[y:min(h,y+side),x:min(w,x+side)])
                    detected=lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=patch))
                    for face in detected.face_landmarks:
                        p=np.array([[l.x,l.y] for l in face]);p=(p*[patch.shape[1],patch.shape[0]]+[x,y])/[w,h]
                        if np.ptp(p[:,0])*w>=20 and np.ptp(p[:,1])*h>=25:points.append(p)
        faces=_merge_face_candidates([face_mask(p,rgb.shape) for p in points])
        # Full-frame detection can return two different meshes for a tilted
        # face. Face width is useful for deduplication, not landmark quality.
        # Re-estimate each retained face in its native-resolution head crop so
        # every downstream feature mask shares the same locally fitted mesh.
        refined=[]
        for seed in faces:
            a,b,c,d=seed.box
            patch=np.ascontiguousarray(rgb[b:d,a:c])
            local=lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=patch))
            matches=[]
            for mesh in local.face_landmarks:
                p=np.array([[l.x,l.y] for l in mesh])*[c-a,d-b]+[a,b]
                if not np.isfinite(p).all():continue
                width=float(np.linalg.norm(p[234]-p[454]))
                distance=float(np.linalg.norm(p[[33,133,263,362]].mean(0)-seed.points[[33,133,263,362]].mean(0)))
                if .65*seed.width<=width<=1.5*seed.width and distance<seed.width*.30:
                    matches.append(p)
            # Ambiguous or failed local detection must not switch identities.
            face=face_mask(matches[0]/[w,h],rgb.shape) if len(matches)==1 else seed
            face.landmark_source='local-head-crop' if len(matches)==1 else 'full-frame-fallback'
            refined.append(face)
        faces=_merge_face_candidates(refined)
    # Protect each person's features against another overlapping face mask too.
    protected=np.zeros(rgb.shape[:2],bool)
    for f in faces:
        a,b,c,d=f.box; protected[b:d,a:c]|=f.protected>0
    for f in faces:
        a,b,c,d=f.box; f.mask[protected[b:d,a:c]]=0
    return sorted(faces,key=lambda f:(f.box[0]+f.box[2],f.box[1]+f.box[3]))


def _merge_face_candidates(found):
    # Some detector configurations emit two meshes for the same rotated face.
    # Merge only nearly coincident faces, rather than editing that person twice.
    faces=[]
    for f in sorted(found,key=lambda f:f.width,reverse=True):
        a,b,c,d=f.box; duplicate=False
        for g in faces:
            e,j,k,l=g.box
            intersection=max(0,min(c,k)-max(a,e))*max(0,min(d,l)-max(b,j))
            union=(c-a)*(d-b)+(k-e)*(l-j)-intersection
            center_distance=np.hypot((a+c-e-k)/2,(b+d-j-l)/2)
            if intersection/max(1,union)>.45 and center_distance<min(f.width,g.width)*.25:
                duplicate=True; break
        if not duplicate:faces.append(f)
    return faces

def find_spots(rgb, faces, sensitivity=35):
    """Conservative red point heuristic, not a trained acne classifier."""
    spots=[]
    for fi,f in enumerate(faces):
        x0,y0,x1,y1=f.box; patch=rgb[y0:y1,x0:x1]
        lab=cv2.cvtColor(patch,cv2.COLOR_RGB2LAB).astype(np.float32)
        sigma=max(1.2,f.width*.016)
        baseline=cv2.GaussianBlur(lab,(0,0),sigma)
        red=lab[:,:,1]-baseline[:,:,1]; dark=baseline[:,:,0]-lab[:,:,0]
        threshold=9.5 - np.clip(sensitivity,0,100)*.03
        candidate=((red>threshold)&(dark>2)&(f.mask>.95)).astype(np.uint8)
        count,labels,stats,centers=cv2.connectedComponentsWithStats(candidate,8)
        for idx in range(1,count):
            x,y,w,h,area=stats[idx]
            if area<2 or area>max(8,(f.width*.026)**2) or max(w,h)>f.width*.07: continue
            if max(w,h)/max(1,min(w,h))>2.8: continue
            cx,cy=centers[idx]; radius=max(2,int(np.ceil(max(w,h)/2))+1)
            if f.mask[int(cy),int(cx)]<.99: continue
            # Expanding the spot must remain entirely within the safe skin region.
            disk=np.zeros_like(candidate); cv2.circle(disk,(round(cx),round(cy)),radius,1,-1)
            if np.min(f.mask[disk>0])<.95: continue
            spots.append({'x':round(cx+x0),'y':round(cy+y0),'r':radius,'face':fi,'enabled':True,'manual':False})
    return spots

class Session:
    def __init__(self,rgb,auto_scan=False,cache_smoothing=True):
        self.original=np.ascontiguousarray(rgb)
        self.faces=detect_faces(rgb)
        self.spots=find_spots(rgb,self.faces) if auto_scan else []
        self._smooth=[]
        if cache_smoothing:self.prepare_smooth()
    def prepare_smooth(self):
        self._smooth=[]
        for f in self.faces:
            x0,y0,x1,y1=f.box; p=self.original[y0:y1,x0:x1]
            # Preserve fine grain; soften only intermediate-scale irregularities.
            sigma=max(.65,f.width*.0025)
            low=cv2.GaussianBlur(p.astype(np.float32),(0,0),sigma)
            base=cv2.bilateralFilter(low,0,13,max(2,f.width*.018))
            softened=base + .85*(p.astype(np.float32)-low)
            self._smooth.append(softened)
    def scan(self,sensitivity):
        self.spots=find_spots(self.original,self.faces,sensitivity)
    def add_spot(self,x,y,r):
        for fi,f in enumerate(self.faces):
            x0,y0,x1,y1=f.box
            if x0<=x<x1 and y0<=y<y1 and f.mask[y-y0,x-x0]>.95:
                disk=np.zeros(f.mask.shape,np.uint8); cv2.circle(disk,(x-x0,y-y0),r,1,-1)
                if np.min(f.mask[disk>0])<.95: return False
                self.spots.append(dict(x=x,y=y,r=r,face=fi,enabled=True,manual=True)); return True
        return False
    def render(self,smooth=25,repair=75):
        if smooth>0 and not self._smooth:self.prepare_smooth()
        out=self.original.copy()
        for fi,f in enumerate(self.faces):
            x0,y0,x1,y1=f.box; src=self.original[y0:y1,x0:x1]
            amount=np.clip(smooth,0,100)/100*.65
            edited=src.astype(np.float32)
            if smooth>0:edited+=(self._smooth[fi]-src)*f.mask[:,:,None]*amount
            spots=[s for s in self.spots if s['enabled'] and s['face']==fi]
            if spots and repair>0:
                spotmask=np.zeros(f.mask.shape,np.uint8)
                for s in spots: cv2.circle(spotmask,(s['x']-x0,s['y']-y0),s['r'],255,-1)
                spotmask[f.mask<.95]=0
                healed=cv2.inpaint(np.clip(edited,0,255).astype(np.uint8),spotmask,3,cv2.INPAINT_TELEA)
                # Inpainting only changes selected disks, with inward soft blending.
                weight=np.clip(cv2.distanceTransform(spotmask,cv2.DIST_L2,5)/1.5,0,1)*np.clip(repair,0,100)/100
                edited+=(healed-edited)*weight[:,:,None]
            out[y0:y1,x0:x1]=np.clip(np.rint(edited),0,255).astype(np.uint8)
        return out

def diagnostics(session):
    out=session.original.copy()
    for f in session.faces:
        x0,y0,x1,y1=f.box; p=out[y0:y1,x0:x1]
        a=f.mask[:,:,None]*.35
        out[y0:y1,x0:x1]=np.rint(p*(1-a)+np.array([40,210,155])*a).astype(np.uint8)
    for s in session.spots:
        cv2.circle(out,(s['x'],s['y']),s['r']+3,(255,180,20) if s['enabled'] else (120,120,120),1)
    return out
