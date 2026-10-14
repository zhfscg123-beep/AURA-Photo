"""Reference-region selection and diagnostics, independent from colour transfer."""
import cv2
import numpy as np
from damo_engine import PortraitAISession

SCOPES={'全图':None,'人物肤色':'skin','面部皮肤':'face','身体皮肤':'body',
        '衣物':'clothes','头发':'hair','整个人物':'person','背景':'background'}

def full_frame(shape):
    """Only image geometry is needed for full-frame/rectangle sampling."""
    return dict(skin=np.zeros(shape,bool),people=[])

class ReferenceSession(PortraitAISession):
    """Parse reference regions without running unrelated blemish detection."""
    def scan_ai(self,confidence=.35,progress=None):
        from ai_engine import parse_skin,square_box
        from region_masks import face_parts
        for f in self.faces:
            if progress:progress('正在识别参考图的皮肤、头发和五官…')
            box=square_box(f.box,self.original.shape)
            _,_,labels=parse_skin(self.original,box,self.parser_model)
            self.parse_contexts[len(self.part_regions)]=(box,labels)
            parts,hair,nostrils,local=face_parts(self.original,f,box,labels)
            self.part_regions.append(parts);self.part_labels.append(local)
            self.semantic_skin.append(parts['skin']);self.hair.append(hair);self.nostrils.append(nostrils)

def select(data,scope,person=None,roi=None):
    if scope not in SCOPES:raise ValueError('未知参考图区域。')
    key=SCOPES[scope]
    if key is None:mask=None
    elif person is None or key=='background':mask=data[key]
    else:
        if type(person) is not int or not 0<=person<len(data['people']):
            raise ValueError('追色人物已不可用，请重新确认对应人物。')
        mask=data['people'][person][key]
    if roi is not None:
        h,w=data['skin'].shape
        box=np.asarray(roi,dtype=np.float64)
        if box.shape!=(4,) or not np.isfinite(box).all() or np.any(box<0) or np.any(box>1) or box[0]>=box[2] or box[1]>=box[3]:
            raise ValueError('参考图取样框无效。')
        a,b,c,d=np.rint(box*[w,h,w,h]).astype(int)
        rectangle=np.zeros((h,w),bool);rectangle[b:d,a:c]=True
        mask=rectangle if mask is None else mask&rectangle
    return mask

def diagnostic(mask,shape):
    if mask is None:return '全图取样；构图和物体颜色占比会影响匹配。'
    count=int(np.count_nonzero(mask));total=int(np.prod(shape))
    # Use the same bounded sampling size as statistics, not native pixel count.
    scale=min(1,1200/max(shape));size=(max(1,round(shape[1]*scale)),max(1,round(shape[0]*scale)))
    sampled=cv2.resize(mask.astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
    if np.count_nonzero(sampled)<40:raise ValueError('该区域未可靠识别或太小，请换人物、范围或取样框。')
    return f'选中 {count/total:.1%}；请核对边界，覆盖比例不代表识别准确率。'
