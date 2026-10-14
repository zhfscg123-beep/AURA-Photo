"""Photographic controls in AURA's existing Tk sections and color palette."""
import copy,tkinter as tk
from tkinter import ttk,filedialog
import numpy as np
from dark_ui import Section
import color_science as cs
from develop_output_ui import DevelopOutputUI
from develop_optics_ui import DevelopOpticsUI
from fuji_profiles_ui import FujiProfilesUI

class DevelopUI(DevelopOutputUI,DevelopOpticsUI,FujiProfilesUI):
    def color_dialog_parent(self):
        workbench=getattr(self,'color_workbench',None)
        return workbench.window if workbench is not None and workbench.active else self.root

    def init_develop_ui(self):
        self.color_process=tk.StringVar(value='专业浮点调色')
        self.point_color_index=tk.IntVar(value=0);self.point_color_label=tk.StringVar(value='尚未取样')
        self.point_color_vars={k:tk.DoubleVar(value=v) for k,v in dict(hue_range=30,chroma_range=.15,lightness_range=.4,hue_shift=0,saturation=0,luminance=0,variance=0).items()}
        self.bw_vars={k:tk.DoubleVar(value=0) for k in ('红','橙','黄','绿','青','蓝','紫','洋红')}
        self.raw_process=tk.StringVar(value='专业线性显影');self.raw_kelvin=tk.DoubleVar(value=6500);self.raw_tint=tk.DoubleVar(value=0)
        self.wb_preset=tk.StringVar(value='原始拍摄')
        self.init_develop_output()
        self.init_develop_optics()
        self.init_fuji_ui()

    def build_develop_controls(self,body):
        self.develop_sections={}
        combo=ttk.Combobox(body,textvariable=self.color_process,values=['专业浮点调色','兼容旧项目算法'],state='readonly')
        combo.pack(fill='x',before=body.winfo_children()[0] if body.winfo_children() else None);combo.bind('<<ComboboxSelected>>',lambda e:self.color_changed());self.controls.append(combo)
        self.develop_process_control=combo
        wb=Section(body,'白平衡 · 色温与中性取样',opened=False)
        wb._feature_scope='wb';self.develop_sections['wb']=wb
        selector=ttk.Combobox(wb.body,textvariable=self.wb_preset,values=['原始拍摄','自动','日光','阴天','阴影','钨丝灯','荧光灯','闪光灯','自定义'],state='readonly');selector.pack(fill='x');selector.bind('<<ComboboxSelected>>',lambda e:self.choose_wb_preset());self.controls.append(selector)
        for key,title in [('wb_kelvin','色温参考 K'),('wb_tint','绿／洋红偏色')]:self.develop_slider(wb.body,key,title)
        self.mode_button(wb.body,'在照片上取中性灰 / 白','develop_wb')
        self.button(wb.body,'清除中性取样',self.clear_wb_sample)
        self.button(wb.body,'自动影调',self.auto_develop_tone)
        self.button(wb.body,'XMP 参数应用到当前照片',self.import_xmp_color)
        self.button(wb.body,'导出 XMP 调色设置',self.export_xmp_color)
        grading=Section(body,'色彩分级 · 三向与全局',opened=False)
        self.develop_sections['grading']=grading
        from color_workbench_widgets import GradingWheel
        wheels=ttk.Frame(grading.body);wheels.pack(fill='x',pady=8)
        for column,(name,title) in enumerate([('shadow','阴影'),('midtone','中间调'),('highlight','高光')]):
            wheels.columnconfigure(column,weight=1,uniform='grading');slot=ttk.Frame(wheels);slot.grid(row=0,column=column,sticky='nsew');ttk.Label(slot,text=title,anchor='center').pack(fill='x');GradingWheel(slot,self,name,compact=True)
        ttk.Label(grading.body,text='中心为中性 · 左右键调整色相 · 上下键调整强度',style='Muted.TLabel',wraplength=290).pack(fill='x')
        for name,title in [('shadow','阴影'),('midtone','中间调'),('highlight','高光'),('global','全局')]:
            sub=Section(grading.body,title,opened=False)
            if name=='global':GradingWheel(sub.body,self,name)
            for suffix,label in [('hue','色相'),('color','饱和度')]+([] if name=='global' else [('luma','明度')]):self.develop_slider(sub.body,name+'_'+suffix,label)
            self.button(sub.body,'选择分级颜色',lambda n=name:self.pick_grade_color(n))
        for key in ('grading_balance','grading_blend'):self.develop_slider(grading.body,key)
        point=Section(body,'点颜色 · 可调颜色范围',opened=False);point._feature_scope='point_colors'
        self.develop_sections['point']=point
        self.mode_button(point.body,'在照片上添加颜色取样','develop_point')
        self.point_selector=ttk.Combobox(point.body,values=[],state='readonly');self.point_selector.pack(fill='x');self.point_selector.bind('<<ComboboxSelected>>',self.select_point_color);self.controls.append(self.point_selector)
        ttk.Label(point.body,textvariable=self.point_color_label,style='Muted.TLabel',wraplength=270).pack(fill='x')
        for key,title,lo,hi,decimals in [('hue_shift','色相变化',-100,100,0),('saturation','饱和度变化',-100,100,0),('luminance','明度变化',-100,100,0),('hue_range','色相范围',1,180,0),('chroma_range','饱和度范围',.01,1,2),('lightness_range','明度范围',.01,4,2)]:self.slider(point.body,title,self.point_color_vars[key],lo,hi,self.point_color_changed,decimals=decimals)
        self.slider(point.body,'颜色离散程度',self.point_color_vars['variance'],-100,100,self.point_color_changed)
        self.button(point.body,'预览受影响颜色范围',lambda:self.color_workbench.toggle_point_preview())
        self.button(point.body,'删除当前点颜色',self.remove_point_color)
        detail=Section(body,'全图质感、降噪与锐化',opened=False)
        self.develop_sections['detail']=detail
        for key in ('texture','clarity','dehaze','denoise_luma','denoise_detail','denoise_contrast','denoise_chroma','denoise_color_detail','denoise_color_smooth','sharpen','sharpen_radius','sharpen_detail','sharpen_mask'):self.develop_slider(detail.body,key)
        bw=Section(body,'黑白混色',opened=False)
        bw._feature_scope='bw';self.develop_sections['bw']=bw
        self.develop_slider(bw.body,'bw','黑白转换：0关闭 / 1开启')
        for name,var in self.bw_vars.items():self.slider(bw.body,name+'明度',var,-100,100,self.bw_mix_changed)
        calibration=Section(body,'RGB 原色校准',opened=False)
        self.develop_sections['calibration']=calibration
        for name in ('red','green','blue'):
            for suffix in ('hue','sat'):self.develop_slider(calibration.body,'cal_'+name+'_'+suffix)
        self.develop_slider(calibration.body,'cal_shadow_tint')
        effects=Section(body,'曲线保色、暗角与颗粒',opened=False)
        self.develop_sections['effects']=effects
        for key in ('curve_saturation','vignette','vignette_midpoint','vignette_roundness','vignette_feather','vignette_highlights'):self.develop_slider(effects.body,key)
        self.vignette_mode=tk.StringVar(value='高光优先')
        combo=ttk.Combobox(effects.body,textvariable=self.vignette_mode,values=['高光优先','颜色优先','叠色'],state='readonly');combo.pack(fill='x');self.controls.append(combo)
        combo.bind('<<ComboboxSelected>>',lambda e:self.choose_vignette_mode())
        for key in ('grain','grain_size','grain_roughness'):self.develop_slider(effects.body,key)
        check=ttk.Checkbutton(effects.body,text='胶片颗粒 · 随原图比例缩放',variable=self.creative_vars['grain_model'],onvalue=1,offvalue=0,command=self.color_changed);check.pack(anchor='w');self.controls.append(check)
        self.build_develop_output(body)
        self.build_develop_optics(body)

    def develop_slider(self,parent,key,title=None):
        import creative_color as color
        k,label,lo,hi=next(row for row in color.CONTROLS if row[0]==key)
        return self.slider(parent,title or label,self.creative_vars[key],lo,hi,self.color_changed,decimals=2 if key in ('sharpen_radius',) else 0)

    def choose_vignette_mode(self):
        self.creative_vars['vignette_style'].set(['高光优先','颜色优先','叠色'].index(self.vignette_mode.get()));self.parameter_apply(self.color_changed)

    def sync_develop_ui(self,data):
        if hasattr(self,'vignette_mode'):self.vignette_mode.set(['高光优先','颜色优先','叠色'][int(data['values']['vignette_style'])])
        self.color_process.set('专业浮点调色' if data['process']==2 else '兼容旧项目算法')
        self.wb_preset.set('自定义' if data.get('wb_sample') or data['values']['wb_kelvin']!=6500 or data['values']['wb_tint'] else '原始拍摄')
        for k,var in self.bw_vars.items():var.set(data['bw_mix'].get(k,0))
        self.point_selector.configure(values=[f'{i+1} · 色相 {r["hue"]:.0f}°' for i,r in enumerate(data['point_colors'])])
        if data['point_colors']:
            i=min(self.point_color_index.get(),len(data['point_colors'])-1);self.point_color_index.set(i);self.point_selector.current(i)
            r=data['point_colors'][i]
            for k,var in self.point_color_vars.items():var.set(r[k])
            self.point_color_label.set(f'取样明度 {r["lightness"]:.2f} · 色度 {r["chroma"]:.2f}')
        else:self.point_selector.set('');self.point_color_label.set('尚未取样')
        self.sync_develop_output()
        self.sync_develop_optics()
    def choose_wb_preset(self):
        if self.loading_creative:return
        name=self.wb_preset.get()
        if name=='自定义':return
        self.commit_edit('白平衡方案前');data=self.workflow_extensions.setdefault('color',{});data['wb_sample']=None
        self.creative_vars['wb_kelvin'].set({'原始拍摄':6500,'自动':6500,'日光':5500,'阴天':6500,'阴影':7500,'钨丝灯':2850,'荧光灯':4200,'闪光灯':6000}[name]);self.creative_vars['wb_tint'].set(0)
        if name=='自动' and self.color_input is not None:
            step=max(1,len(self.color_input)//800);pixels=cs.decode(self.color_input[::step,::step]/255).reshape(-1,3)
            luma=pixels@np.array([.2126,.7152,.0722],np.float32);spread=(pixels.max(1)-pixels.min(1))/np.maximum(pixels.max(1),.001)
            valid=(luma>.03)&(luma<.85)&(spread<.45)
            if valid.sum()>30:
                mean=np.mean(pixels[valid],0);data['wb_sample']=np.clip(mean[1]/np.maximum(mean,.001),.125,8).tolist()
        self.color_process.set('专业浮点调色');self.color_changed();self.record('白平衡方案 '+name)

    def select_point_color(self,event=None):
        i=self.point_selector.current()
        if i<0:return
        self.point_color_index.set(i);self.loading_creative=True
        try:
            import creative_color as color
            self.sync_develop_ui(color.validate(self.workflow_extensions.get('color',{})))
        finally:self.loading_creative=False

    def point_color_changed(self):
        if self.loading_creative:return
        data=self.workflow_extensions.get('color',{});records=data.get('point_colors',[]);i=self.point_color_index.get()
        if not 0<=i<len(records):self.status.set('请先在照片上添加点颜色取样。');return
        self.commit_edit('点颜色调整前');records[i].update({k:v.get() for k,v in self.point_color_vars.items()});self.color_process.set('专业浮点调色');self.color_changed()

    def remove_point_color(self):
        records=self.workflow_extensions.get('color',{}).get('point_colors',[]);i=self.point_color_index.get()
        if not 0<=i<len(records):return
        self.commit_edit('删除点颜色前');records.pop(i);self.sync_creative_color_ui();self.refresh_color();self.record('删除点颜色')

    def bw_mix_changed(self):
        if self.loading_creative:return
        self.workflow_extensions.setdefault('color',{})['bw_mix']={k:v.get() for k,v in self.bw_vars.items()};self.color_process.set('专业浮点调色');self.color_changed()

    def clear_wb_sample(self):
        self.commit_edit('清除白平衡取样前');self.workflow_extensions.get('color',{}).pop('wb_sample',None);self.refresh_color();self.record('清除白平衡取样')

    def develop_pick(self,event):
        if self.busy or self._render_pending or self.color_input is None:return
        x,y=np.rint(self.original_point(self.point(event))).astype(int);h,w=self.color_input.shape[:2]
        if not 0<=x<w or not 0<=y<h:return
        sample=np.median(self.color_input[max(0,y-2):min(h,y+3),max(0,x-2):min(w,x+3)].reshape(-1,3),axis=0)
        self.commit_edit('调色取样前');data=self.workflow_extensions.setdefault('color',{});self.color_process.set('专业浮点调色')
        if self.mode.get()=='develop_wb':
            value=np.maximum(cs.decode(sample/255),1e-5);gain=np.clip(value[1]/value,.125,8)
            data['wb_sample']=gain.tolist();self.creative_vars['wb_kelvin'].set(6500);self.creative_vars['wb_tint'].set(0)
            self.status.set('已按中性取样校正白平衡，可继续微调冷暖。')
        elif self.mode.get()=='develop_hsl':
            import cv2,creative_color as color
            hsv=cv2.cvtColor(np.clip(sample.reshape(1,1,3)/255,0,1).astype(np.float32),cv2.COLOR_RGB2HSV)[0,0]
            name=min(color.HUES,key=lambda k:abs((float(hsv[0])-color.HUES[k]+180)%360-180));self.choose_hsl(name);self.select_tool('pan');self.status.set('已定位HSL：'+name);return
        else:
            records=data.setdefault('point_colors',[])
            if len(records)>=8:self.status.set('点颜色最多8组，请先删除不需要的取样。');return
            lab=cs.oklab(cs.decode(sample/255));hue=float((np.rad2deg(np.arctan2(lab[2],lab[1]))+360)%360)
            record=dict(hue=hue,chroma=float(np.linalg.norm(lab[1:])),lightness=float(max(0,lab[0])))
            from develop_settings import checked_points
            records.append(checked_points([record])[0]);self.point_color_index.set(len(records)-1)
        self.color_changed();self.sync_creative_color_ui();self.select_tool('pan');self.record('调色取样')
    def import_xmp_color(self):
        p=filedialog.askopenfilename(filetypes=[('Lightroom / Camera Raw XMP','*.xmp')],parent=self.color_dialog_parent())
        if not p:return
        from xmp_color_style import read
        from tkinter import messagebox
        try:data,report=read(p)
        except (OSError,ValueError) as e:messagebox.showerror('XMP无法导入',str(e),parent=self.color_dialog_parent());return
        self.apply_xmp_color(data,report)

    def apply_xmp_color(self,data,report,source_ready=False):
        from tkinter import messagebox
        from xmp_color_style import merge_import
        from fuji_profiles import required_base
        merged=merge_import(self.workflow_extensions.get('color',{}),data,report)
        required=report.get('raw_base') or required_base({'color':merged})
        if not source_ready and not self.check_filter_raw_base({'raw_base':required},dict(kind='xmp',data=data,report=report)):return
        if required:
            self.apply_color_style({'color':merged,'raw_base':required},report['name'][:30],source_ready=True)
        else:
            self.commit_edit('XMP导入前');self.workflow_extensions['color']=merged;self.workflow_extensions.pop('color_filter',None)
        if 'optics' in report:
            if 'optics_patch' in report:
                from develop_optics import checked
                current=checked(self.workflow_extensions.get('optics',{}));current.update(report['optics_patch']);self.workflow_extensions['optics']=checked(current)
            else:self.workflow_extensions['optics']=report['optics']
        self.sync_creative_color_ui();self.parameter_apply(self.refresh);self.record('XMP参数映射 '+report['name'])
        messagebox.showinfo('XMP映射结果',f'已映射 {len(report["mapped"])} 项。\n'+report['notice']+'\n未导入：'+('、'.join(report['unsupported'][:15]) or '无')+'\n'+'\n'.join(report['warnings']),parent=self.color_dialog_parent())

    def export_xmp_color(self):
        from xmp_color_style import write
        from tkinter import messagebox
        if not self.document or self.busy:return
        path=filedialog.asksaveasfilename(title='导出调色XMP',defaultextension='.xmp',filetypes=[('XMP','*.xmp')],parent=self.color_workbench.window if self.color_workbench.active else self.root)
        if not path:return
        from fuji_profiles import required_base
        try:report=write(path,self.workflow_extensions.get('color',{}),self.workflow_extensions.get('optics',{}),required_base(self.workflow_extensions))
        except (OSError,ValueError) as e:messagebox.showerror('XMP未导出',str(e),parent=self.color_dialog_parent());return
        self.status.set('XMP已导出。'+report['notice'])

    def pick_grade_color(self,name):
        from color_widgets import ColorPalette
        def apply(rgb):
            lab=cs.oklab(cs.decode(np.array(rgb,np.float32)/255));hue=float((np.rad2deg(np.arctan2(lab[2],lab[1]))+360)%360)
            self.commit_edit('分级颜色前');self.creative_vars[name+'_hue'].set(hue);self.creative_vars[name+'_color'].set(min(100,float(np.linalg.norm(lab[1:]))/.0012));self.color_process.set('专业浮点调色');self.color_changed()
        self.color_palette=ColorPalette(self.color_dialog_parent(),[128,128,128],apply,'分级颜色 · '+name)

    def auto_develop_tone(self):
        if self.color_input is None or self.busy:return
        image=self.color_input[::max(1,len(self.color_input)//1000)].astype(np.float32)
        luminance=cs.decode(image/255)@np.array([.2126,.7152,.0722],np.float32);q=np.percentile(luminance,[2,50,98])
        self.commit_edit('自动影调前');self.creative_vars['exposure'].set(float(np.clip(np.log2(.18/max(q[1],1e-5)),-3,3)))
        self.creative_vars['highlights'].set(float(np.clip(-max(0,q[2]-.85)*100,-100,0)))
        self.creative_vars['shadows'].set(float(np.clip((.025-q[0])*800,0,60)));self.color_process.set('专业浮点调色');self.color_changed();self.record('自动影调')
