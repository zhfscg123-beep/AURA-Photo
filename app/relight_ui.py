"""Existing Tk style, explicit per-person light selection and folded controls."""
import copy,tkinter as tk
from tkinter import ttk,messagebox
from dark_ui import Section
import relight_settings as settings

class RelightUI:
    def init_relight_ui(self):
        self.relight_master=tk.BooleanVar(value=False);self.relight_on=tk.BooleanVar(value=True)
        self.relight_occlusion=tk.BooleanVar(value=True)
        self.relight_choice=tk.StringVar();self.relight_kind=tk.StringVar(value='柔面光');self.relight_scope=tk.StringVar(value='面部与身体皮肤')
        self.relight_vars={key:tk.DoubleVar(value=settings.DEFAULTS[key]) for key in settings.LIMITS}
        self.relight_rgb=[tk.DoubleVar(value=255) for _ in range(3)];self.light_note=tk.StringVar(value='开启后在后台分析深度与表面方向；调灯复用缓存。')
        self.relight_loading=False;self.relight_legacy=False;self._relight_index=0
        self._relight_combos=[]

    def build_relight_panel(self,panel):
        section=Section(panel,'几何柔光 · 当前人物',opened=False);section._feature_scope='relight';self.light_panel=section
        body=section.body
        master=ttk.Checkbutton(body,text='启用几何补光',variable=self.relight_master,command=lambda:self.parameter_apply(self.relight_changed));master.pack(anchor='w',pady=4);self.controls.append(master)
        row=ttk.Frame(body);row.pack(fill='x',pady=4)
        self.relight_selector=ttk.Combobox(row,textvariable=self.relight_choice,state='readonly',width=16);self.relight_selector.pack(side='left',fill='x',expand=True)
        self.relight_selector._aura_search_name='选择人物光源';self.relight_selector.bind('<<ComboboxSelected>>',self.relight_selected)
        self.controls.append(self.relight_selector)
        self._relight_combos.append(self.relight_selector)
        add=ttk.Button(row,text='添加',width=5,command=self.relight_add);add.pack(side='left',padx=3);self.controls.append(add)
        delete=ttk.Button(row,text='删除',width=5,command=self.relight_remove);delete.pack(side='left');self.controls.append(delete)
        self.relight_selector.configure(values=['1 · 主光','2 · 补光','3 · 轮廓光']);self.relight_choice.set('1 · 主光')
        enabled=ttk.Checkbutton(body,text='开启此光源',variable=self.relight_on,command=lambda:self.parameter_apply(self.relight_changed));enabled.pack(anchor='w');self.controls.append(enabled)
        for label,var,choices,callback in [('光源类型',self.relight_kind,list(settings.TYPES),self.relight_type_changed),
            ('作用范围',self.relight_scope,list(settings.SCOPES),lambda e:self.parameter_apply(self.relight_changed))]:
            ttk.Label(body,text=label,style='Muted.TLabel').pack(anchor='w',pady=(5,2))
            c=ttk.Combobox(body,textvariable=var,values=choices,state='readonly');c.pack(fill='x');c._aura_search_name=label;c.bind('<<ComboboxSelected>>',callback)
            self.controls.append(c)
            self._relight_combos.append(c)
        for key,title,lo,hi,decimals in [('power','强度',0,20,2),('softness','柔和程度',0,100,0)]:self.slider(body,title,self.relight_vars[key],lo,hi,self.relight_changed,decimals=decimals)
        palette=ttk.Frame(body);palette.pack(fill='x',pady=5)
        self.relight_color_button=tk.Button(palette,text='灯光颜色 #FFFFFF',relief='flat',command=self.pick_relight_color);self.relight_color_button.pack(fill='x')
        self.controls.append(self.relight_color_button)
        for var in self.relight_rgb:var.trace_add('write',lambda *_:self.update_relight_chip())
        for key,title,lo,hi,decimals in [('temperature','冷暖',-100,100,0),('tint','绿／洋红',-100,100,0),('saturation','灯色饱和度',0,1,2),('color_mix','灯色混合',0,1,2)]:self.slider(body,title,self.relight_vars[key],lo,hi,self.relight_changed,decimals=decimals)
        position=Section(body,'灯位与范围',opened=False);position._feature_scope='relight_position'
        for key,title in [('x','横向位置'),('y','纵向位置'),('z','前后深度')]:self.slider(position.body,title,self.relight_vars[key],-3,3,self.relight_changed,decimals=2)
        self.mode_button(position.body,'在照片上放置此光源','creative_light')
        self.button(position.body,'结束放置 · 返回浏览',lambda:self.select_tool('pan'))
        self.slider(position.body,'灯面大小',self.relight_vars['size'],.01,2,self.relight_changed,decimals=2)
        ttk.Label(position.body,text='正深度在人物前方，负深度在背后；点选位置保持原图坐标。',style='Muted.TLabel',wraplength=270).pack(anchor='w',pady=5)
        material=Section(body,'高光与五官受光',opened=False);material._feature_scope='relight_material'
        for key,title,lo,hi in [('specular_strength','新增高光',0,1),('roughness','高光柔度',.12,1),('diffuse_wrap','侧面填光',0,.5),('lip_receive','嘴唇受光',0,1),('brow_receive','眉毛受光',0,1),('rim_gain','轮廓光量',0,5),('rim_width','轮廓宽度',.002,.2)]:self.slider(material.body,title,self.relight_vars[key],lo,hi,self.relight_changed,decimals=3 if key=='rim_width' else 2)
        protection=Section(body,'暗部、高光与几何保护',opened=False);protection._feature_scope='relight_protection'
        for key,title in [('shadow_priority','暗部优先'),('highlight_protect','亮部／肤色保护'),('geometry_protect','几何可靠性保护')]:self.slider(protection.body,title,self.relight_vars[key],0,1,self.relight_changed,decimals=2)
        occlusion=ttk.Checkbutton(protection.body,text='使用可见深度遮挡',variable=self.relight_occlusion,command=lambda:self.parameter_apply(self.relight_changed));occlusion.pack(anchor='w',pady=4);self.controls.append(occlusion)
        ttk.Label(protection.body,text='保护只调整新增光量，不更换强度曲线。遮挡依据可见深度，不能恢复背面或消除原图阴影。',style='Muted.TLabel',wraplength=270).pack(anchor='w',pady=5)
        ttk.Label(body,textvariable=self.light_note,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        ttk.Label(body,text='最多五盏灯。嘴唇和眉毛连续受光，眼球与鼻孔保持保护。柔化新增光照，原图已有阴影仍保留。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=4)
        self.update_relight_chip()

    def _rig_for_ui(self):
        item=self.workflow_extensions.get('people',{}).get(str(self.active_face),{})
        return settings.checked(item.get('relight'))

    def enable(self):
        super().enable()
        ready=getattr(self,'document',None) is not None and not getattr(self,'busy',False)
        for c in getattr(self,'_relight_combos',[]):c.configure(state='readonly' if ready else 'disabled')

    def sync_relight_ui(self):
        if not hasattr(self,'relight_master'):return
        self.relight_loading=True
        try:
            item=self.workflow_extensions.get('people',{}).get(str(self.active_face),{})
            self.relight_legacy='relight' not in item and bool(item.get('light',0))
            rig=settings.from_legacy(item) if self.relight_legacy else settings.checked(item.get('relight'))
            if self.relight_legacy:
                rig['enabled']=False
                self.light_note.set('旧项目减光记录保留；几何补光添加光照，减光请用全局曝光。' if item.get('light',0)<0 else '旧项目保留原补光；开启或编辑几何补光时转换，可撤销。')
            self._relight_index=rig['selected'];values=[f'{i+1} · {v["name"]}' for i,v in enumerate(rig['lights'])]
            self.relight_selector.configure(values=values);self.relight_choice.set(values[rig['selected']])
            self.relight_master.set(rig['enabled']);lamp=rig['lights'][rig['selected']]
            self.relight_on.set(lamp['enabled']);self.relight_kind.set(settings.TYPE_LABELS[lamp['type']]);self.relight_scope.set(settings.SCOPE_LABELS[lamp['scope']])
            self.relight_occlusion.set(lamp['occlusion'])
            for key,var in self.relight_vars.items():var.set(lamp[key])
            for var,v in zip(self.relight_rgb,lamp['color']):var.set(v)
        finally:self.relight_loading=False

    def relight_selected(self,event=None):
        if self.relight_loading:return
        index=self.relight_selector.current()
        if index<0:return
        item=self.scene_person()
        if 'relight' in item:item['relight']['selected']=index
        self._relight_index=index;self.relight_loading=True
        try:
            rig=settings.from_legacy(item) if self.relight_legacy else settings.checked(item.get('relight'));lamp=rig['lights'][index]
            self.relight_on.set(lamp['enabled']);self.relight_kind.set(settings.TYPE_LABELS[lamp['type']]);self.relight_scope.set(settings.SCOPE_LABELS[lamp['scope']])
            self.relight_occlusion.set(lamp['occlusion'])
            for key,var in self.relight_vars.items():var.set(lamp[key])
            for var,value in zip(self.relight_rgb,lamp['color']):var.set(value)
        finally:self.relight_loading=False

    def relight_changed(self):
        if self.relight_loading or self.loading_scene or self.busy or not self.session or not self.session.faces:return
        item=self.scene_person();rig=settings.from_legacy(item) if self.relight_legacy else settings.checked(item.get('relight'))
        if self.relight_legacy:self.relight_master.set(True)
        index=min(self._relight_index,len(rig['lights'])-1);v=rig['lights'][index]
        v.update({k:var.get() for k,var in self.relight_vars.items()});v.update(enabled=bool(self.relight_on.get()),occlusion=bool(self.relight_occlusion.get()),type=settings.TYPES[self.relight_kind.get()],scope=settings.SCOPES[self.relight_scope.get()],color=[x.get() for x in self.relight_rgb])
        if v['type']=='back' and v['z']>=0:v['z']=-max(.1,abs(v['z']));self.relight_vars['z'].set(v['z'])
        rig.update(enabled=bool(self.relight_master.get()),selected=index);item['relight']=settings.checked(rig);item['light']=0;item['box']=list(self.session.faces[self.active_face].box)
        self.relight_legacy=False;self.light_note.set('正在后台更新补光…首次开启会分析人物深度与表面方向。')
        self.parameter_apply(self.refresh);self.record('人物几何补光参数')

    def relight_type_changed(self,event=None):
        if self.relight_kind.get()=='后轮廓光':self.relight_vars['z'].set(-max(.1,abs(self.relight_vars['z'].get())));self.relight_scope.set('人物轮廓与衣物');self.relight_occlusion.set(False)
        elif self.relight_vars['z'].get()<0:self.relight_vars['z'].set(abs(self.relight_vars['z'].get()))
        self.parameter_apply(self.relight_changed)

    def relight_add(self):
        if self.busy or not self.session:return
        item=self.scene_person();rig=settings.from_legacy(item) if self.relight_legacy else self._rig_for_ui()
        if len(rig['lights'])>=5:self.status.set('每个人物最多五盏光源。');return
        self.commit_edit('添加光源前');rig['lights'].append(settings.lamp(len(rig['lights'])));rig['selected']=len(rig['lights'])-1
        item['relight']=rig;item['light']=0;self.sync_relight_ui();self.parameter_apply(self.refresh);self.mark_draft();self.record('添加人物光源')

    def relight_remove(self):
        if self.busy or not self.session:return
        item=self.scene_person();rig=settings.from_legacy(item) if self.relight_legacy else self._rig_for_ui()
        if len(rig['lights'])<=1:self.status.set('至少保留一盏光源；可关闭其开关。');return
        self.commit_edit('删除光源前');rig['lights'].pop(rig['selected']);rig['selected']=min(rig['selected'],len(rig['lights'])-1)
        item['relight']=rig;item['light']=0;self.sync_relight_ui();self.parameter_apply(self.refresh);self.record('删除人物光源')

    def reset_relight(self):
        if self.busy or not self.session:return
        self.commit_edit('重置补光前');self.scene_person()['relight']=settings.defaults();self.scene_person()['light']=0
        self.sync_relight_ui();self.parameter_apply(self.refresh);self.record('重置人物补光')

    def update_relight_chip(self):
        if not hasattr(self,'relight_color_button'):return
        from color_widgets import rgb_hex
        rgb=[v.get() for v in self.relight_rgb];code=rgb_hex(rgb)
        self.relight_color_button.configure(text='灯光颜色 '+code,bg=code,fg='#202b3c' if sum(rgb)>420 else 'white')

    def pick_relight_color(self):
        if self.busy:return
        from color_widgets import ColorPalette
        def apply(rgb):
            self.commit_edit('灯光调色前')
            for var,value in zip(self.relight_rgb,rgb):var.set(value)
            self.parameter_apply(self.relight_changed)
        self.color_palette=ColorPalette(self.root,[v.get() for v in self.relight_rgb],apply,'灯光颜色')

    def place_relight(self,event):
        if not self.session or self.busy:return
        from creative_regions import regions
        from relight_engine import person_box
        p=self.original_point(self.point(event));box=person_box(self.session,self.active_face,regions(self.session,self.region_layers)['people'][self.active_face]);a,b,c,d=box
        span=max(c-a,d-b);self.relight_vars['x'].set(max(-3,min(3,(p[0]-(a+c)/2)/span)))
        self.relight_vars['y'].set(max(-3,min(3,((b+d)/2-p[1])/span)))
        self.parameter_apply(self.relight_changed);self.select_tool('pan');self.status.set('当前光源已放置，可调整前后深度。')
