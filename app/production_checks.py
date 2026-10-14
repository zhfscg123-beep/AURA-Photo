"""Observable delivery checks; visual aesthetics are never scored as accuracy."""
import numpy as np

def inspect(document,pixels,layers=(),pending=()):
    rows=[]
    def add(key,status,message):rows.append(dict(key=key,status=status,message=message))
    valid=pixels.ndim==3 and pixels.shape[-1]==3 and min(pixels.shape[:2])>0 and np.isfinite(pixels).all()
    if not valid:
        add('pixels','error','成片含无效像素或尺寸异常，请重新渲染。')
        return dict(exportable=False,checks=rows)
    add('pixels','ok',f'成片像素有效：{pixels.shape[1]} × {pixels.shape[0]}。')
    step=max(1,int(np.ceil(max(pixels.shape[:2])/1000)));sample=pixels[::step,::step]
    high=float(np.mean(np.all(sample>=254.5,axis=2)));low=float(np.mean(np.all(sample<=.5,axis=2)))
    add('clipping','review' if max(high,low)>.02 else 'ok',f'抽样纯白 {high:.1%}／纯黑 {low:.1%}；请结合原图判断是否需要保留细节。')
    source=document.metadata.get('camera_source')
    if source=='embedded_preview':add('precision','review','当前使用机内 8 位预览，16 位导出不能恢复 RAW 精度。')
    elif document.is_raw:
        add('precision','ok',f'RAW 来源保留 {document.precision} 位像素。')
        if source!='dcp_raw':add('profile','review','当前使用基础／线性 RAW 显影，拍摄风格未由机型配置复现。')
        else:add('profile','ok','已使用机型匹配配置：'+document.metadata.get('profile_name',''))
        base=document.metadata.get('raw_baseline',{})
        if base.get('verified'):add('baseline','ok',f"当前亮度基准已验证：{base['ev']:+.2f} EV。")
        else:add('baseline','review','当前机型、ISO 和配置组合尚无 Adobe 亮度对照验证；请检查底图。')
        if document.metadata.get('white_balance_method')=='relative_daylight_approximation':add('wb','review','基础 RAW 自定义色温为近似值，请检查灰色与肤色。')
    elif not document.metadata.get('input_profile'):
        add('profile','review','输入没有嵌入 ICC，按 sRGB 解释；请核对来源色彩空间。')
    else:add('profile','ok','输入 ICC 已转换：'+document.metadata['input_profile'])
    engine=document.metadata.get('retouch_engine',1)
    add('skin_engine','ok','皮肤引擎：'+('多尺度与细节保护；深色点保护'+('开启。' if document.metadata.get('protect_dark_points',False) else '关闭，可手动取消误选。') if engine==2 else '旧项目兼容模式；沿用原有皮肤处理。'))
    for message in pending:add('pending','error',message)
    for layer in layers:
        if not layer.get('enabled',True):continue
        if layer.get('ai_region'):add('mask','review',layer['name']+'：请放大检查发丝、手指、帽檐及背景亮斑。')
    add('visual','review','人工检查肤色、纹理、形变和整组风格；这些项目无法由当前数值检查判定合格。')
    return dict(exportable=not any(r['status']=='error' for r in rows),checks=rows,clipping_sample=dict(white=high,black=low,step=step))

def for_app(app):
    pending=[]
    if getattr(app,'_render_failed',False):pending.append('当前渲染失败，不能使用旧预览交付。')
    if app.repair_pending():pending.append('新补选区域尚未完成 AI 修复。')
    if app.shape_pending():pending.append('形变仍待处理，请先完成生成。')
    pixels=app.prepare_export_image(app.output_float.copy())
    return inspect(app.document,pixels,app.region_layers,pending)
