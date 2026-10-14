"""Local develop components and editable gradient pins in the shared viewport."""
import copy
import tkinter as tk
from tkinter import ttk
import numpy as np
from dark_ui import Section,COLORS
from dpi_support import dp
from region_masks import LOCAL_DEFAULTS,MAX_LAYERS
from local_develop import MAX_COMPONENTS

def source_screen(app,p):
    h,w=app.document.rgb.shape[:2];target=np.array(p,np.float32)*[max(1,w-1),max(1,h-1)];q=target.copy()
    for _ in range(8):
        mapped=app.original_point(q);error=target-mapped
        if np.linalg.norm(error)<.01:break
        jac=np.column_stack([app.original_point(q+[1,0])-mapped,app.original_point(q+[0,1])-mapped])
        try:q+=np.linalg.solve(jac,error)
        except np.linalg.LinAlgError:break
    return app.view.to_canvas(*q,app.size())

class WorkbenchMasks:
    def __init__(self,workbench):
        self.workbench=workbench;self.app=workbench.app;self.drag=None;self.last_signature=None;self.syncing=False;self.ai_pending=False
        a=self.app;self.panel=Section(workbench.panel,'局部蒙版',opened=True);workbench.mask_panel=self.panel
        body=self.panel.body
        self.mask_view=tk.StringVar(value='彩色叠加')
        ttk.Label(body,text='检查蒙版范围').pack(anchor='w')
        view=ttk.Combobox(body,textvariable=self.mask_view,values=['彩色叠加','黑白蒙版','仅看成片'],state='readonly');view.pack(fill='x',pady=4)
        view.bind('<<ComboboxSelected>>',lambda event:self.update_view())
        ttk.Button(body,text='撤销当前蒙版最后一笔',command=self.remove_last_brush).pack(fill='x',pady=4)
        self.stroke_note=tk.StringVar();ttk.Label(body,textvariable=self.stroke_note,style='Muted.TLabel',wraplength=285).pack(fill='x')
        ai=Section(body,'AI 分区',opened=True);self.ai_section=ai
        self.ai_kinds={key:tk.BooleanVar(value=True) for key in ('person','sky','background')}
        row=ttk.Frame(ai.body);row.pack(fill='x')
        for key,label in [('person','人物'),('sky','天空'),('background','背景')]:ttk.Checkbutton(row,text=label,variable=self.ai_kinds[key]).pack(side='left',padx=4)
        self.ai_generate=ttk.Button(ai.body,text='AI 生成可编辑蒙版',command=self.generate_ai);self.ai_generate.pack(fill='x',pady=4);a.controls.append(self.ai_generate)
        self.ai_apply=ttk.Button(ai.body,text='AI 套用当前滤镜的分区参数',command=lambda:self.generate_ai(True));self.ai_apply.pack(fill='x',pady=4);a.controls.append(self.ai_apply)
        self.ai_refine=ttk.Button(ai.body,text='重新识别分区范围（保留调色）',command=lambda:self.generate_ai(regenerate=True));self.ai_refine.pack(fill='x',pady=4);a.controls.append(self.ai_refine)
        self.ai_cancel=ttk.Button(ai.body,text='取消识别',command=a.cancel.set,state='disabled');self.ai_cancel.pack(fill='x',pady=4)
        self.ai_note=tk.StringVar(value='人物、天空和背景分别生成柔边蒙版。六款“日系参考”和“开源精选 → Taro 秋日肖像”支持分区参数，均可独立微调和画笔修补。')
        ttk.Label(ai.body,textvariable=self.ai_note,style='Muted.TLabel',wraplength=285).pack(fill='x',pady=4)
        self.layers=ttk.Combobox(body,state='readonly');self.layers.pack(fill='x');self.layers.bind('<<ComboboxSelected>>',self.select)
        self.layers.pack_configure(before=ai)
        row=ttk.Frame(body);row.pack(fill='x',pady=6)
        ttk.Button(row,text='新建蒙版',command=self.new).pack(side='left',expand=True,fill='x')
        ttk.Button(row,text='删除蒙版',command=self.delete).pack(side='right',expand=True,fill='x')
        ttk.Checkbutton(body,text='启用当前蒙版',variable=a.layer_enabled,command=lambda:(a.layer_toggle_changed(),self.sync())).pack(anchor='w',before=ai)
        self.operation=tk.StringVar(value='添加');self.kind=tk.StringVar(value='软画笔')
        brush_row=ttk.Frame(body);brush_row.pack(fill='x',pady=6)
        brush_row.pack_configure(before=ai)
        for title,operation in [('补选画笔','添加'),('擦除画笔','减去')]:
            control=ttk.Button(brush_row,text=title,command=lambda op=operation:self.activate_brush(op));control.pack(side='left',expand=True,fill='x',padx=2);a.controls.append(control)
        for title,var,values in [('组合',self.operation,['添加','减去','交集']),('形状',self.kind,['软画笔','线性渐变','径向渐变','亮度范围','颜色范围'])]:
            ttk.Label(body,text=title).pack(anchor='w');ttk.Combobox(body,textvariable=var,values=values,state='readonly').pack(fill='x')
        button=ttk.Button(body,text='在照片上添加组件',command=self.arm);button.pack(fill='x',pady=6)
        a.register_mode_button(button,'develop_component')
        self.components=ttk.Combobox(body,state='readonly');self.components.pack(fill='x')
        ttk.Button(body,text='删除选中组件',command=self.remove_component).pack(fill='x',pady=4)
        ttk.Button(body,text='反转选中组件',command=self.invert_component).pack(fill='x',pady=4)
        self.radius=tk.DoubleVar(value=8);self.feather=tk.DoubleVar(value=50);self.flow=tk.DoubleVar(value=100);self.density=tk.DoubleVar(value=100)
        self.low=tk.DoubleVar(value=0);self.high=tk.DoubleVar(value=1);self.soft=tk.DoubleVar(value=.1)
        settings=Section(body,'笔刷与范围',opened=False)
        settings.pack_configure(before=ai)
        self.brush_settings=settings
        for title,var,lo,hi in [('笔刷半径 / 原图像素',self.radius,1,300),('笔刷羽化',self.feather,0,100),('流量',self.flow,1,100),('密度',self.density,1,100),('亮度下界',self.low,0,4),('亮度上界',self.high,0,4),('范围过渡',self.soft,.001,1)]:a.slider(settings.body,title,var,lo,hi,lambda:None,decimals=2 if hi<=4 else 0,mutating=False)
        ttk.Label(settings.body,text='可输入 1 像素半径修细边；右键临时擦除，空格拖动平移，Ctrl＋滚轮缩放。',style='Muted.TLabel',wraplength=285).pack(fill='x',pady=4)
        adjust=Section(body,'局部调色',opened=True);self.edit_controls=[]
        for key in ('exposure','temperature','tint','saturation','contrast','highlights','shadows','whites','blacks','texture','clarity','dehaze','denoise_luma','denoise_chroma','sharpen','edge_protect','expand','feather','opacity'):
            from region_masks import LOCAL_RANGES
            from creative_color import CONTROLS
            title=next((row[1] for row in CONTROLS if row[0]==key),{'opacity':'蒙版不透明度','edge_protect':'边缘保护','expand':'边缘扩展 / 收缩（像素）','feather':'边缘羽化（像素）'}.get(key,key));lo,hi=LOCAL_RANGES[key]
            self.edit_controls.append(a.slider(adjust.body,title,a.layer_vars[key],lo,hi,a.layer_values_changed,decimals=2 if key=='exposure' else 0))
        self.strength_control=a.slider(adjust.body,'分区调色强度 %',a.layer_vars['strength'],0,200,a.layer_values_changed)
        self.link_note=tk.StringVar();ttk.Label(adjust.body,textvariable=self.link_note,style='Muted.TLabel',wraplength=285).pack(fill='x')
        self.unlink_button=ttk.Button(adjust.body,text='解除当前蒙版与滤镜联动',command=self.unlink);self.unlink_button.pack(fill='x',pady=4)
        grading=Section(body,'局部阴影与高光颜色',opened=False)
        from creative_color import CONTROLS
        for key in ('shadow_hue','shadow_color','shadow_luma','highlight_hue','highlight_color','highlight_luma','curve_saturation'):
            title=next(row[1] for row in CONTROLS if row[0]==key);lo,hi=__import__('region_masks').LOCAL_RANGES[key]
            self.edit_controls.append(a.slider(grading.body,title,a.layer_vars[key],lo,hi,a.layer_values_changed))
        hsl=Section(body,'局部 HSL 颜色',opened=False);self.hsl_color=tk.StringVar(value='橙')
        combo=ttk.Combobox(hsl.body,textvariable=self.hsl_color,values=list(__import__('creative_color').HUES),state='readonly');combo.pack(fill='x');combo.bind('<<ComboboxSelected>>',lambda e:self.sync_hsl())
        self.hsl_values=[tk.DoubleVar(value=0) for _ in range(3)]
        for title,var in zip(('色相','饱和度','明亮度'),self.hsl_values):self.edit_controls.append(a.slider(hsl.body,title,var,-100,100,self.hsl_changed))
        ttk.Button(body,text='重置当前蒙版的调色',command=self.reset_color).pack(fill='x',pady=4)
        ttk.Checkbutton(body,text='显示蒙版范围',variable=a.mask_overlay,command=a.draw).pack(anchor='w',pady=6,before=ai)
        ttk.Label(body,text='渐变端点可直接拖动；参数数值提供键盘操作。添加、减去与交集按组件顺序组合。',style='Muted.TLabel',wraplength=285).pack(fill='x')
        workbench.bind_scroll(self.panel);self.sync()

    def layer(self):
        a=self.app;return a.region_layers[a.active_layer] if 0<=a.active_layer<len(a.region_layers) else None
    def sync(self):
        a=self.app;layer=self.layer()
        from ai_region_filters import SCHEMES
        preset=a.workflow_extensions.get('color_filter',{}).get('preset',{}).get('id')
        self.ai_generate.configure(state='normal' if a.document is not None and not a.busy else 'disabled')
        self.ai_refine.configure(state='normal' if a.document is not None and not a.busy else 'disabled')
        self.ai_apply.configure(state='normal' if a.document is not None and not a.busy and preset in SCHEMES else 'disabled')
        self.ai_cancel.configure(state='normal' if a.busy and self.ai_pending else 'disabled')
        if self.ai_pending and not a.busy:self.ai_pending=False
        link=layer.get('filter_link') if layer else None
        signature=(tuple(l['name'] for l in a.region_layers),a.active_layer,id(layer),len(layer.get('components',[])) if layer else 0,layer.get('enabled') if layer else False,link.get('amount') if link else None,bool(a.busy))
        if signature==self.last_signature:return
        self.last_signature=signature;self.layers.configure(values=[f'{i+1} · {l["name"]}' for i,l in enumerate(a.region_layers)])
        count=sum(c['shape']['kind']=='brush' for c in layer.get('components',[])) if layer else 0
        self.stroke_note.set(f'当前蒙版：{count} 笔手动修正 · 最多 {MAX_COMPONENTS} 个组件；移除最后一笔可用全局重做恢复。')
        if layer:self.layers.current(a.active_layer)
        else:self.layers.set('尚未创建蒙版')
        self.components.configure(values=[f'{i+1} · {c.get("operation","add")} · {c["shape"]["kind"]}' for i,c in enumerate(layer.get('components',[]))] if layer else [])
        if layer and layer.get('components'):self.components.current(len(layer['components'])-1)
        else:self.components.set('尚无附加组件')
        for control in self.edit_controls:control.configure(state='normal' if layer is not None and not a.busy else 'disabled')
        self.strength_control.configure(state='normal' if layer is not None and not a.busy and link is None else 'disabled')
        self.unlink_button.configure(state='normal' if layer is not None and not a.busy and link is not None else 'disabled')
        self.link_note.set(f'随滤镜强度 {link["amount"]:.0f}% 联动；各局部颜色与影调可独立修改。' if link else '当前蒙版独立调色；不会覆盖全局参数。')
        self.sync_hsl()

    def generate_ai(self,apply_filter=False,regenerate=False):
        a=self.app
        if a.document is None or a.session is None or a.busy or a._render_pending:return
        from ai_region_filters import source_key,create_layers,apply_recipe,SCHEMES
        kinds=[key for key,var in self.ai_kinds.items() if var.get()]
        if not kinds:a.status.set('请至少选择人物、天空或背景中的一项。');return
        a.flush_parameters();state=copy.deepcopy(a.workflow_extensions.get('color_filter',{}));preset=state.get('preset',{}).get('id')
        if apply_filter and preset not in SCHEMES:a.status.set('当前滤镜暂无专属分区参数；可先生成蒙版手动调色。');return
        rgb=a.session.original;source=source_key(rgb);identity=(id(a.document),id(a.session));session=a.session
        existing={l['ai_region']['kind']:l for l in a.region_layers if l.get('ai_region',{}).get('source')==source}
        missing=[key for key in kinds if key not in existing]
        if len(a.region_layers)+len(missing)>MAX_LAYERS:a.status.set('蒙版数量已达上限，请先删除不需要的蒙版。');return
        a.commit_edit('AI 分区调整前')
        def ready(result):
            self.ai_pending=False
            if identity!=(id(a.document),id(a.session)):a.status.set('照片已改变，未写入旧照片的 AI 蒙版。');return
            masks,info=result
            new=create_layers(masks,rgb.shape[:2],source,info['models'],missing) if missing else []
            if regenerate:
                for kind,layer in existing.items():
                    if kind not in kinds:continue
                    prob=masks[kind]
                    if prob.max()<128:continue
                    layer['mask_alpha']=prob.copy();layer['mask']=__import__('cv2').resize(prob,(rgb.shape[1],rgb.shape[0]),interpolation=__import__('cv2').INTER_LINEAR)>0
                    if kind=='person':layer['parameters'].setdefault('edge_protect',60.)
                    layer['ai_region']['models']=list(info['models'])
            a.region_layers.extend(new);items=[existing[key] for key in kinds if key in existing]+new
            if apply_filter:
                exposure=a.workflow_extensions.get('color',{}).get('values',{}).get('exposure',0)
                for layer in items:apply_recipe(layer,SCHEMES[preset][layer['ai_region']['kind']],preset,state['amount'],rgb,exposure)
            if items:a.active_layer=next(i for i,layer in enumerate(a.region_layers) if layer is items[0])
            a.mask_overlay.set(not apply_filter);a.overlay.set(False);a.sync_layers();self.last_signature=None;self.sync();a.refresh();a.record('AI 分区套用滤镜' if apply_filter else 'AI 重新识别分区范围' if regenerate else 'AI 生成分区蒙版')
            detected={layer['ai_region']['kind'] for layer in items};empty=[{'person':'人物','sky':'天空','background':'背景'}[key] for key in kinds if key not in detected]
            a.status.set(('AI 分区参数已套用，可在蒙版列表逐项调整。' if apply_filter else 'AI 分区范围已重新识别，保留局部调色和附加组件。' if regenerate else 'AI 蒙版已生成，可独立调色和修补。')+' · '+info['backend']+(' · 未检出：'+'、'.join(empty) if empty else ''))
            self.ai_note.set('AI 识别 '+info['backend']+f' · {info["seconds"]:.2f} 秒；'+('已更新 AI 基础范围，保留调色及附加修补组件。' if regenerate else '已有分区会复用并保留范围修补。'))
        if not missing and not regenerate:
            ready(({},dict(models=[],backend='复用已有蒙版',seconds=0)));return
        self.ai_pending=True;a.status.set('AI 正在准备人物与天空分区…')
        def job():
            cache=getattr(session,'_aura_scene_masks',None)
            if cache is not None and cache[0]==source and not regenerate:return cache[1]
            from ai_scene_masks import generate
            result=generate(rgb,a.progress,a.cancel);session._aura_scene_masks=(source,result);return result
        a.work(job,ready);self.sync()

    def sync_hsl(self):
        self.syncing=True
        try:
            layer=self.layer();values=layer.get('color_recipe',{}).get('hsl',{}).get(self.hsl_color.get(),[0,0,0]) if layer else [0,0,0]
            for var,value in zip(self.hsl_values,values):var.set(value)
        finally:self.syncing=False

    def hsl_changed(self):
        layer=self.layer();a=self.app
        if self.syncing or layer is None or a.busy:return
        if layer.get('color_process',1)!=2:a.status.set('请先将旧蒙版转换为专业调色。');self.sync_hsl();return
        values=[var.get() for var in self.hsl_values];key=self.hsl_color.get()
        if values==layer.get('color_recipe',{}).get('hsl',{}).get(key,[0,0,0]):return
        a.commit_edit('局部颜色调整前');layer.setdefault('color_recipe',{}).setdefault('hsl',{})[key]=values
        a.parameter_apply(a.refresh)

    def unlink(self):
        layer=self.layer();a=self.app
        if layer is None or a.busy or 'filter_link' not in layer:return
        a.commit_edit('解除分区滤镜联动前');layer['parameters']['strength']=layer.pop('filter_link')['amount']
        a.sync_layers();self.last_signature=None;self.sync();a.record('解除分区滤镜联动')

    def reset_color(self):
        layer=self.layer();a=self.app
        if layer is None or a.busy:return
        a.commit_edit('重置局部调色前')
        geometry={key:layer['parameters'][key] for key in ('feather','expand','opacity','edge_protect') if key in layer['parameters']}
        layer['parameters']=dict(LOCAL_DEFAULTS,**geometry)
        for key in ('color_recipe','color_preparation','filter_link'):layer.pop(key,None)
        a.sync_layers();self.last_signature=None;self.sync();a.refresh();a.record('重置当前蒙版调色')
        a.status.set('当前蒙版调色已重置，保留范围、边缘修正和不透明度。')
    def select(self,e=None):
        a=self.app
        if a.busy:return
        a.commit_edit('切换局部蒙版前');a.active_layer=self.layers.current();a.sync_layers();self.update_view();self.sync()
    def update_view(self):
        a=self.app;a._local_mask_view=self.mask_view.get();a.mask_overlay.set(self.mask_view.get()!='仅看成片')
        self.workbench.compare.set('当前效果');self.workbench.clipping.set(False);a.draw()
    def remove_last_brush(self):
        a=self.app;layer=self.layer()
        if layer is None or a.busy or a._render_pending:return
        components=layer.get('components',[])
        index=next((i for i in range(len(components)-1,-1,-1) if components[i]['shape']['kind']=='brush'),None)
        if index is None:a.status.set('当前蒙版尚无手动笔画。');return
        a.commit_edit('移除蒙版最后一笔前');components.pop(index)
        a.parameter_apply(a.refresh);a.commit_edit('移除蒙版最后一笔');self.last_signature=None;self.sync();self.update_view()
    def new(self):
        a=self.app
        if not a.document or a.busy or len(a.region_layers)>=MAX_LAYERS:return
        a.commit_edit('新建局部蒙版前');h,w=a.document.rgb.shape[:2]
        a.region_layers.append(dict(name='局部调色 '+str(len(a.region_layers)+1),enabled=True,mask=np.ones((h,w),bool),parameters=dict(LOCAL_DEFAULTS),color_process=2,components=[],component_base=False))
        a.active_layer=len(a.region_layers)-1;a.sync_layers();a.mask_overlay.set(True);self.sync();a.draw()
    def delete(self):
        self.app.delete_layer();self.sync()
    def remove_component(self):
        if self.app.busy:return
        layer=self.layer();i=self.components.current()
        if not layer or not 0<=i<len(layer.get('components',[])):return
        self.app.commit_edit('删除蒙版组件前');layer['components'].pop(i);self.app.parameter_apply(self.app.refresh);self.sync()
    def invert_component(self):
        if self.app.busy:return
        layer=self.layer();i=self.components.current()
        if not layer or not 0<=i<len(layer.get('components',[])):return
        self.app.commit_edit('反转蒙版组件前');item=layer['components'][i];item['invert']=not item.get('invert',False);self.app.parameter_apply(self.app.refresh);self.app.commit_edit('反转蒙版组件')
    def arm(self):
        if self.app.busy:return
        if self.app.mode.get()=='develop_component':self.app.toggle_tool('develop_component');return
        if self.layer() is None:self.new()
        layer=self.layer()
        if layer is None:return
        if len(layer.get('components',[]))>=MAX_COMPONENTS:self.app.status.set(f'每个蒙版最多{MAX_COMPONENTS}个组件。');return
        if self.kind.get()=='亮度范围':
            if self.low.get()>=self.high.get():self.app.status.set('亮度下界需小于上界。');return
            self.add(dict(kind='luminance',low=self.low.get(),high=self.high.get(),softness=self.soft.get()));return
        self.app.toggle_tool('develop_component')
        if self.app.mode.get()=='develop_component':self.app.status.set('在照片上'+('点击取色' if self.kind.get()=='颜色范围' else '拖动绘制'+self.kind.get())+'；再次点击按钮退出。')
    def activate_brush(self,operation):
        a=self.app
        if a.busy or a._render_pending:return
        if self.layer() is None:self.new()
        if self.layer() is None:return
        if len(self.layer().get('components',[]))>=MAX_COMPONENTS:a.status.set(f'每个蒙版最多{MAX_COMPONENTS}个组件，请删除不需要的组件。');return
        self.kind.set('软画笔');self.operation.set(operation);a.select_tool('develop_component');a.mask_overlay.set(True)
        if not self.brush_settings.opened:self.brush_settings.toggle()
        a.status.set(operation+'当前蒙版：原图像素笔刷；右键临时擦除，空格平移，Ctrl＋滚轮缩放。');a.draw()
    def add(self,shape,operation=None):
        if self.app.busy:return
        a=self.app;layer=self.layer()
        if layer is None:return
        if len(layer.get('components',[]))>=MAX_COMPONENTS:a.status.set(f'每个蒙版最多{MAX_COMPONENTS}个组件，请删除不需要的组件。');return
        operation=operation or {'添加':'add','减去':'subtract','交集':'intersect'}[self.operation.get()]
        a.commit_edit('添加蒙版组件前');layer.setdefault('components',[]).append(dict(operation=operation,shape=shape))
        from local_develop import checked
        checked(layer);a.parameter_apply(a.refresh);a.sync_layers();a.commit_edit('添加蒙版组件');self.sync();self.update_view()
    def norm(self,e):
        a=self.app;h,w=a.document.rgb.shape[:2];return np.round(a.original_point(a.point(e))/[max(1,w-1),max(1,h-1)],6).tolist()
    def press(self,e,erase=False):
        a=self.app;layer=self.layer()
        if a.busy or a._render_pending or layer is None:return False
        if a.mode.get()=='pan':
            for shape in self.gradients():
                for key in ('start','end'):
                    xy=source_screen(a,shape[key])
                    if np.hypot(e.x-xy[0],e.y-xy[1])<dp(a.root,12):
                        a.commit_edit('渐变端点调整前');self.drag=dict(kind='handle',shape=shape,key=key);a.drag={'mode':'develop_pin'};return True
            return False
        if a.mode.get()!='develop_component':return False
        if self.kind.get()=='颜色范围':
            import color_science as cs
            x,y=np.rint(a.original_point(a.point(e))).astype(int);source=a.color_input;h,w=source.shape[:2]
            if not 0<=x<w or not 0<=y<h:return True
            lab=cs.oklab(cs.decode(source[y,x]/255));sample=dict(hue=float(np.rad2deg(np.arctan2(lab[2],lab[1]))%360),chroma=float(np.linalg.norm(lab[1:])),lightness=float(max(0,lab[0])))
            from develop_settings import checked_points
            self.add(dict(kind='color',sample=checked_points([sample])[0]));return True
        a.commit_edit('绘制蒙版组件前');self.drag=dict(kind=self.kind.get(),start=self.norm(e),points=[self.norm(e)],operation='subtract' if erase else {'添加':'add','减去':'subtract','交集':'intersect'}[self.operation.get()]);a.drag={'mode':'develop_component'};return True
    def motion(self,e):
        if not self.drag:return False
        a=self.app;d=self.drag;p=self.norm(e)
        if d['kind']=='handle':d['shape'][d['key']]=p
        elif d['kind']=='软画笔':
            h,w=a.document.rgb.shape[:2];distance=np.linalg.norm((np.array(p)-d['points'][-1])*[max(1,w-1),max(1,h-1)])
            if len(d['points'])<4096 and distance>max(.25,min(1,self.radius.get()*.25)):d['points'].append(p)
        else:d['end']=p
        a.draw();return True
    def release(self,e):
        if not self.drag:return False
        self.motion(e);d=self.drag;self.drag=None;self.app.drag=None
        if d['kind']=='handle':
            from local_develop import checked
            try:checked(self.layer())
            except ValueError:self.app.undo();return True
            self.app.parameter_apply(self.app.refresh);self.app.commit_edit('调整渐变端点')
        elif d['kind']=='软画笔':self.add(dict(kind='brush',points=d['points'],radius=self.radius.get()/max(self.app.document.rgb.shape[:2]),feather=self.feather.get(),flow=self.flow.get(),density=self.density.get()),d['operation'])
        else:
            end=d.get('end',d['start'])
            if np.linalg.norm(np.array(end)-d['start'])>.001:self.add(dict(kind='linear' if d['kind']=='线性渐变' else 'radial',start=d['start'],end=end,invert=False))
        return True
    def gradients(self):
        layer=self.layer()
        if not layer:return []
        shapes=[layer['gradient']] if layer.get('gradient') else []
        return shapes+[c['shape'] for c in layer.get('components',[]) if c['shape']['kind'] in ('linear','radial')]
    def draw_handles(self):
        a=self.app;c=a.canvas;c.delete('workbench_pins')
        if not self.workbench.active or self.workbench.page!='蒙版' or not a.document:return
        if a.mode.get()=='develop_component' and self.kind.get()=='软画笔' and a.pointer:
            x,y=a.pointer;radius=self.radius.get()*a.view.scale
            c.delete('tool_cursor');c.create_oval(x-radius,y-radius,x+radius,y+radius,outline=COLORS['accent'],width=1,tags='workbench_pins')
        for shape in self.gradients():
            start=source_screen(a,shape['start']);end=source_screen(a,shape['end'])
            c.create_line(*start,*end,fill=COLORS['accent'],width=2,tags='workbench_pins')
            for p in (start,end):c.create_oval(p[0]-5,p[1]-5,p[0]+5,p[1]+5,fill='white',outline=COLORS['accent'],width=2,tags='workbench_pins')
        if self.drag and self.drag['kind']!='handle':
            points=[source_screen(a,p) for p in self.drag.get('points',[self.drag['start']])]
            if 'end' in self.drag:points.append(source_screen(a,self.drag['end']))
            if len(points)>1:c.create_line(*np.array(points).ravel().tolist(),fill=COLORS['accent'],width=2,tags='workbench_pins')
