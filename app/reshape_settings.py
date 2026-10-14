"""Numeric per-person geometry settings; presets are editable starting points."""
RESHAPE=[('rs_slim_left','瘦脸 · 人物左侧',0,100),('rs_slim_right','瘦脸 · 人物右侧',0,100),
 ('rs_jaw_left','下颌宽度 · 人物左侧',-100,100),('rs_jaw_right','下颌宽度 · 人物右侧',-100,100),
 ('rs_chin_width','下巴宽度',-100,100),('rs_chin_length','下巴长短',-100,100)]
SMART=[('fs_eye_left_size','眼睛大小 · 人物左侧',-100,100),('fs_eye_right_size','眼睛大小 · 人物右侧',-100,100),
 ('fs_eye_left_width','眼睛宽度 · 人物左侧',-100,100),('fs_eye_right_width','眼睛宽度 · 人物右侧',-100,100),
 ('fs_eye_left_height','眼睛高度 · 人物左侧',-100,100),('fs_eye_right_height','眼睛高度 · 人物右侧',-100,100),
 ('fs_eye_left_tilt','眼睛倾斜 · 人物左侧',-100,100),('fs_eye_right_tilt','眼睛倾斜 · 人物右侧',-100,100),
 ('fs_eye_distance','眼距',-100,100),('fs_nose_width','鼻子宽度',-100,100),('fs_nose_height','鼻子长短',-100,100),
 ('fs_mouth_width','嘴巴宽度',-100,100),('fs_mouth_height','嘴巴位置 / 高低',-100,100),
 ('fs_upper_lip','上唇厚度',-100,100),('fs_lower_lip','下唇厚度',-100,100),('fs_smile','嘴角 / 微笑',-100,100),
 ('fs_face_width','脸部宽度',-100,100)]
CLASSIC_KEYS=tuple(k for k,_,_,_ in RESHAPE)
SMART_KEYS=tuple(k for k,_,_,_ in SMART)
KEYS=CLASSIC_KEYS+SMART_KEYS
PRESETS={
 '无':(0,0,0,0,0,0),
 '自然':(20,20,-8,-8,-8,0),
 '柔和':(12,12,6,6,12,-6),
 '利落':(26,26,-22,-22,-15,8),
 '圆脸参考':(38,38,-18,-18,-20,12),
 '长脸参考':(12,12,6,6,8,-28),
 '方脸参考':(26,26,-35,-35,-18,0),
 'V形参考':(34,34,-24,-24,-34,16),
}

def signature(values):return tuple(round(float(values.get(k,0)),4) for k in KEYS)
def active(values):return any(signature(values))
def preset_name(values):
    if any(float(values.get(k,0)) for k in SMART_KEYS):return '自定义'
    target=tuple(round(float(values.get(k,0)),4) for k in CLASSIC_KEYS)
    return next((name for name,vector in PRESETS.items() if target==vector),'自定义')
