"""Composable regional-mask panel and manual add/subtract, independent of acne selection."""
import copy,tkinter as tk
from tkinter import ttk
import cv2,numpy as np
from dark_ui import Section,ToolButton
from region_masks import PARTS,LOCAL_DEFAULTS,LOCAL_RANGES,MAX_LAYERS,part_mask
from local_develop_ui import LocalDevelopUI

class RegionMaskUI(LocalDevelopUI):
    def init_masks(self):
        self.region_layers=[];self.active_layer=-1;self.loading_layer=False
        self.part_checks={k:tk.BooleanVar(value=k=='skin') for k in PARTS}
        self.layer_vars={k:tk.DoubleVar(value=v) for k,v in LOCAL_DEFAULTS.items()}
        self.init_local_develop()
        self.layer_name=tk.StringVar(value='尚未生成部位蒙版');self.layer_enabled=tk.BooleanVar(value=True)
        self.mask_overlay=tk.BooleanVar(value=False)
    def build_masks_panel(self,panel):
        section=Section(panel,'AI 部位蒙版 · 可合并 / 分别生成');self.mask_panel=section
        ttk.Label(section.body,text='所有部位均对应上方所选人像，含身体皮肤。重叠或归属不明确处可用画笔补选。蒙版独立于祛痘选区。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(0,5))
        for k,label in PARTS.items():
            b=ttk.Checkbutton(section.body,text=label,variable=self.part_checks[k]);b.pack(anchor='w');self.controls.append(b)
        row=ttk.Frame(section.body);row.pack(fill='x',pady=6)
        for label,combine in [('合并生成',True),('分别生成',False)]:
            b=ttk.Button(row,text=label,command=lambda c=combine:self.create_region_masks(c));b.pack(side='left',expand=True,fill='x',padx=2);self.controls.append(b)
        self.layer_control=ttk.Combobox(section.body,textvariable=self.layer_name,state='disabled');self.layer_control.pack(fill='x');self.layer_control.bind('<<ComboboxSelected>>',self.switch_layer)
        self.layer_control._aura_search_name='当前部位蒙版'
        row=ttk.Frame(section.body);row.pack(fill='x',pady=6)
        self.layer_toggle=ttk.Checkbutton(row,text='启用当前蒙版',variable=self.layer_enabled,command=self.layer_toggle_changed);self.layer_toggle.pack(side='left');self.controls.append(self.layer_toggle)
        ttk.Checkbutton(row,text='显示叠加',variable=self.mask_overlay,command=self.draw).pack(side='right')
        row=ttk.Frame(section.body);row.pack(fill='x')
        for label,mode in [('添加画笔','mask_add'),('减去画笔','mask_subtract')]:
            b=ToolButton(row,label,mode,lambda m=mode:self.toggle_tool(m));b.pack(side='left',padx=2);self.tool_buttons[mode]=b;self.controls.append(b)
        self.layer_radius=self.slider(section.body,'画笔半径 / 原图像素',self.radius,1,250,self.tool_size_changed)
        ttk.Label(section.body,text='Ctrl＋滚轮调画笔；空格拖动平移；Esc 返回浏览。画笔只修改当前部位蒙版。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        self.layer_sliders=[]
        for k,label in [('exposure','曝光'),('temperature','色温'),('tint','色调'),('saturation','饱和度'),('texture','纹理'),('smooth','局部柔化'),('expand','扩展 / 收缩像素'),('feather','羽化像素'),('opacity','蒙版效果强度')]:
            lo,hi=LOCAL_RANGES[k];self.layer_sliders.append(self.slider(section.body,label,self.layer_vars[k],lo,hi,self.layer_values_changed,decimals=2 if k=='exposure' else 0))
        self.layer_delete=self.button(section.body,'删除当前部位蒙版',self.delete_layer)
        self.build_local_develop(section.body)
        self.sync_layers()
    def sync_layers(self):
        self.layer_control.configure(values=[f'{i+1} · {l["name"]}' for i,l in enumerate(self.region_layers)],state='readonly' if self.region_layers and not self.busy else 'disabled')
        valid=0<=self.active_layer<len(self.region_layers)
        self.loading_layer=True
        try:
            self.layer_name.set(f'{self.active_layer+1} · {self.region_layers[self.active_layer]["name"]}' if valid else '尚未生成部位蒙版')
            self.layer_enabled.set(self.region_layers[self.active_layer].get('enabled',True) if valid else True)
            for k,v in self.layer_vars.items():v.set(self.region_layers[self.active_layer]['parameters'][k] if valid else 0)
            self.sync_local_develop()
        finally:self.loading_layer=False
        for control in self.layer_sliders+[self.layer_toggle,self.layer_delete,self.layer_radius]:control.configure(state='normal' if valid and not self.busy else 'disabled')
        for mode in ('mask_add','mask_subtract'):self.tool_buttons[mode].configure(state='normal' if valid and not self.busy else 'disabled')
    def layer_values_changed(self):
        if self.loading_layer or self.busy or not 0<=self.active_layer<len(self.region_layers):return
        layer=self.region_layers[self.active_layer]
        if layer.get('color_process',1)==1:
            extras=[k for k,_,_,_ in __import__('local_develop').EXTRA]
            if any(self.layer_vars[k].get()!=layer['parameters'].get(k,0) for k in extras):
                for k in extras:self.layer_vars[k].set(layer['parameters'].get(k,0))
                self.status.set('此为旧版局部蒙版；请先在“局部影调与细节”转换为专业调色，或新建蒙版。');return
        layer['parameters']={k:float(v.get()) for k,v in self.layer_vars.items()}
        self.parameter_apply(self.refresh)
    def layer_toggle_changed(self):
        if self.busy or not 0<=self.active_layer<len(self.region_layers):return
        self.region_layers[self.active_layer]['enabled']=bool(self.layer_enabled.get());self.refresh();self.record('切换部位蒙版开关')
    def switch_layer(self,event=None):
        if self.busy:return
        self.commit_edit('部位蒙版参数');self.active_layer=self.layer_control.current();self.sync_layers();self.draw()
    def create_region_masks(self,combine):
        if not self.session or self.busy:return
        parts=[k for k,v in self.part_checks.items() if v.get()]
        if not parts:return
        if not self.session.faces:self.status.set('未识别到可靠人脸，无法对应人物身体；请先确认人像识别。');return
        if len(self.region_layers)+(1 if combine else len(parts))>MAX_LAYERS:self.status.set(f'单图最多{MAX_LAYERS}个部位蒙版，请先删除不需要的蒙版。');return
        self.commit_edit('生成蒙版前');session=self.session;fi=self.active_face
        def job():
            self.progress('AI 正在生成部位蒙版…');return [(k,part_mask(session,fi,k)) for k in parts]
        def ready(result):
            empty=[PARTS[k] for k,m in result if not m.any()];items=[(k,m) for k,m in result if m.any()]
            if combine and items:items=[('+'.join(k for k,_ in items),np.logical_or.reduce([m for _,m in items]))]
            for k,m in items:
                name=f'人像 {fi+1} '+'＋'.join(PARTS[x] for x in k.split('+'))
                self.region_layers.append(dict(name=name,mask=m,parameters=dict(LOCAL_DEFAULTS),enabled=True,color_process=2))
            if items:self.active_layer=len(self.region_layers)-1
            self.mask_overlay.set(True);self.overlay.set(False);self.sync_layers();self.refresh();self.record('合并生成部位蒙版' if combine else '分别生成部位蒙版')
            if empty:self.status.set(self.status.get()+' / 未检出：'+'、'.join(empty))
            if 'body' in parts and fi+1 not in getattr(session,'body_assignment',{}).get('matched_people',[]):
                self.status.set(self.status.get()+' / 该人像身体归属不可靠，未生成身体蒙版。')
        self.work(job,ready)
    def delete_layer(self):
        if self.busy or not 0<=self.active_layer<len(self.region_layers):return
        del self.region_layers[self.active_layer];self.active_layer=min(self.active_layer,len(self.region_layers)-1)
        if self.active_layer<0:self.select_tool('pan')
        self.sync_layers();self.refresh();self.record('删除部位蒙版')
    def paint_layer(self,p0,p1,r,mode):
        if not 0<=self.active_layer<len(self.region_layers):return
        mask=self.region_layers[self.active_layer]['mask'];h,w=mask.shape
        x0,y0=map(lambda v:round(v),p0);x1,y1=map(lambda v:round(v),p1)
        a,b=max(0,min(x0,x1)-r-2),max(0,min(y0,y1)-r-2);c,d=min(w,max(x0,x1)+r+3),min(h,max(y0,y1)+r+3)
        if c<=a or d<=b:return
        stroke=np.zeros((d-b,c-a),np.uint8);cv2.line(stroke,(x0-a,y0-b),(x1-a,y1-b),1,r*2+1)
        for x,y in ((x0,y0),(x1,y1)):cv2.circle(stroke,(x-a,y-b),r,1,-1)
        mask[b:d,a:c][stroke>0]=mode=='mask_add'
        layer=self.region_layers[self.active_layer]
        if layer.get('mask_alpha') is not None:
            prob=layer['mask_alpha'];ph,pw=prob.shape
            x0,y0=round(x0*pw/w),round(y0*ph/h);x1,y1=round(x1*pw/w),round(y1*ph/h);radius=max(1,round(r*pw/w))
            value=255 if mode=='mask_add' else 0
            cv2.line(prob,(x0,y0),(x1,y1),value,radius*2+1)
            for x,y in ((x0,y0),(x1,y1)):cv2.circle(prob,(x,y),radius,value,-1)
