"""Manual brush interaction. Store original coordinates; preview never replaces RAW."""
import copy, time, tkinter as tk
from tkinter import ttk
import cv2
import numpy as np
from PIL import Image
from dark_ui import Section, ToolButton, COLORS
from photo_document import to_uint8
from body_shape import apply_forms
import face_reshape, liquify, manual_retouch as retouch

LABELS = dict(dodge='减淡', burn='加深', heal='修复画笔', clone='仿制图章', restore='恢复画笔')
TONES = {'全部': 'all', '阴影': 'shadows', '中间调': 'midtones', '高光': 'highlights'}
HEALING = {'自然融合':'gradient','纹理保留':'texture'}
VARS = ('manual_radius','manual_hardness','manual_opacity','manual_flow','manual_strength','manual_tone','manual_aligned','manual_enabled','manual_spacing','manual_scale','manual_angle','manual_flip_x','manual_flip_y','manual_healing')

class RetouchUI:
    def init_retouch(self):
        for key in ('radius','hardness','opacity','flow','strength','spacing','scale','angle'):
            setattr(self,'manual_'+key,tk.DoubleVar(value=retouch.DEFAULT_TOOLS[key]))
        self.manual_flip_x=tk.BooleanVar(value=False);self.manual_flip_y=tk.BooleanVar(value=False)
        self.manual_healing=tk.StringVar(value='自然融合')
        self.manual_tone=tk.StringVar(value='中间调');self.manual_aligned=tk.BooleanVar(value=True)
        self.manual_enabled=tk.BooleanVar(value=True);self.manual_hint=tk.StringVar(value='选择画笔，在照片上按住并拖动。')
        self.reset_retouch_state()
    def reset_retouch_state(self):
        self.manual_records=[];self.manual_input=None;self.manual_source=None;self.manual_offset=None;self.manual_anchor=None
        self.manual_pick_source=False;self.manual_preview=None;self.manual_preview_base=None;self.manual_preview_box=None;self.manual_preview_restore=None
    def manual_settings(self):
        values={key:float(getattr(self,'manual_'+key).get()) for key in ('radius','hardness','opacity','flow','strength','spacing','scale','angle')}
        return dict(values,tone=TONES[self.manual_tone.get()],aligned=bool(self.manual_aligned.get()),flip_x=bool(self.manual_flip_x.get()),flip_y=bool(self.manual_flip_y.get()),healing=HEALING[self.manual_healing.get()])
    def load_manual_settings(self,values=None):
        tools=retouch.validate_tools(values)
        for key in ('radius','hardness','opacity','flow','strength','spacing','scale','angle'):getattr(self,'manual_'+key).set(tools[key])
        self.manual_tone.set(next(k for k,v in TONES.items() if v==tools['tone']));self.manual_aligned.set(tools['aligned'])
        for key in ('flip_x','flip_y'):getattr(self,'manual_'+key).set(tools[key])
        self.manual_healing.set('自然融合' if values is None else next(k for k,v in HEALING.items() if v==tools['healing']))
    def build_retouch_panel(self,panel):
        section=Section(panel,'手动修饰 · 画笔');self.manual_panel=section;body=section.body
        for names in (('dodge','burn','restore'),('heal','clone')):
            row=ttk.Frame(body);row.pack(fill='x',pady=3)
            for name in names:
                key='retouch_'+name
                b=ToolButton(row,LABELS[name],key,lambda key=key:self.toggle_tool(key))
                b.pack(side='left',expand=True,fill='x',padx=1);self.tool_buttons[key]=b;self.controls.append(b)
        self.controls.append(self.slider(body,'半径 / 原图像素',self.manual_radius,1,1000,self.draw_tool_cursor,mutating=False))
        self.manual_strength_scale=self.slider(body,'减淡 / 加深强度',self.manual_strength,0,100,lambda:None,mutating=False);self.controls.append(self.manual_strength_scale)
        row=ttk.Frame(body);row.pack(fill='x',pady=4)
        ttk.Label(row,text='明暗范围').pack(side='left')
        self.manual_tone_control=ttk.Combobox(row,textvariable=self.manual_tone,values=list(TONES),state='readonly',width=9)
        self.manual_tone_control.pack(side='right');self.controls.append(self.manual_tone_control)
        self.manual_sample_button=self.button(body,'取样 · 再点击照片（或 Alt＋点击）',self.pick_manual_source)
        self.manual_align_control=ttk.Checkbutton(body,text='对齐取样 · 多笔保持来源偏移',variable=self.manual_aligned,command=self.reset_manual_offset)
        self.manual_align_control.pack(anchor='w',pady=4);self.controls.append(self.manual_align_control)
        row=ttk.Frame(body);row.pack(fill='x',pady=4)
        ttk.Label(row,text='修复融合').pack(side='left')
        self.manual_healing_control=ttk.Combobox(row,textvariable=self.manual_healing,values=list(HEALING),state='readonly',width=10)
        self.manual_healing_control.pack(side='right');self.controls.append(self.manual_healing_control)
        settings=Section(body,'笔刷设置',opened=False)
        for key,title,lo in (('hardness','硬度',0),('opacity','不透明度',0),('flow','流量',1),('spacing','间距 / 直径百分比',1)):
            self.controls.append(self.slider(settings.body,title,getattr(self,'manual_'+key),lo,100,self.draw_tool_cursor,mutating=False))
        samples=Section(body,'取样变换',opened=False);self.manual_transform_controls=[]
        for key,title,lo,hi in (('scale','取样缩放 / %',20,400),('angle','取样旋转 / 度',-180,180)):
            control=self.slider(samples.body,title,getattr(self,'manual_'+key),lo,hi,self.draw_tool_cursor,mutating=False)
            self.controls.append(control);self.manual_transform_controls.append(control)
        row=ttk.Frame(samples.body);row.pack(fill='x',pady=4)
        for key,title in (('flip_x','水平翻转'),('flip_y','垂直翻转')):
            control=ttk.Checkbutton(row,text=title,variable=getattr(self,'manual_'+key),command=self.draw_tool_cursor)
            control.pack(side='left',padx=4);self.controls.append(control);self.manual_transform_controls.append(control)
        self.manual_transform_controls.append(self.button(samples.body,'重置取样变换',self.reset_manual_transform))
        check=ttk.Checkbutton(body,text='显示手动修饰效果',variable=self.manual_enabled,command=self.toggle_manual)
        check.pack(anchor='w',pady=6);self.controls.append(check)
        ttk.Label(body,textvariable=self.manual_hint,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=4)
        row=ttk.Frame(body);row.pack(fill='x',pady=4)
        for title,fn in [('撤销',self.undo),('重做',self.redo),('浏览',lambda:self.select_tool('pan'))]:
            b=ttk.Button(row,text=title,command=fn);b.pack(side='left',expand=True,fill='x',padx=1);self.controls.append(b)
        ttk.Label(body,text='左键涂画 · 右键恢复 · 每笔可撤销\nCtrl＋滚轮调大小 · 空格平移\n笔画随项目保存',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=4)
    def sync_manual_ui(self):
        if not hasattr(self,'manual_panel'):return
        active=self.document is not None and not self.busy;mode=self.mode.get()[8:] if self.mode.get().startswith('retouch_') else ''
        sample=active and mode in ('heal','clone');tone=active and mode in ('dodge','burn')
        self.manual_sample_button.configure(state='normal' if sample else 'disabled')
        self.manual_align_control.configure(state='normal' if sample else 'disabled')
        self.manual_tone_control.configure(state='readonly' if tone else 'disabled')
        self.manual_strength_scale.configure(state='normal' if tone else 'disabled')
        self.manual_healing_control.configure(state='readonly' if active and mode=='heal' else 'disabled')
        for control in self.manual_transform_controls:control.configure(state='normal' if sample else 'disabled')
        source=f'取样点：{self.manual_source[0]:.0f}, {self.manual_source[1]:.0f}' if self.manual_source else '尚未取样，请 Alt＋点击干净皮肤。'
        self.manual_hint.set('请在照片上点击取样位置。' if self.manual_pick_source else source if sample else '减淡提亮，加深压暗；恢复画笔仅恢复手动修饰。')
        self.manual_sample_button.configure(style='Accent.TButton' if self.manual_pick_source else 'TButton',text='取样 · 开（再点退出）' if self.manual_pick_source else '取样 · 再点击照片（或 Alt＋点击）')
    def reset_manual_offset(self):
        self.manual_offset=None;self.manual_anchor=None;self.sync_manual_ui()
    def reset_manual_transform(self):
        self.manual_scale.set(100);self.manual_angle.set(0);self.manual_flip_x.set(False);self.manual_flip_y.set(False);self.draw_tool_cursor()
    def pick_manual_source(self):
        if self.busy:return
        if self.manual_pick_source:
            self.select_tool('pan');self.status.set('已退出取样，返回浏览；已有修改保留。');return
        self.manual_pick_source=True;self.sync_manual_ui();self.canvas.focus_set()
    def toggle_manual(self):
        if self.busy:return
        if self.drag and self.drag['mode'].startswith('retouch_'):self.finish_manual()
        self.render_manual();self.record('显示手动修饰' if self.manual_enabled.get() else '隐藏手动修饰')
    def render_manual(self):
        if self.manual_input is None:self.refresh();return
        effect_input=self.effect_before('manual',self.manual_input)
        self.output_float=retouch.apply(self.manual_input,self.manual_records,self.manual_enabled.get())
        self.output_float=self.effect_after('manual',effect_input,self.output_float)
        self.output_float=self.creative_render(self.output_float)
        self.output_float,self.form_changed=apply_forms(self.output_float,self.session,self.face_settings,self.region_layers,self.form_cache)
        self.output_float,self.reshape_changed=face_reshape.apply(self.output_float,self.face_settings,self.reshape_cache)
        import photo_body
        self.output_float,self.photo_body_changed,self.photo_body_message,self.photo_body_cache=photo_body.apply(self.output_float,self.session,self.face_settings,self.photo_body_values(),self.photo_body_cache)
        self.liquify_input=self.output_float
        if self.liquify_enabled.get():self.output_float=liquify.apply(self.liquify_input,self.liquify_state)
        self.output=to_uint8(self.output_float);self.make_navigation();self.draw_histogram();self.draw()
    def start_manual(self,event,erase=False,sampling=False):
        p=self.original_point(self.point(event));h,w=self.document.rgb.shape[:2]
        if not 0<=p[0]<w or not 0<=p[1]<h:return
        mode='restore' if erase else self.mode.get()[8:]
        if mode in ('heal','clone') and (sampling or self.manual_pick_source or event.state & (0x0008|0x20000)):
            self.manual_source=list(map(float,p));self.manual_offset=None;self.manual_anchor=None;self.manual_pick_source=False
            self.sync_manual_ui();self.draw_tool_cursor();return
        if len(self.manual_records)>=retouch.MAX_STROKES or sum(len(r['points']) for r in self.manual_records)>=retouch.MAX_TOTAL_POINTS:
            self.status.set('已达到手动笔画上限，请保存当前项目并导出成片。');return
        tools=self.manual_settings();rec=dict(tools,mode=mode,points=[list(map(float,p))])
        if mode in ('heal','clone'):
            if self.manual_source is None:self.status.set('先 Alt＋点击取样位置，再涂画需要修复的区域。');return
            if tools['aligned'] and self.manual_offset is not None:
                if self.manual_anchor is None:self.manual_anchor=(np.array(self.manual_source)-self.manual_offset).tolist()
                source=retouch.source_point(dict(tools,source=self.manual_source,points=[self.manual_anchor]),p)
            else:source=np.array(self.manual_source)
            if not 0<=source[0]<w or not 0<=source[1]<h:self.status.set('对齐取样已超出照片，请重新 Alt＋点击取样。');return
            rec['source']=source.tolist()
            if tools['aligned'] and self.manual_offset is None:self.manual_offset=source-np.array(p);self.manual_anchor=list(map(float,p))
        if mode=='restore' and not self.manual_records:return
        if tools['opacity']==0 or mode in ('dodge','burn') and tools['strength']==0:return
        was_enabled=self.manual_enabled.get();self.commit_edit('手动修饰前');self.manual_enabled.set(True)
        self.manual_preview_factor=min(1,max(1600/max(h,w),self.view.scale))
        base=retouch.apply(self.manual_input,self.manual_records,was_enabled) if self.manual_input is not None else self.document.base_float()
        if self.manual_input is None:self.manual_input=base
        if not was_enabled:base=retouch.apply(self.manual_input,self.manual_records)
        size=(max(1,round(w*self.manual_preview_factor)),max(1,round(h*self.manual_preview_factor)))
        self.manual_preview_base=cv2.resize(base,size,interpolation=cv2.INTER_AREA) if self.manual_preview_factor<1 else base
        self.manual_preview=self.manual_preview_base.copy();self.manual_preview_box=None
        self.manual_preview_restore=cv2.resize(self.manual_input,size,interpolation=cv2.INTER_AREA) if self.manual_preview_factor<1 else self.manual_input
        self.drag={'mode':'retouch_'+mode,'record':rec,'r':tools['radius'],'preview_at':0.}
        self.update_manual(self.point(event),force=True)
    def update_manual(self,p,force=False):
        d=self.drag
        if not d or not d['mode'].startswith('retouch_'):return
        p=self.original_point(p)
        h,w=self.document.rgb.shape[:2];p=[float(np.clip(p[0],0,w-1)),float(np.clip(p[1],0,h-1))]
        points=d['record']['points']
        count=sum(len(r['points']) for r in self.manual_records)+len(points)
        if np.linalg.norm(np.array(p)-points[-1])>.25:
            if len(points)<retouch.MAX_POINTS and count<retouch.MAX_TOTAL_POINTS:points.append(p)
            else:self.status.set('本笔已达到路径上限，请松开鼠标并另画一笔。')
        now=time.monotonic()
        if force or now-d['preview_at']>.05:
            r=retouch.scaled(d['record'],self.manual_preview_factor)
            if self.manual_preview_box is not None:
                a,b,c,e=self.manual_preview_box
                self.manual_preview[b:e,a:c]=self.manual_preview_base[b:e,a:c]
            self.manual_preview_box=retouch.brush_bounds(r,self.manual_preview.shape[:2])
            retouch.apply(self.manual_preview,[r],checked=False,restore_rgb=self.manual_preview_restore,copy_output=False,source_rgb=self.manual_preview_base)
            d['preview_at']=now;self.draw()
        else:self.draw_tool_cursor()
    def finish_manual(self):
        d=self.drag
        if not d or not d['mode'].startswith('retouch_'):return
        try:retouch.validate_records(self.manual_records+[d['record']],self.document.rgb.shape[:2])
        except ValueError as e:
            self.drag=None;self.manual_preview=None;self.draw();self.status.set(str(e));return
        self.manual_records.append(d['record']);self.drag=None;self.manual_preview=None;self.manual_preview_base=None;self.manual_preview_box=None;self.manual_preview_restore=None
        self.render_manual();self.record('手动修饰 · '+LABELS[d['record']['mode']]);self.sync_manual_ui()
        self.status.set(f'已应用 {LABELS[d["record"]["mode"]]} · {len(self.manual_records)} 笔；Ctrl＋Z 撤销。')
    def fast_manual_display(self,bounds,size,localcut):
        a,b,c,d=bounds;pw,ph=size;factor=self.manual_preview_factor
        x,y=np.meshgrid(a+(np.arange(pw,dtype=np.float32)+.5)*(c-a)/pw-.5,b+(np.arange(ph,dtype=np.float32)+.5)*(d-b)/ph-.5)
        q=self.original_points(np.stack([x.ravel(),y.ravel()],axis=1)).reshape(ph,pw,2)
        # Preview only the new stroke delta through the existing inverse geometry.
        # The committed stroke is replayed before color and geometry in full precision.
        mx=(q[:,:,0]+.5)*factor-.5;my=(q[:,:,1]+.5)*factor-.5
        delta=cv2.remap(self.manual_preview-self.manual_preview_base,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        rgb=to_uint8(cv2.remap(self.output_float,x,y,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)+delta)
        cut=int(round(localcut*pw/(c-a)))
        if cut:rgb[:,:cut]=cv2.remap(self.session.original,x[:,:cut],y[:,:cut],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        return Image.fromarray(rgb)
    def draw_manual_cursor(self,x,y,px,py):
        d=self.drag;rec=d['record'] if d and d['mode'].startswith('retouch_') else None
        r=(rec['radius'] if rec else float(self.manual_radius.get()))*self.view.scale
        for color,width in [('#202b3c',3),('#ffffff',1)]:self.canvas.create_oval(x-r,y-r,x+r,y+r,outline=color,width=width,tags='tool_cursor')
        if self.mode.get() in ('retouch_heal','retouch_clone') and self.manual_source:
            source=np.array(self.manual_source)
            if rec and 'source' in rec:source=retouch.source_point(rec,self.original_point([px,py]))
            elif self.manual_aligned.get() and self.manual_offset is not None:
                anchor=self.manual_anchor if self.manual_anchor is not None else (np.array(self.manual_source)-self.manual_offset).tolist()
                source=retouch.source_point(dict(self.manual_settings(),source=self.manual_source,points=[anchor]),self.original_point([px,py]))
            from liquify_guides import project
            projected,valid=project(source[None].astype(np.float32),self.document.rgb.shape[:2],self.reshape_cache,self.face_settings,self.liquify_state if self.liquify_active() else None)
            if not valid[0]:return
            sx,sy=self.view.to_canvas(*projected[0],self.size())
            for color,width in [('#202b3c',3),('#ffffff',1)]:
                self.canvas.create_line(sx-7,sy,sx+7,sy,fill=color,width=width,tags='tool_cursor');self.canvas.create_line(sx,sy-7,sx,sy+7,fill=color,width=width,tags='tool_cursor')
