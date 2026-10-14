"""Map the existing MediaPipe face mesh to the editor's WFLW control layout.

This is a geometric adapter, not a second 98-point detector. Contour samples
come from arc-length interpolation; feature controls use mesh vertices.
"""
import numpy as np

JAW=[127,234,93,132,58,172,136,150,149,176,148,152,377,400,378,379,365,397,288,361,323,454,356]

def _sample(points,count):
    distances=np.r_[0,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    if distances[-1]<1e-6:raise ValueError('面部轮廓过小，无法可靠重塑。')
    at=np.linspace(0,distances[-1],count)
    return np.column_stack([np.interp(at,distances,points[:,i]) for i in (0,1)])

def controls(mesh):
    mesh=np.asarray(mesh,dtype=np.float64)
    if mesh.ndim!=2 or mesh.shape[1]!=2 or len(mesh)<468 or not np.isfinite(mesh).all():raise ValueError('面部网格定位无效。')
    jaw=np.vstack([_sample(mesh[JAW[:12]],17),_sample(mesh[JAW[11:]],17)[1:]])
    features=[70,63,105,66,107,55,65,52,46,
              336,296,334,293,300,276,283,282,295,
              168,6,197,1,98,97,2,326,327,
              33,160,159,158,133,153,145,144,
              362,385,386,387,263,373,374,380,
              61,40,37,0,267,270,291,321,314,17,84,91,
              78,81,13,311,308,402,14,178]
    pupils=mesh[[468,473]] if len(mesh)>=478 else np.array([mesh[[33,133]].mean(0),mesh[[263,362]].mean(0)])
    return np.vstack([jaw,mesh[features],pupils])
