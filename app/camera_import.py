"""Camera-setting provenance without speculative firmware emulation."""
VENDOR_FIELDS=[('Contrast','机内对比度'),('Saturation','机内饱和度'),('Sharpness','机内锐化'),('Brightness','机内亮度'),('PictureProfile','图片配置／伽马'),('PictureEffect','图片效果'),('DynamicRangeOptimizer','动态范围优化'),('AutoHDR','机内 HDR'),('HighISONoiseReduction','高 ISO 降噪'),('LongExposureNoiseReduction','长曝光降噪'),('SoftSkinEffect','机内美颜')]
def report(meta,settings,source,precision,crop_applied,raw_info):
    rows=[]
    def add(key,label,value,status):rows.append(dict(key=key,label=label,value=str(value),status=status))
    if raw_info.get('raw_engine'):
        add('RAWEngine','显影引擎',raw_info['raw_engine'],'旧项目兼容，保留原显影结果' if 'legacy' in raw_info['raw_engine'] else '当前实际显影路径')
    for key,label in [('Model','机型'),('LensModel','镜头')]:add(key,label,meta.get(key,'未提供'),'已读取' if key in meta else '元数据未提供')
    for key,label in [('iso','ISO'),('aperture','光圈'),('shutter','快门（秒）'),('focal_length','焦距（mm）')]:add(key,label,raw_info.get(key,'未提供'),'拍摄数据已包含在 RAW 中，不重复施加')
    add('ExposureCompensation','拍摄曝光补偿（EV）',meta.get('ExposureCompensation','未提供'),'拍摄曝光效果已包含在 RAW 中；保留，不重复叠加' if 'ExposureCompensation' in meta else '元数据未提供')
    status='已包含在机内预览中' if source=='embedded_preview' else '使用 RAW 拍摄白平衡' if settings['white_balance']=='camera' else '已记录；当前白平衡已由用户切换'
    add('WhiteBalance','拍摄白平衡',meta.get('WhiteBalance','RAW 拍摄白平衡增益'),status)
    add('ColorTemperature','机内色温',meta.get('ColorTemperature','未提供'),'只显示相机记录，不推测自动白平衡的色温')
    if raw_info.get('white_balance_method')=='relative_daylight_approximation':
        add('CustomWB','自定义白平衡',f"{settings['kelvin']} K / 色调 {settings['tint']:g}",'已应用；基础 RAW 色温为近似值，尚未与 Adobe 校准')
    if raw_info.get('decoder_white_balance'):
        add('DecodedWB','显影白平衡增益',raw_info['decoder_white_balance'],'读取本次显影实际使用的增益')
    baseline=raw_info.get('raw_baseline')
    if baseline:
        add('RAWBaseline','AURA 额外亮度补偿',f"{baseline.get('ev',0):+.2f} EV",'使用所选相机配置；不额外施加固定曝光补偿')
    style=next((str(meta[k]) for k in ('CreativeStyle','CreativeLook','PictureStyle','PictureControlName','FilmMode','FilmSimulation') if k in meta),'未提供')
    if source=='embedded_preview':status='已包含在机内预览中'
    elif source=='dcp_raw' and settings['camera_profile']=='as_shot':status='使用机型匹配 DCP 近似拍摄风格'
    elif source=='dcp_raw':status='已记录；当前使用用户选择的配置／滤镜基底'
    elif source=='raw_scene':status='已读取；当前为线性显影，未套用拍摄风格'
    elif not settings['camera_look']:status='已读取；用户未启用相机风格'
    else:status='已读取；未找到可用的机型风格配置'
    add('Style','拍摄风格',style,status)
    crop_status='默认构图使用机内裁切；RAW 完整画幅保留' if raw_info.get('camera_crop_composition') else '已按 RAW 裁切数据应用' if crop_applied else '保持有效画幅；未额外裁切'
    add('AspectRatio','相机画幅／裁切',meta.get('AspectRatio','RAW 有效传感器画幅'),crop_status)
    add('Orientation','方向',raw_info.get('orientation','未提供'),'显影时按 RAW 方向应用')
    for key,label in VENDOR_FIELDS:
        status='已包含在机内预览像素中' if source=='embedded_preview' else '参数已记录；厂商专有处理未复刻'
        add(key,label,meta.get(key,'未提供'),status if key in meta else '元数据未提供；不猜测设置')
    return dict(schema=1,precision=precision,source=source,rows=rows)
def summary(data):
    if data['source']=='embedded_preview':return '机内预览保留已渲染外观；8位像素，不能恢复 RAW 精度。'
    return 'RAW16：拍摄白平衡与风格导入情况见详情；机内锐化、降噪、DRO、美颜等参数仅记录，不复刻厂商处理。'
def show(app):
    if app.document is None:return
    import tkinter as tk
    from tkinter import ttk
    data=app.document.metadata.get('camera_import')
    if not data:return
    window=tk.Toplevel(app.root);window.title('相机设置导入详情');window.geometry('900x600');window.transient(app.root)
    ttk.Label(window,text=summary(data),wraplength=860).pack(fill='x',padx=16,pady=12)
    frame=ttk.Frame(window);frame.pack(fill='both',expand=True,padx=16,pady=(0,12));tree=ttk.Treeview(frame,columns=('setting','camera','status'),show='headings')
    for key,title,width in (('setting','设置',160),('camera','相机记录',220),('status','AURA 导入状态',470)):tree.heading(key,text=title);tree.column(key,width=width,anchor='w')
    scroll=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set);tree.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
    for row in data['rows']:tree.insert('',tk.END,values=(row['label'],row['value'],row['status']))
    ttk.Button(window,text='关闭',command=window.destroy).pack(pady=(0,12))
