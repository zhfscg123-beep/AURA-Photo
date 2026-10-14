"""Independent, zero-default controls; methods/limits are explicit in the UI."""
FACE_REPAIR=[('blemish_all','祛斑祛痘',0,100),('dark_spots','祛斑点候选',0,100),
 ('moles','祛深色点 / 痣点候选',0,100),('sweat','祛汗珠亮点',0,100),
 ('nose_debris','鼻部细小瑕疵',0,100),('beard_remove','减淡胡须 / 唇毛',0,100)]
FACE_DETAILS=[('texture_keep','修复质感保留',0,100),('eye_bags','淡化眼袋光影',0,100),
 ('lip_lines','唇纹修整',0,100),('jaw_enhance','下颌线光影增强',0,100),
 ('beard_protect','胡须保护',0,100),('makeup_protect','妆容色彩保护',0,100)]
BODY_REPAIR=[('body_spots','身体祛瑕疵',0,100),('body_moles','身体深色点候选',0,100),('body_tattoo','纹身候选修复 · 实验',0,100)]
BODY_SKIN=[('body_smooth','身体质感磨皮',0,100),('body_hf','身体高频纹理',-100,100),('body_lf','身体低频平整',0,100),
 ('body_hydrate','身体水润柔化',0,100),('body_whiten','身体美白',0,100),('body_translucent','身体肤色透亮',0,100),
 ('body_even','身体肤色均匀',0,100),('body_to_face','身体向面部肤色靠拢',0,100),
 ('body_redness','身体红润（旧配置兼容）',-100,100),('body_temp','身体色温',-100,100),('body_tint','身体红润 / 色调',-200,200),
 ('neck_wrinkles','颈纹淡化',0,100),('stretch_marks','身体细纹 / 妊娠纹 · 实验',0,100),('clavicle','锁骨光影增强 · 实验',0,100)]
BODY_SKIN += [('sample_body','身体取样肤色匹配',0,100),('color_body','身体肤色方案强度',0,100),('match_body_bright','身体向最亮面部肤色靠拢',0,100)]
COLOR_FACE=[('color_face','面部肤色方案强度',0,100),('sample_face','面部取样肤色匹配',0,100),
 ('match_face_bright','面部向最亮肤色靠拢',0,100),('face_hf','面部高频纹理增强',-100,100)]
COLOR_DATA=[('skin_choice','肤色方案编号',0,8),('sample_r','取样R',0,255),('sample_g','取样G',0,255),('sample_b','取样B',0,255)]
BODY=BODY_REPAIR+BODY_SKIN
BODY_SHAPE=[('body_slim','自动瘦身',0,50),('waist_slim','自动瘦腰',0,50),('leg_slim','自动瘦腿',0,50),('leg_length','拉腿',0,50)]
VOLUME=[('stereo_features','中性灰立体 · 五官',0,100),('stereo_contour','中性灰立体 · 轮廓',0,100),
 ('volume_all','全脸光影丰盈 · 档位',0,4),('vol_forehead','额头光影丰盈',0,100),('vol_midface','面中光影丰盈',0,100),
 ('vol_cheek','面颊光影丰盈',0,100),('vol_nosebase','鼻基底光影丰盈',0,100),
 ('vol_eye_left','眼窝 · 人物左侧',0,100),('vol_eye_right','眼窝 · 人物右侧',0,100),
 ('vol_eye_inner','眼头阴影柔化',0,100),('vol_brow','眉弓光影丰盈',0,100),('vol_chin','下巴光影丰盈',0,100),('vol_corner','嘴角光影丰盈',0,100)]
for zone,label in [('forehead','额头'),('midface','面中'),('nosebase','鼻基底'),('chin','下巴')]:
 VOLUME += [('vol_'+zone+'_flat',label+'丰盈 · 平整',0,100),('vol_'+zone+'_light',label+'丰盈 · 提亮',0,100)]
FORM=[('double_chin','双下巴局部收紧 · 实验',0,100),('double_chin_shadow','双下巴阴影淡化',0,100),
 ('armpit_left','腋下局部收紧 · 人物左侧 · 实验',0,100),('armpit_right','腋下局部收紧 · 人物右侧 · 实验',0,100)]
FORM_GEOMETRY=('double_chin','armpit_left','armpit_right')
ADVANCED=FACE_REPAIR+FACE_DETAILS+BODY+BODY_SHAPE+COLOR_FACE+COLOR_DATA+VOLUME+FORM
TYPE_LABELS={k:label for k,label,_,_ in FACE_REPAIR+BODY_REPAIR}
TYPE_LABELS['body_skin']='身体美颜范围'
