"""Overlapping 512px neural patches with bounded local tone matching."""
import numpy as np,cv2

def match_colour(source,prediction,selected):
    valid=(selected==0).astype(np.float32)
    support=cv2.GaussianBlur(valid,(0,0),8)
    nearby=cv2.GaussianBlur(source.astype(np.float32)*valid[:,:,None],(0,0),8)/np.maximum(support[:,:,None],1e-5)
    smooth=cv2.GaussianBlur(prediction.astype(np.float32),(0,0),8)
    confidence=np.clip((support-.12)/.45,0,1)
    correction=np.clip(nearby-smooth,-10,10)*confidence[:,:,None]
    result=prediction+correction
    # Apply one headroom factor to all channels, avoiding independent clipping.
    delta=result-prediction;limit=np.ones(selected.shape,np.float32)
    for ch in range(3):
        change=delta[:,:,ch];p=prediction[:,:,ch]
        ratio=np.where(change>0,(255-p)/np.maximum(change,1e-5),p/np.maximum(-change,1e-5))
        limit=np.minimum(limit,np.where(np.abs(change)<1e-5,1,np.clip(ratio,0,1)))
    return prediction+delta*limit[:,:,None]

def repair(rgb,mask,predict,progress=None,cancel=None,precision=False):
    source=np.asarray(rgb);selected=mask>0;h,w=selected.shape
    ys,xs=np.nonzero(selected);count=len(xs)
    if not count:return source.astype(np.float32) if precision else source.copy(),dict(tiles=0,changed_pixels=0)
    tiles=[]
    for y in range(0,h,384):
        for x in range(0,w,384):
            if selected[max(0,y-64):min(h,y+448),max(0,x-64):min(w,x+448)].any():tiles.append((x-64,y-64))
    if len(tiles)>96:raise ValueError('选区过大，请分批修复；每批最多96个重叠图块。')
    sums=np.zeros((count,3),np.float32);weights=np.zeros(count,np.float32)
    ramp=np.minimum(np.arange(512)+1,512-np.arange(512)).astype(np.float32)/64
    ramp=np.minimum(ramp,1);window=ramp[:,None]*ramp[None,:]
    for n,(xa,ya) in enumerate(tiles):
        if cancel and cancel.is_set():raise RuntimeError('已取消，未应用修复。')
        if progress:progress(f'AI 重叠修复与颜色匹配 {n+1}/{len(tiles)}…')
        xb,yb=xa+512,ya+512;x0,y0,x1,y1=max(0,xa),max(0,ya),min(w,xb),min(h,yb)
        pads=(max(0,-ya),max(0,yb-h),max(0,-xa),max(0,xb-w))
        patch=cv2.copyMakeBorder(source[y0:y1,x0:x1],*pads,cv2.BORDER_REFLECT_101)
        matte=cv2.copyMakeBorder(selected[y0:y1,x0:x1].astype(np.uint8),*pads,cv2.BORDER_CONSTANT,value=0)
        prediction=predict(patch,matte)
        if prediction.shape!=patch.shape or not np.isfinite(prediction).all():raise ValueError('AI 修复返回无效像素。')
        prediction=match_colour(patch,prediction,matte)
        lo=np.searchsorted(ys,y0);hi=np.searchsorted(ys,y1)
        ids=np.arange(lo,hi);ids=ids[(xs[ids]>=x0)&(xs[ids]<x1)]
        py,px=ys[ids]-ya,xs[ids]-xa;weight=window[py,px]
        sums[ids]+=prediction[py,px]*weight[:,None];weights[ids]+=weight
    if np.any(weights<=0):raise ValueError('修复图块没有完整覆盖选区，未应用结果。')
    output=source.astype(np.float32).copy() if precision else source.copy()
    values=sums/weights[:,None]
    output[ys,xs]=values if precision else np.clip(np.rint(values),0,255).astype(np.uint8)
    return output,dict(tiles=len(tiles),overlap=128,colour_correction_limit=10,changed_pixels=int(np.count_nonzero(np.any(output!=source,axis=2))))
