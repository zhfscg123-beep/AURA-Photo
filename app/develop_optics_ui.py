"""Measured lens profiles and manual geometry controls; no guessed calibration."""
import tkinter as tk
from tkinter import ttk
from dark_ui import Section
import develop_optics as optics

class DevelopOpticsUI:
    def init_develop_optics(self):
        self.optics_vars={k:tk.DoubleVar(value=d) for k,_,_,_,d in optics.CONTROLS}
        self.optics_enabled=tk.BooleanVar(value=False);self.optics_constrain=tk.BooleanVar(value=True);self.optics_profile=tk.StringVar(value='')
        self.optics_note=tk.StringVar(value='新导入 RAW 自动启用唯一匹配的镜头配置；也可手动选择。')
    def build_develop_optics(self,body):
        lens=Section(body,'镜头校正',opened=False);lens._feature_scope='optics_lens';self.develop_sections['lens']=lens
        check=ttk.Checkbutton(lens.body,text='启用镜头配置校正',variable=self.optics_enabled,command=self.optics_changed);check.pack(anchor='w');self.controls.append(check)
        self.button(lens.body,'按相机与镜头信息匹配',self.match_optics_profile)
        self.optics_combo=ttk.Combobox(lens.body,textvariable=self.optics_profile,state='readonly');self.optics_combo.pack(fill='x');self.optics_combo.bind('<<ComboboxSelected>>',lambda e:self.optics_changed());self.controls.append(self.optics_combo)
        self.button(lens.body,'载入镜头配置列表',self.load_optics_list)
        for key in ('crop_factor','focal','aperture','distortion','lens_vignette','ca_red','ca_blue','defringe'):self.optics_slider(lens.body,key)
        ttk.Label(lens.body,textvariable=self.optics_note,style='Muted.TLabel',wraplength=270).pack(fill='x')
        transform=Section(body,'变换 · 透视与水平',opened=False);transform._feature_scope='optics_transform';self.develop_sections['transform']=transform
        for key in ('vertical','horizontal','rotation','aspect','scale','shift_x','shift_y'):self.optics_slider(transform.body,key)
        check=ttk.Checkbutton(transform.body,text='约束边缘 · 自动缩放避免黑边',variable=self.optics_constrain,command=self.optics_changed);check.pack(anchor='w');self.controls.append(check)
        self.button(transform.body,'自动水平',self.auto_level_optics)
        for title,mode in [('自动垂直校正','vertical'),('自动完整透视','full')]:self.button(transform.body,title,lambda m=mode:self.auto_upright(m))
        self.guide_axis=tk.StringVar(value='垂直线');combo=ttk.Combobox(transform.body,textvariable=self.guide_axis,values=['垂直线','水平线'],state='readonly');combo.pack(fill='x');self.controls.append(combo)
        self.mode_button(transform.body,'在照片上绘制引导线','develop_guide')
        self.button(transform.body,'应用引导线校正',self.apply_guided_upright)
        self.button(transform.body,'清除引导与自动透视',self.clear_upright)
    def optics_slider(self,parent,key):
        k,title,lo,hi,_=next(row for row in optics.CONTROLS if row[0]==key)
        return self.slider(parent,title,self.optics_vars[k],lo,hi,self.optics_changed,decimals=2 if key in ('rotation','crop_factor','aperture') else 0)
    def sync_develop_optics(self):
        v=optics.checked(self.workflow_extensions.get('optics',{}));self.optics_enabled.set(v['enabled']);self.optics_constrain.set(v['constrain']);self.optics_profile.set(v['profile'])
        for k,var in self.optics_vars.items():var.set(v[k])
        if v['profile']:
            self.optics_combo.configure(values=[v['profile']]);self.optics_note.set(('已启用：' if v['enabled'] else '已选择，校正关闭：')+v['profile'])
        elif self.document and self.document.is_raw:self.optics_note.set('未找到唯一匹配的镜头配置；可载入列表选择实际镜头。')
    def optics_changed(self):
        if self.loading_creative:return
        if self.optics_enabled.get() and not self.optics_profile.get():self.optics_note.set('请先匹配或选择镜头配置。');self.optics_enabled.set(False);return
        self.commit_edit('镜头与变换前');v={k:var.get() for k,var in self.optics_vars.items()};v.update(enabled=self.optics_enabled.get(),profile=self.optics_profile.get(),constrain=self.optics_constrain.get())
        self.workflow_extensions['optics']=optics.checked(v);self.parameter_apply(self.refresh);self.record('镜头与透视变换')
    def load_optics_list(self):
        from lens_profiles import registry
        self.optics_combo.configure(values=sorted(registry()[0]));self.optics_note.set('已载入实测镜头列表；请选择实际使用的镜头。')
    def match_optics_profile(self):
        if self.document is None:return
        from lens_profiles import match
        profile,crop=match(self.document.metadata)
        if not profile:self.load_optics_list();self.optics_note.set('没有唯一匹配的配置，请手动选择实际镜头。');return
        self.optics_combo.configure(values=[profile]);self.optics_profile.set(profile)
        if crop:self.optics_vars['crop_factor'].set(crop)
        self.optics_vars['focal'].set(self.document.metadata.get('focal_length',50) or 50);self.optics_vars['aperture'].set(self.document.metadata.get('aperture',5.6) or 5.6)
        self.optics_enabled.set(True);self.optics_changed();self.optics_note.set('已匹配：'+profile)
    def auto_level_optics(self):
        if self.output is None:return
        import cv2,numpy as np
        image=self.output;scale=min(1,1400/max(image.shape[:2]));small=cv2.resize(image,None,fx=scale,fy=scale)
        edges=cv2.Canny(cv2.cvtColor(small,cv2.COLOR_RGB2GRAY),70,150);lines=cv2.HoughLinesP(edges,1,np.pi/1800,100,minLineLength=max(40,small.shape[1]//5),maxLineGap=15)
        angles=[]
        if lines is not None:
            for x,y,a,b in np.asarray(lines).reshape(-1,4):
                angle=np.rad2deg(np.arctan2(b-y,a-x));angle=(angle+90)%180-90
                if abs(angle)<10:angles.append(angle)
        if len(angles)<2:self.optics_note.set('未检测到足够可靠的水平线，请手动调整。');return
        self.optics_vars['rotation'].set(-float(np.median(angles)));self.optics_changed()

    def auto_upright(self,mode):
        if self.output is None or self.busy:return
        from optics_analysis import analyze
        try:result=analyze(self.color_input if self.color_input is not None else self.output,mode)
        except ValueError as e:self.optics_note.set(str(e));return
        self.commit_edit('自动透视前');value=optics.checked(self.workflow_extensions.get('optics',{}));value.update(result,upright_mode=mode)
        self.workflow_extensions['optics']=optics.checked(value);self.sync_develop_optics();self.parameter_apply(self.refresh);self.record('自动透视校正')

    def apply_guided_upright(self):
        from optics_analysis import rectify
        value=optics.checked(self.workflow_extensions.get('optics',{}))
        try:matrix=rectify(value['guides'],'full' if len([g for g in value['guides'] if g['axis']=='horizontal'])>=2 else 'vertical')
        except ValueError as e:self.optics_note.set(str(e));return
        self.commit_edit('引导透视前');value.update(homography=matrix,upright_mode='guided');self.workflow_extensions['optics']=optics.checked(value);self.parameter_apply(self.refresh);self.record('引导透视校正')

    def clear_upright(self):
        self.commit_edit('清除透视前');value=optics.checked(self.workflow_extensions.get('optics',{}));value.update(homography=optics.DEFAULTS['homography'],guides=[],upright_mode='off');self.workflow_extensions['optics']=value;self.parameter_apply(self.refresh)
