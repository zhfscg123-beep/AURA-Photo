"""Click-assisted mask completion plus feather/edge refinement."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from dark_ui import Section
from region_masks import LOCAL_DEFAULTS
from smart_selection import select,skin_constraints

class SmartMaskUI:
    def init_smart_masks(self):
        self.smart_mode=tk.StringVar(value='皮肤补全 · 当前人物');self.smart_radius=tk.DoubleVar(value=800)
    def build_smart_mask_panel(self,panel):
        section=Section(panel,'智能补选与蒙版修边',opened=False);self.smart_mask_panel=section;body=section.body
        c=ttk.Combobox(body,textvariable=self.smart_mode,values=['皮肤补全 · 当前人物','物体点选'],state='readonly');c.pack(fill='x');self.controls.append(c)
        self.controls.append(self.slider(body,'点选范围 / 原图像素',self.smart_radius,20,4000,lambda:None,mutating=False))
        row=ttk.Frame(body);row.pack(fill='x',pady=6)
        for title,mode in [('点选添加','smart_add'),('点选减去','smart_subtract')]:
            b=ttk.Button(row,text=title,command=lambda m=mode:self.toggle_tool(m));b.pack(side='left',fill='x',expand=True,padx=2);self.controls.append(b);self.register_mode_button(b,mode)
        self.button(body,'将当前蒙版用于身体美颜',self.assign_body_mask)
        ttk.Label(body,text='先选部位蒙版，再点击遗漏区域；没有蒙版时自动新建。结合人物范围、颜色和边缘补选；复杂纹理可用添加/减去画笔修正。扩展、羽化与强度在部位蒙版面板。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
    def click_smart_mask(self,event,erase=False):
        if self.shape_pending():self.status.set('请等待形变完成再点选。');return
        if self.form_changed is not None and self.form_changed.any():self.status.set('请先关闭实验身体形变再点选。');return
        person=self.active_face;skin=self.smart_mode.get().startswith('皮肤');session=self.session
        if skin and not session.faces:self.status.set('请先识别人物，或切换物体点选。');return
        point=self.original_point(self.point(event));radius=float(self.smart_radius.get());mode=self.mode.get();layer=self.active_layer
        from region_masks import MAX_LAYERS
        if not 0<=layer<len(self.region_layers) and len(self.region_layers)>=MAX_LAYERS:self.status.set('蒙版数量已达上限，请先删除不需要的蒙版。');return
        self.commit_edit('智能补选前')
        def job():
            allowed,veto=skin_constraints(session,person) if skin else (None,None)
            return select(session.original,point,radius,'skin' if skin else 'object',allowed,veto)
        def ready(mask):
            if not 0<=layer<len(self.region_layers):
                self.region_layers.append(dict(name=f'智能选区 · 人像 {person+1}' if skin else '智能物体选区',mask=np.zeros_like(mask),parameters=dict(LOCAL_DEFAULTS),enabled=True))
                self.active_layer=len(self.region_layers)-1
            else:self.active_layer=layer
            target=self.region_layers[self.active_layer]['mask']
            if (mode=='smart_subtract')!=erase:target &= ~mask
            else:target |= mask
            self.mask_overlay.set(True);self.overlay.set(False);self.sync_layers();self.refresh();self.record('智能点选补全' if mode=='smart_add' else '智能点选减去')
        self.work(job,ready)
    def assign_body_mask(self):
        if self.busy or not self.session.faces or not 0<=self.active_layer<len(self.region_layers):return
        layer=self.region_layers[self.active_layer];layer['feature_key']='body_skin';layer['person_index']=self.active_face
        self.refresh();self.record('应用为当前人物身体美颜范围');self.status.set('当前蒙版已用于此人物身体参数；请检查范围，避免包含衣服、脸部或其他人物。')
