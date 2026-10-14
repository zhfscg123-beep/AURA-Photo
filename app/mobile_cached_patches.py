"""Apply imported mobile repair deltas before the desktop photo pipeline."""
import numpy as np
def apply(rgb,extensions):
    records=extensions.get('mobile_cached_patches',[])
    if not records:return rgb
    from effect_controls import settings
    enabled,opacity=settings(extensions,'mobile_cache')
    if not enabled or not opacity:return rgb
    out=rgb.copy()
    for record in records:
        a,b,c,d=record['box'];delta=extensions.get('assets',{}).get(record['asset'])
        if delta is None:continue
        if not (0<=a<c<=rgb.shape[1] and 0<=b<d<=rgb.shape[0])or delta.shape!=(d-b,c-a,3):raise ValueError('手机修补缓存位置无效。')
        out[b:d,a:c]+=delta*float(record['strength'])*opacity
    return np.clip(out,0,255).astype(np.float32)
