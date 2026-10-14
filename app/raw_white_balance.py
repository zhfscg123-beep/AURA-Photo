"""Shared LibRaw WB selection and honest post-decode gain provenance."""
import numpy as np
import color_science as cs

REVISION=1

def options(raw,settings):
    mode=settings['white_balance'];user=None
    if mode=='custom':
        # Preserve the existing scene decoder's relative-daylight convention.
        # This is an approximation, not an Adobe camera temperature calibration.
        white=np.linalg.inv(cs.SPACES['sRGB'][0])@cs.white_xyz(settings['kelvin'])
        white=np.maximum(white,1e-4);white/=white[1]
        daylight=np.asarray(raw.daylight_whitebalance,np.float64).copy()
        if daylight.shape!=(4,) or not np.isfinite(daylight).all() or np.any(daylight[:3]<=0):
            raise ValueError('此 RAW 缺少有效日光白平衡增益，不能可靠应用自定义色温。请使用拍摄白平衡或机型配置。')
        if daylight[3]<=0:daylight[3]=daylight[1]
        user=daylight/white[[0,1,2,1]]
        user[[1,3]]*=np.exp(-settings['tint']*.003)
        user=user.tolist()
    return dict(use_camera_wb=mode=='camera',use_auto_wb=mode=='auto',user_wb=user)

def provenance(raw,settings,selected):
    actual=getattr(raw,'auto_whitebalance',None)
    actual=[] if actual is None else list(map(float,actual))
    if actual and (len(actual)!=4 or not np.isfinite(actual).all()):actual=[]
    requested=list(raw.camera_whitebalance) if settings['white_balance']=='camera' else selected['user_wb'] or actual
    return dict(applied_white_balance=list(map(float,requested)),decoder_white_balance=actual,
                white_balance_method='relative_daylight_approximation' if settings['white_balance']=='custom' else settings['white_balance'],
                white_balance_engine='LibRaw',white_balance_revision=REVISION)
