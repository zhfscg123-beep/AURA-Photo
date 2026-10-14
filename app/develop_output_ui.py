"""Output profile, display profile and soft-proof controls on the color panel."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from dark_ui import Section
import develop_output as output

class DevelopOutputUI:
    def init_develop_output(self):
        self.output_space=tk.StringVar(value='sRGB');self.output_hdr=tk.BooleanVar(value=False)
        self.proof_enabled=tk.BooleanVar(value=False);self.proof_gamut=tk.BooleanVar(value=False);self.hdr_preview=tk.BooleanVar(value=False)
        self.proof_note=tk.StringVar(value='显示预览和导出像素分别处理；软打样不写入照片。')
    def build_develop_output(self,body):
        section=Section(body,'色彩输出与软打样',opened=False);section._feature_scope='output';self.develop_sections['output']=section
        combo=ttk.Combobox(section.body,textvariable=self.output_space,values=['sRGB','AdobeRGB','ProPhoto','Rec2020'],state='readonly');combo.pack(fill='x');combo.bind('<<ComboboxSelected>>',lambda e:self.output_changed());self.controls.append(combo)
        for text,var in [('HDR 浮点TIFF输出',self.output_hdr),('SDR 高光映射预览',self.hdr_preview),('启用软打样',self.proof_enabled),('显示所选输出空间的超色域区域',self.proof_gamut)]:
            check=ttk.Checkbutton(section.body,text=text,variable=var,command=self.output_changed);check.pack(anchor='w');self.controls.append(check)
        self.button(section.body,'选择软打样 ICC',lambda:self.choose_output_profile('proof'))
        self.button(section.body,'恢复当前照片打样预览',self.reset_proof_preview)
        ttk.Label(section.body,textvariable=self.proof_note,style='Muted.TLabel',wraplength=270).pack(fill='x')
        device=Section(body,'本机显示器 · 立即生效',opened=False);device._feature_tools=True;self.develop_sections['display_device']=device
        ttk.Label(device.body,text='以下设置影响本机所有照片；立即保存，不受工作台应用或取消控制，不随照片同步。',style='Muted.TLabel',wraplength=270).pack(fill='x')
        self.button(device.body,'使用系统显示器 ICC',self.use_monitor_profile)
        self.button(device.body,'手动选择显示器 ICC',lambda:self.choose_output_profile('monitor'))
        self.button(device.body,'显示器恢复 sRGB',self.reset_monitor_profile)
    def sync_develop_output(self):
        v=output.checked(self.workflow_extensions.get('output',{}));self.output_space.set(v['space']);self.output_hdr.set(v['hdr']);self.proof_enabled.set(v['proof_enabled']);self.proof_gamut.set(v['gamut_warning']);self.hdr_preview.set(v['hdr_preview'])
        self.proof_note.set('HDR为浮点TIFF；当前窗口采用SDR显示。' if v['hdr'] else 'ICC转换保留浮点精度；软打样只影响预览。')
        notes=output.display_profiles(v)[2]
        if notes:self.proof_note.set(' '.join(notes))
    def output_changed(self):
        if self.loading_creative:return
        self.commit_edit('色彩输出设置前');v=output.checked(self.workflow_extensions.get('output',{}))
        v.update(space=self.output_space.get(),hdr=self.output_hdr.get(),proof_enabled=self.proof_enabled.get(),gamut_warning=self.proof_gamut.get(),hdr_preview=self.hdr_preview.get())
        self.workflow_extensions['output']=output.checked(v);self.refresh_color();self.record('色彩输出与软打样')
    def choose_output_profile(self,key):
        p=filedialog.askopenfilename(filetypes=[('ICC 色彩配置','*.icc *.icm')],parent=self.color_dialog_parent())
        if not p:return
        from icc_runtime import profile_bytes
        try:profile_bytes(p)
        except (OSError,ValueError) as e:messagebox.showerror('ICC无法使用',str(e),parent=self.color_dialog_parent());return
        if key=='monitor':
            from app_preferences import save_preferences
            save_preferences({'monitor_profile':p});self.sync_develop_output();self.refresh_color();return
        self.commit_edit('ICC设置前');v=output.portable(self.workflow_extensions.get('output',{}));v[key]=p
        if key=='proof':v['proof_enabled']=True
        self.workflow_extensions['output']=v;self.sync_develop_output();self.refresh_color();self.record('设置ICC '+key)
    def use_monitor_profile(self):
        from icc_runtime import monitor_profile
        path=monitor_profile()
        if not path:self.proof_note.set('系统未提供显示器ICC，可以手动选择。');return
        from app_preferences import save_preferences
        save_preferences({'monitor_profile':path});self.sync_develop_output();self.refresh_color();self.proof_note.set('已使用本机显示器ICC；此设置不随照片同步。')
    def reset_monitor_profile(self):
        from app_preferences import save_preferences
        save_preferences({'monitor_profile':''})
        self.sync_develop_output();self.refresh_color();self.proof_note.set('本机显示器已恢复 sRGB；照片的软打样与输出设置保持不变。')
    def reset_proof_preview(self):
        self.commit_edit('恢复打样预览前');v=output.portable(self.workflow_extensions.get('output',{}));v['proof_enabled']=False;v['gamut_warning']=False;v['hdr_preview']=False;self.workflow_extensions['output']=v;self.sync_develop_output();self.refresh_color();self.record('恢复当前照片打样预览')
