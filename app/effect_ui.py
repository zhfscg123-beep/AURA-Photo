"""Visible effect selection, local erase/restore and original-coordinate mapping."""
import copy,tkinter as tk
from tkinter import ttk
import numpy as np
from dark_ui import Section
from dpi_support import dp
import effect_controls as effects,liquify,face_reshape
from liquify_guides import sample_grid

class EffectUI:
    def init_effects(self):
        self.effect_choice=tk.StringVar(value=next(iter(effects.TITLES.values())))
        self.effect_enabled=tk.BooleanVar(value=True);self.effect_opacity=tk.DoubleVar(value=100)
        self.effect_radius=tk.DoubleVar(value=35);self.effect_overlay=tk.BooleanVar(value=True);self.loading_effect=False
    def build_effect_panel(self,panel):
        section=Section(panel,'效果管理与局部擦回',opened=False);self.effect_panel=section;body=section.body
        self.effect_list=ttk.Combobox(body,textvariable=self.effect_choice,values=list(effects.TITLES.values()),state='readonly');self.effect_list.pack(fill='x',pady=5)
        self.effect_list.bind('<<ComboboxSelected>>',lambda e:self.sync_effect_ui())
        b=ttk.Checkbutton(body,text='显示所选效果',variable=self.effect_enabled,command=self.change_effect);b.pack(anchor='w');self.controls.append(b)
        self.slider(body,'所选效果强度',self.effect_opacity,0,100,self.change_effect)
        row=ttk.Frame(body);row.pack(fill='x',pady=5)
        for title,mode in [('擦回此效果','effect_erase'),('恢复此效果','effect_restore')]:
            b=ttk.Button(row,text=title,command=lambda m=mode:self.toggle_tool(m));b.pack(side='left',expand=True,fill='x',padx=2);self.controls.append(b);self.register_mode_button(b,mode)
        self.controls.append(self.slider(body,'擦回半径 / 原图像素',self.effect_radius,1,500,self.draw_tool_cursor,mutating=False))
        ttk.Checkbutton(body,text='显示擦回区域',variable=self.effect_overlay,command=self.draw).pack(anchor='w',pady=4)
        self.button(body,'清除所选效果的擦回区域',self.clear_effect_mask)
        ttk.Label(body,text='擦回只影响所选处理阶段，保留其他调整；智能脸型和液化通过原工具恢复。画笔在原图坐标记录，可跟随已完成的面部液化。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
    def effect_key(self):return next(k for k,v in effects.TITLES.items() if v==self.effect_choice.get())
    def sync_effect_ui(self):
        if not hasattr(self,'effect_list'):return
        self.loading_effect=True
        try:
            enabled,opacity=effects.settings(self.workflow_extensions,self.effect_key())
            self.effect_enabled.set(enabled);self.effect_opacity.set(opacity*100)
        finally:self.loading_effect=False
    def change_effect(self):
        if self.loading_effect or self.busy:return
        self.workflow_extensions.setdefault('effects',{})[self.effect_key()]=dict(enabled=self.effect_enabled.get(),opacity=float(self.effect_opacity.get()))
        self.refresh();self.record('调整效果 · '+self.effect_choice.get())
    def effect_before(self,key,rgb):return effects.before(rgb,self.workflow_extensions,key)
    def effect_after(self,key,before,rgb):return effects.blend(before,rgb,self.workflow_extensions,key)
    def original_point(self,p):
        return self.original_points(np.asarray(p,np.float32)[None])[0]
    def original_points(self,p):
        # OpenCV remap has a 32767-row limit; a viewport contains many more pixels.
        if len(p)>30000:return np.concatenate([self.original_points(p[i:i+30000]) for i in range(0,len(p),30000)])
        q=np.asarray(p,np.float32).copy()
        from develop_optics import inverse_points
        q=inverse_points(q,self.document.rgb.shape,self.workflow_extensions.get('optics',{}))
        if self.liquify_active():q=q+sample_grid(self.liquify_state['flow'],q,(0,0,self.output.shape[1],self.output.shape[0]))
        if getattr(self,"photo_body_changed",False):
            import photo_body
            q=photo_body.inverse_points(q,photo_body.current_field(self.photo_body_cache))
        delta=np.zeros_like(q)
        for field in face_reshape._fields(self.reshape_cache,self.face_settings):delta+=sample_grid(field['grid'],q,field['roi'])
        q+=delta
        return q
    def start_effect_paint(self,event,erase=False):
        if self.shape_pending():self.status.set('请等待形变完成后擦回。');return
        if self.form_changed is not None and self.form_changed.any():self.status.set('请先关闭实验身体形变，再擦回效果。');return
        self.commit_edit('擦回效果前');key='erase-'+self.effect_key();p=self.original_point(self.point(event))
        mask=self.workflow_extensions.setdefault('masks',{}).setdefault(key,np.zeros(self.document.rgb.shape[:2],bool))
        self.drag=dict(mode='effect_paint',key=key,last=p,r=float(self.effect_radius.get()),erase=(self.mode.get()=='effect_erase')!=erase)
        effects.paint(mask,p,p,self.drag['r'],self.drag['erase']);self.draw()
    def update_effect_paint(self,p):
        d=self.drag;q=self.original_point(p);mask=self.workflow_extensions['masks'][d['key']]
        effects.paint(mask,d['last'],q,d['r'],d['erase']);d['last']=q;self.draw()
    def finish_effect_paint(self):
        self.drag=None;self.refresh();self.record('局部擦回 · '+self.effect_choice.get())
    def clear_effect_mask(self):
        self.workflow_extensions.setdefault('masks',{}).pop('erase-'+self.effect_key(),None);self.refresh();self.record('清除效果擦回区域')
    def decorate_display(self,rgb,bounds,localcut):
        super().decorate_display(rgb,bounds,localcut)
        if self.mode.get().startswith('effect_') and self.effect_overlay.get():
            mask=self.workflow_extensions.get('masks',{}).get('erase-'+self.effect_key())
            if mask is None:return
            shown=self.mask_for_display(mask,bounds,localcut).copy();shown[:,:localcut]=False
            rgb[shown]=np.rint(rgb[shown]*.65+np.array([80,170,245])*.35).astype(np.uint8)
