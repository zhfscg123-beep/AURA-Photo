"""Float global color controls and regional reference matching."""
import json,copy,tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from dark_ui import Section
from core import ROOT
from photo_document import open_document
from creative_regions import regions
import creative_color as color
from develop_ui import DevelopUI
from color_filters_ui import ColorFiltersUI

class CreativeColorUI(DevelopUI,ColorFiltersUI):
    def init_creative_color(self):
        self.creative_vars={k:tk.DoubleVar(value=color.DEFAULTS[k]) for k,_,_,_ in color.CONTROLS}
        self.curve_vars=[tk.DoubleVar(value=0) for _ in range(5)];self.hsl_name=tk.StringVar(value='红')
        self.hsl_vars=[tk.DoubleVar(value=0) for _ in range(3)];self.loading_creative=False
        self.lut_note=tk.StringVar(value='尚未加载 LUT');self.reference_note=tk.StringVar(value='尚未选择参考图')
        self.reference_scope=tk.StringVar(value='全图');self.reference_color=tk.DoubleVar(value=0);self.reference_tone=tk.DoubleVar(value=0)
        self.creative_input=None;self.creative_output=None;self.color_input=None
        self.init_develop_ui()
        self.init_color_filters()
    def build_creative_color_panel(self,panel):
        section=Section(panel,'全局调色与风格',opened=False);self.creative_color_panel=section;body=section.body
        for title,start,end in [('基本影调',0,10),('旧版阴影与高光染色',10,14),('LUT 与肤色保护',14,16)]:
            sub=Section(body,title,opened=start==0)
            if start==0:basic_section=sub
            elif start==10:legacy_grade=sub
            else:lut_section=sub
            for k,label,lo,hi in color.CONTROLS[start:end]:
                if k not in ('temperature','tint'):self.slider(sub.body,label,self.creative_vars[k],lo,hi,self.color_changed,decimals=2 if k=='exposure' else 0)
            if start==14:self.button(sub.body,'导入 3D .cube LUT',self.import_lut);ttk.Label(sub.body,textvariable=self.lut_note,style='Muted.TLabel').pack(anchor='w')
        self.build_develop_controls(body)
        for k,title in [('temperature','旧版相对色温'),('tint','旧版相对色调')]:self.slider(legacy_grade.body,title,self.creative_vars[k],-100,100,self.color_changed)
        filters=self.build_color_filters(body)
        sub=Section(body,'色调曲线',opened=False)
        curve_section=sub
        sub._feature_scope='curve'
        from curve_editor import CurveEditor
        self.point_curve_editor=CurveEditor(sub.body,self)
        self.mode_button(sub.body,'在照片上拖动调整亮度','develop_target_curve')
        param=Section(sub.body,'参数曲线与亮度分界',opened=False)
        from color_workbench_widgets import ParametricCurve
        self.parametric_curve_editor=ParametricCurve(param.body,self)
        for key in ('curve_shadow','curve_dark','curve_light','curve_highlight','curve_split_shadow','curve_split_mid','curve_split_highlight'):self.develop_slider(param.body,key)
        legacy=Section(sub.body,'旧版五段曲线（项目兼容）',opened=False)
        for i,label in enumerate(('黑点','阴影','中间调','高光','白点')):self.slider(legacy.body,label,self.curve_vars[i],-100,100,self.color_changed)
        sub=Section(body,'HSL 色彩',opened=False)
        hsl_section=sub
        sub._feature_scope='hsl';self.hsl_swatches={};swatches=ttk.Frame(sub.body);swatches.pack(fill='x',pady=5)
        from color_widgets import hue_rgb,rgb_hex,ColorParameterScale
        for name,hue in color.HUES.items():
            b=tk.Button(swatches,text=name,bg=rgb_hex(hue_rgb(hue,.75,.85)),fg='white',relief='flat',width=2,command=lambda n=name:self.choose_hsl(n));b.pack(side='left',expand=True,fill='x',padx=1);self.hsl_swatches[name]=b
        self.hsl_ramps=[]
        self.mode_button(sub.body,'在照片上取色定位 HSL','develop_hsl')
        self.hsl_target_axis=tk.StringVar(value='明亮度')
        target=ttk.Combobox(sub.body,textvariable=self.hsl_target_axis,values=['色相','饱和度','明亮度'],state='readonly');target.pack(fill='x');self.controls.append(target)
        self.mode_button(sub.body,'在照片上拖动调整颜色','develop_target_hsl')
        for i,title in enumerate(('色相','饱和度','明亮度')):
            c=ColorParameterScale(sub.body,title,self.hsl_vars[i],-100,100,lambda:self.parameter_apply(self.hsl_changed),self.record);c.preview_command=self.preview_global_color;self.controls.append(c);self.hsl_ramps.append(c)
        for title,fn in [('保存完整调色文件',self.save_color_style),('应用完整调色文件',self.load_color_style),('恢复全局调色',self.reset_global_color)]:self.button(body,title,fn)
        ttk.Label(body,text='完整文件包含曝光、白平衡、光学与参考图设置。滤镜库风格保留照片曝光与拍摄白平衡；仅复用风格请在“预设”保存到“我的”。',style='Muted.TLabel',wraplength=270).pack(fill='x')
        ttk.Label(body,text='默认零调整；肤色保护用于染色、HSL与LUT，影调独立。支持2–33阶标准3D .cube。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        tail=[w for w in body.winfo_children() if w not in [filters,self.develop_process_control,basic_section,legacy_grade,lut_section,curve_section,hsl_section]+list(self.develop_sections.values())]
        order=[filters,self.develop_process_control,self.develop_sections['wb'],basic_section,curve_section,hsl_section,self.develop_sections['point'],self.develop_sections['grading'],self.develop_sections['detail'],self.develop_sections['lens'],self.develop_sections['transform'],self.develop_sections['effects'],self.develop_sections['calibration'],self.develop_sections['bw'],lut_section,self.develop_sections['output'],self.develop_sections['display_device'],legacy_grade]+tail
        for widget in body.winfo_children():widget.pack_forget()
        for widget in order:widget.pack(fill='x',pady=(0,5))
        self.color_basic_section=basic_section;self.color_curve_section=curve_section;self.color_hsl_section=hsl_section
        self.color_lut_section=lut_section;self.color_legacy_grade=legacy_grade;self.color_filter_section=filters
        ref=Section(panel,'参考图追色',opened=False);self.reference_panel=ref;body=ref.body
        from reference_regions import SCOPES
        c=ttk.Combobox(body,textvariable=self.reference_scope,values=list(SCOPES),state='readonly');c.pack(fill='x');c.bind('<<ComboboxSelected>>',lambda e:self.reference_scope_changed())
        c._aura_search_name='参考图匹配范围'
        self.button(body,'导入参考图并分析',self.import_reference);self.button(body,'将当前效果作为参考',self.current_as_reference)
        ttk.Label(body,textvariable=self.reference_note,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        self.slider(body,'匹配颜色',self.reference_color,0,100,self.reference_changed);self.slider(body,'匹配影调',self.reference_tone,0,100,self.reference_changed)
        ttk.Label(body,text='导入后分别确认两张图的范围和对应人物，可拖框限制取样。范围错误时先用美颜补选修正，再重新确认参考图。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
    def color_changed(self):
        if self.loading_creative:return
        old=self.workflow_extensions.get('color',{})
        from develop_advanced import CONTROLS
        if any(self.creative_vars[k].get()!=default for k,_,_,_,default in CONTROLS):self.color_process.set('专业浮点调色')
        try:data=color.validate(dict(old,process=2 if self.color_process.get()=='专业浮点调色' else 1,values={k:float(v.get()) for k,v in self.creative_vars.items()},curve=[v.get() for v in self.curve_vars]))
        except ValueError as e:
            self.status.set(str(e));self.sync_creative_color_ui();return
        self.workflow_extensions['color']=data
        self.draw_curve();self.refresh_color();self.record('全局调色')
    def hsl_changed(self):
        if self.loading_creative:return
        self.workflow_extensions.setdefault('color',{}).setdefault('hsl',{})[self.hsl_name.get()]=[v.get() for v in self.hsl_vars];self.color_changed()
    def choose_hsl(self,name):self.hsl_name.set(name);self.sync_hsl()
    def sync_hsl(self):
        self.loading_creative=True
        try:
            for var,value in zip(self.hsl_vars,self.workflow_extensions.get('color',{}).get('hsl',{}).get(self.hsl_name.get(),[0,0,0])):var.set(value)
        finally:self.loading_creative=False
        if hasattr(self,'hsl_ramps'):
            from color_widgets import hue_rgb,rgb_hex
            hue=color.HUES[self.hsl_name.get()];rgb=rgb_hex(hue_rgb(hue))
            ramps=[[rgb_hex(hue_rgb(hue-25)),rgb,rgb_hex(hue_rgb(hue+25))],['#999999',rgb],['#161b20',rgb,'#ffffff']]
            for c,ramp in zip(self.hsl_ramps,ramps):c.set_colors(ramp)
            for name,b in self.hsl_swatches.items():b.configure(relief='solid' if name==self.hsl_name.get() else 'flat',borderwidth=2 if name==self.hsl_name.get() else 0)
    def sync_creative_color_ui(self):
        if not hasattr(self,'creative_vars'):return
        data=color.validate(self.workflow_extensions.get('color',{}));self.loading_creative=True
        try:
            for k,v in data['values'].items():self.creative_vars[k].set(v)
            for var,value in zip(self.curve_vars,data['curve']):var.set(value)
            ref=self.workflow_extensions.get('reference',{});self.reference_scope.set(ref.get('scope','全图'));self.reference_color.set(ref.get('color',0));self.reference_tone.set(ref.get('tone',0))
            self.reference_note.set(ref.get('name','尚未选择参考图'));self.lut_note.set(data['lut']['name'] if data['lut'] else '尚未加载 LUT')
            self.sync_develop_ui(data)
        finally:self.loading_creative=False
        self.sync_hsl();self.draw_curve()
        self.sync_filter_ui()
    def draw_curve(self):
        if hasattr(self,'parametric_curve_editor'):self.parametric_curve_editor.draw()
        if hasattr(self,'point_curve_editor'):self.point_curve_editor.draw();return
        if not hasattr(self,'curve_canvas'):return
        import numpy as np
        c=self.curve_canvas;c.delete('all');w=max(100,c.winfo_width());h=max(60,c.winfo_height());points=[]
        ys=np.maximum.accumulate(np.clip(np.linspace(0,1,5)+np.array([v.get() for v in self.curve_vars])/500,0,1))
        c.create_line(8,h-8,w-8,8,fill='#bcc9da',dash=(3,3))
        for i,v in enumerate(ys):x=8+i*(w-16)/4;y=h-8-v*(h-16);points.extend((x,y));c.create_oval(x-3,y-3,x+3,y+3,fill='#3169ec',outline='')
        c.create_line(*points,fill='#3169ec',width=2)
    def import_lut(self):
        path=filedialog.askopenfilename(filetypes=[('3D LUT','*.cube')],parent=self.color_dialog_parent())
        if not path:return
        try:
            from portable_lut import pack
            lut=pack(color.read_cube(path))
        except (OSError,ValueError) as e:messagebox.showerror('LUT无法加载',str(e),parent=self.color_dialog_parent());return
        self.workflow_extensions.setdefault('color',{})['lut']=lut;self.lut_note.set(lut['name']);self.record('导入 LUT（强度保持当前值）');self.refresh_color()
    def reset_global_color(self,source_ready=False):
        if not source_ready and not self.check_filter_raw_base({},dict(kind='reset')):return
        self.commit_edit('恢复全局调色前');self.workflow_extensions.pop('color',None);self.workflow_extensions.pop('color_filter',None)
        self.sync_creative_color_ui();self.refresh_color();self.record('恢复全局调色')
    def reference_scope_changed(self):
        if self.loading_creative:return
        self.workflow_extensions.pop('reference',None);self.reference_color.set(0);self.reference_tone.set(0);self.reference_note.set('区域已更改，请重新选择参考图');self.refresh()
    def region_for_reference(self,data,scope,person=None,roi=None):
        from reference_regions import select
        return select(data,scope,person,roi)
    def import_reference(self):
        if not self.session or self.busy:return
        path=filedialog.askopenfilename(filetypes=[('参考照片','*.jpg *.jpeg *.png *.tif *.tiff *.arw *.nef *.cr3 *.raf')],parent=self.color_dialog_parent())
        if not path:return
        scope=self.reference_scope.get();session=self.session;layers=copy.deepcopy(self.region_layers)
        def job():
            rgb=open_document(path).base_float()
            import cv2
            from reference_regions import ReferenceSession,full_frame
            factor=min(1,1800/max(rgb.shape[:2]));rgb=cv2.resize(rgb,(max(1,round(rgb.shape[1]*factor)),max(1,round(rgb.shape[0]*factor))))
            if scope=='全图':return rgb,full_frame(rgb.shape[:2]),full_frame(session.original.shape[:2])
            import numpy as np
            s=ReferenceSession(np.clip(np.rint(rgb),0,255).astype(np.uint8),.35,self.progress)
            return rgb,regions(s),regions(session,layers)
        def ready(result):
            if self.session is not session:return
            from reference_review_ui import review
            rgb,source_data,target_data=result
            review(self,rgb,source_data,session.original,target_data,scope,Path(path).name)
        self.work(job,ready)
    def current_as_reference(self):
        if self.creative_output is None or self.busy:return
        from reference_review_ui import review
        from reference_regions import full_frame
        data=full_frame(self.session.original.shape[:2]) if self.reference_scope.get()=='全图' else regions(self.session,self.region_layers)
        review(self,self.creative_output,data,self.session.original,data,self.reference_scope.get(),'当前效果')
    def reference_changed(self):
        if self.loading_creative:return
        ref=self.workflow_extensions.get('reference')
        if not ref:self.status.set('请先选择并分析参考图。');return
        ref.update(color=float(self.reference_color.get()),tone=float(self.reference_tone.get()));self.refresh_color();self.record('调整参考图追色')
    def apply_creative_color(self,rgb):
        data=self.workflow_extensions
        if 'color' not in data and not data.get('reference',{}).get('stats') and getattr(self.document,'scene',None) is None and not any(l.get('color_process',1)==2 for l in self.region_layers):return rgb
        masks=regions(self.session,self.region_layers);before=self.effect_before('color',rgb);out=color.apply(rgb,data.get('color',{}),masks['skin'],document=self.document);ref=data.get('reference',{})
        if ref.get('stats') is not None and (ref.get('color',0) or ref.get('tone',0)):out=color.match(out,ref['stats'],ref.get('color',0),ref.get('tone',0),self.region_for_reference(masks,ref['scope'],ref.get('target_person'),ref.get('target_roi')),masks['skin'],data.get('color',{}).get('values',{}).get('skin_protect',0))
        out=self.effect_after('color',before,out)
        from local_develop import apply
        local_before=self.effect_before('local',out);out=apply(out,self.region_layers,reference=rgb)
        return self.effect_after('local',local_before,out)
    def save_color_style(self):
        path=filedialog.asksaveasfilename(initialdir=str(ROOT),initialfile='AURA调色.aura-style.json',defaultextension='.aura-style.json',parent=self.color_dialog_parent())
        if not path:return
        try:
            data=dict(kind='aura-color-style',schema=2,color=color.validate(self.workflow_extensions.get('color',{})),reference=self.workflow_extensions.get('reference',{}),optics=copy.deepcopy(self.workflow_extensions.get('optics',{})))
            from fuji_profiles import required_base
            required=required_base(self.workflow_extensions)
            if required:data['raw_base']=required
            with Path(path).open('x',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,allow_nan=False)
        except (OSError,ValueError) as e:messagebox.showerror('预设未保存',str(e),parent=self.color_dialog_parent())
    def load_color_style(self):
        path=filedialog.askopenfilename(filetypes=[('AURA调色预设','*.aura-style.json')],parent=self.color_dialog_parent())
        if not path:return
        try:
            p=Path(path)
            if p.stat().st_size>2000000:raise ValueError('预设过大。')
            data=json.loads(p.read_text(encoding='utf8'))
            if data.get('kind')!='aura-color-style' or data.get('schema') not in (1,2):raise ValueError('调色预设格式无效。')
            values=color.validate(data['color'])
            from workflow_extensions import validate_extensions
            validate_extensions({'color':values,'reference':data.get('reference',{})},self.document.rgb.shape[:2] if self.document else (1,1))
            if 'optics' in data:
                from develop_optics import checked
                data['optics']=checked(data['optics'])
        except (OSError,ValueError,KeyError,TypeError) as e:messagebox.showerror('预设无法加载',str(e),parent=self.color_dialog_parent());return
        self.apply_color_style(data,Path(path).stem[:30])

    def apply_color_style(self,data,name,source_ready=False):
        ref=data.get('reference',{})
        if ref.get('target_roi') is not None or ref.get('target_person') is not None:
            messagebox.showerror('预设无法加载','该追色预设包含原照片的人物或取样框，请在当前照片重新导入参考图并确认区域。',parent=self.color_dialog_parent());return
        values=color.validate(data['color'])
        from fuji_profiles import required_base
        required=data.get('raw_base') or required_base({'color':values})
        if required is not None:
            from fuji_profiles import RAW_BASE,CALIBRATED_RAW_BASE
            if required not in (RAW_BASE,CALIBRATED_RAW_BASE):messagebox.showerror('预设无法加载','RAW基底记录无效。',parent=self.color_dialog_parent());return
        action=dict(kind='style',data=copy.deepcopy(data),name=name)
        if not source_ready and not self.check_filter_raw_base({'raw_base':required},action):return
        previous=color.validate(self.workflow_extensions.get('color',{}));self.commit_edit('导入调色预设前')
        self.workflow_extensions['color']=values
        self.workflow_extensions.pop('color_filter',None)
        if required:
            import color_presets
            recipe={key:copy.deepcopy(values[key]) for key in color_presets.RECIPE_KEYS}
            for key,neutral in (('hsl',[0,0,0]),('points',[[0,0],[1,1]]),('bw_mix',0)):
                for name in previous[key]:recipe[key].setdefault(name,copy.deepcopy(neutral))
            values=color_presets.overlay(values,recipe);self.workflow_extensions['color']=values
            item=color_presets.checked_preset(dict(id='imported-raw-style',name=name,group='富士RAW',description='完整调色文件；强度与恢复包含全部调色参数。光学与参考图设置独立。',raw_base=required,recipe=recipe))
            self.workflow_extensions['color_filter']=dict(preset=item,base=color_presets.capture_base(previous,item['recipe']),amount=100,signature=color_presets.signature(values))
        if 'reference' in data:
            if data['reference']:self.workflow_extensions['reference']=copy.deepcopy(data['reference'])
            else:self.workflow_extensions.pop('reference',None)
        if 'optics' in data:self.workflow_extensions['optics']=data['optics']
        self.sync_creative_color_ui();self.refresh();self.record('应用调色预设')
    def sync_global_creative(self,source):
        ref=source.get('reference',{})
        if ref.get('target_roi') is not None or ref.get('target_person') is not None:
            raise ValueError('参考追色区域属于原照片，请在目标照片重新确认。')
        for k in ('color','color_filter','reference'):
            if k in source:self.workflow_extensions[k]=copy.deepcopy(source[k])
            else:self.workflow_extensions.pop(k,None)
        self.sync_creative_color_ui()
