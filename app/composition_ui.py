"""Visible export crop guides, precise numeric framing and preview."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image,ImageTk
from dark_ui import Section
from dpi_support import dp
from photo_document import to_uint8
from batch_workflow import resize_output
import composition

class CompositionUI:
    def init_composition(self):
        self.crop_ratio=tk.StringVar(value='原始');self.crop_lock=tk.BooleanVar(value=True)
        self.crop_vars={k:tk.DoubleVar(value=v) for k,v in composition.DEFAULTS.items() if k not in ('ratio','quarter','locked')}
        self.crop_quarter=tk.StringVar(value='0°');self.crop_overlay=tk.BooleanVar(value=False);self.loading_crop=False
    def build_composition_panel(self,panel):
        section=Section(panel,'导出构图与水平校正',opened=False);self.composition_panel=section;body=section.body
        ttk.Checkbutton(body,text='显示构图辅助线',variable=self.crop_overlay,command=self.draw).pack(anchor='w',pady=5)
        c=ttk.Combobox(body,textvariable=self.crop_ratio,values=list(composition.RATIOS),state='readonly');c.pack(fill='x');c.bind('<<ComboboxSelected>>',lambda e:self.choose_crop_ratio())
        self.crop_lock_button=ttk.Checkbutton(body,text='固定比例 · 关闭后可自由裁剪',variable=self.crop_lock,command=self.toggle_crop_lock)
        self.crop_lock_button.pack(anchor='w',pady=6)
        self.crop_angle_control=self.slider(body,'角度',self.crop_vars['rotation'],-180,180,self.composition_changed,decimals=2)
        self.crop_angle_control.preview_command=self.preview_crop_angle
        self.register_mode_button(self.button(body,'拉线校正水平',self.start_crop_straighten),'crop_straighten')
        self.button(body,'重置裁剪与角度',self.reset_composition)
        self.button(body,'恢复完整画幅（保留修复）',self.reset_composition)
        self.button(body,'恢复机内构图',self.restore_camera_composition)
        ttk.Label(body,text='拖动边角裁剪，框内移动，框外拖动自由旋转；角度可输入两位小数。拉线校正：沿画面中的水平参考线拖动。关闭固定比例可自由调整宽高。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
    def start_crop_straighten(self):
        if self.busy:return
        on=self.crop_straighten;self.select_tool('pan')
        if on:self.status.set('已退出拉线校正，返回浏览；已有修改保留。');return
        self.crop_straighten=True;self.sync_tools();self.status.set('在画面中沿水平参考线拖动，松开完成校正；再次点击按钮取消。')
    def preview_crop_angle(self):
        self.store_composition();self.draw()
    def choose_crop_ratio(self):
        self.crop_lock.set(True);self.composition_changed()
    def toggle_crop_lock(self):
        if self.loading_crop:return
        self.commit_edit('裁剪比例切换前')
        old=composition.checked(self.workflow_extensions.get('composition',{}))
        if getattr(self,'crop_image_box',None) and getattr(self,'active_category',None)=='构图':
            _,_,w,h=self.crop_image_box
        elif self.output is not None:
            h,w=composition.oriented(self.output,old).shape[:2]
        else:
            self.composition_changed();return
        a,b,c,d=composition.rectangle(w,h,old,composition.original_aspect(self.output.shape,old))
        if self.crop_lock.get():
            self.crop_ratio.set('自定义');self.crop_vars['custom_ratio'].set((c-a)/(d-b))
            ratio=(c-a)/(d-b);mw,mh=(w,w/ratio) if w/h<ratio else (h*ratio,h)
            self.crop_vars['size'].set(float(np.clip((c-a)/mw*100,1,100)))
        else:
            self.crop_vars['width'].set((c-a)/w*100);self.crop_vars['height'].set((d-b)/h*100);self.crop_vars['size'].set(100.)
        self.composition_changed()
    def composition_changed(self):
        if self.loading_crop:return
        self.store_composition()
        self.draw();self.record('构图设置')
    def store_composition(self):
        self.workflow_extensions['composition']=composition.checked(dict(ratio=self.crop_ratio.get(),locked=self.crop_lock.get(),quarter=int(self.crop_quarter.get()[:-1])//90,**{k:v.get() for k,v in self.crop_vars.items()}))
    def sync_composition_ui(self):
        if not hasattr(self,'crop_vars'):return
        v=composition.checked(self.workflow_extensions.get('composition',{}));self.loading_crop=True
        try:
            self.crop_ratio.set(v['ratio']);self.crop_lock.set(v['locked']);self.crop_quarter.set(str(v['quarter']*90)+'°')
            for k,var in self.crop_vars.items():var.set(v[k])
        finally:self.loading_crop=False
    def prepare_export_image(self,image):
        from gpu_render import execute_pixel
        try:return execute_pixel(composition.apply,image,self.workflow_extensions.get('composition',{}),host_result=True)
        except Exception as error:
            from gpu_render import record_cpu_recovery
            record_cpu_recovery('导出构图',error);return composition.apply(image,self.workflow_extensions.get('composition',{}))
    def frame_person(self):
        if not self.session or not self.session.faces:return
        f=self.session.faces[self.active_face];point=(np.asarray(f.box[:2])+f.box[2:])/2;h,w=self.document.rgb.shape[:2]
        self.crop_vars['center_x'].set(np.clip(point[0]/w*100,0,100));self.crop_vars['center_y'].set(np.clip(point[1]/h*100,0,100));self.composition_changed()
    def reset_composition(self):self.workflow_extensions.pop('composition',None);self.sync_composition_ui();self.fit();self.record('恢复完整画幅，修复与蒙版保留')
    def restore_camera_composition(self):
        if not self.document or not self.document.metadata.get('camera_crop_box'):return
        self.workflow_extensions['composition']=composition.camera_frame(self.document.rgb.shape,self.document.metadata['camera_crop_box']);self.sync_composition_ui();self.fit();self.record('恢复机内构图')
    def draw_camera_frame(self):
        self.canvas.delete('camera_frame')
        if not self.document or not self.document.metadata.get('camera_crop_composition') or self.output is None or getattr(self,'active_category',None)=='构图':return
        v=composition.checked(self.workflow_extensions.get('composition',{}))
        if v==composition.DEFAULTS or v['rotation'] or v['quarter']:return
        h,w=self.output.shape[:2];a,b,c,d=composition.rectangle(w,h,v);cw,ch=self.size()
        x,y=self.view.to_canvas(a,b,(cw,ch));z,t=self.view.to_canvas(c,d,(cw,ch));x,z=np.clip([x,z],0,cw);y,t=np.clip([y,t],0,ch)
        color=self.canvas.cget('background')
        for box in ((0,0,cw,y),(0,t,cw,ch),(0,y,x,t),(z,y,cw,t)):
            self.canvas.create_rectangle(*box,fill=color,outline=color,tags='camera_frame')
    def draw_composition_guides(self):
        self.canvas.delete('composition_guides')
        if self.output is None or not self.crop_overlay.get() or self.mode.get()!='pan':return
        v=composition.checked(self.workflow_extensions.get('composition',{}))
        if v==composition.DEFAULTS or v['quarter'] or v['rotation']:return
        h,w=self.output.shape[:2];a,b,c,d=composition.rectangle(w,h,v);x,y=self.view.to_canvas(a,b,self.size());z,t=self.view.to_canvas(c,d,self.size())
        self.canvas.create_rectangle(x,y,z,t,outline='#ffffff',width=dp(self.root,2),tags='composition_guides')
        for fraction in (1/3,2/3):
            self.canvas.create_line(x+(z-x)*fraction,y,x+(z-x)*fraction,t,fill='#ffffff',dash=(3,3),tags='composition_guides')
            self.canvas.create_line(x,y+(t-y)*fraction,z,y+(t-y)*fraction,fill='#ffffff',dash=(3,3),tags='composition_guides')
    def preview_composition(self):
        if self.output_float is None or self.busy:return
        image=self.output_float.copy();data=dict(self.workflow_extensions.get('composition',{}))
        def job():return to_uint8(resize_output(composition.apply(image,data),1200))
        def ready(pixels):
            window=tk.Toplevel(self.root);window.title('实际导出构图预览');window.transient(self.root)
            photo=ImageTk.PhotoImage(Image.fromarray(pixels),master=window);label=ttk.Label(window,image=photo);label.image=photo;label.pack()
            ttk.Label(window,text='预览已缩小；正式导出使用完整分辨率。',padding=10).pack();ttk.Button(window,text='关闭',command=window.destroy).pack(pady=8)
        self.work(job,ready)
