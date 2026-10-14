"""Pixel-scale frequency detail with edge-aware smoothing and noise-safe boost."""
import numpy as np,cv2

def adaptive(source,width):
    source=source.astype(np.float32);sigma=max(.6,min(1.2,width*.001))
    fine=cv2.GaussianBlur(source,(0,0),sigma)
    low=cv2.bilateralFilter(fine,0,18,max(2,min(20,width*.012)))
    luma=source@np.array([.2126,.7152,.0722],np.float32)
    high=luma-cv2.GaussianBlur(luma,(0,0),sigma)
    gx=cv2.Sobel(luma,cv2.CV_32F,1,0,ksize=3)/4;gy=cv2.Sobel(luma,cv2.CV_32F,0,1,ksize=3)/4
    edge=np.sqrt(gx*gx+gy*gy)
    noise=float(np.median(np.abs(high)))*1.4826
    energy=cv2.GaussianBlur(np.abs(high),(0,0),1)
    boost=np.clip((energy-noise*.8)/(energy+noise*.5+1e-3),0,1)
    smooth=np.clip(1-(edge/12)**2,.12,1)
    return fine,low,smooth,boost
