"""Manual liquify interaction and visible-crop preview for the portrait workspace."""
import time,tkinter as tk
from tkinter import ttk
import numpy as np,cv2
from PIL import Image
from dark_ui import Section,ToolButton,COLORS
from photo_document import to_uint8
import liquify,face_reshape

LABELS={'push':'向前变形','bloat':'膨胀','pucker':'褶皱 / 收缩','restore':'重建','freeze':'冻结','thaw':'解冻','twirl':'旋转','smooth':'平滑','nodes':'身体 / 节点','push_left':'左推','face':'脸部智能'}

class LiquifyUI:
    def init_liquify(self):
        self.liquify_state=None;self.liquify_input=None;self.liquify_timer=None
        self.liquify_enabled=tk.BooleanVar(value=False);self.liquify_protection=tk.BooleanVar(value=True)
        self.liquify_radius=tk.DoubleVar(value=150);self.liquify_strength=tk.DoubleVar(value=50)
        self.liquify_density=tk.DoubleVar(value=50);self.liquify_rate=tk.DoubleVar(value=50)
    def build_liquify_panel(self,panel):
        section=Section(panel,'手动液化',opened=False);self.liquify_panel=section;body=section.body
        check=ttk.Checkbutton(body,text='显示画笔液化 · 智能参数独立生效',variable=self.liquify_enabled,command=self.toggle_liquify)
        check.pack(anchor='w',pady=5);self.controls.append(check)
        for tools in (('push','restore','smooth'),('pucker','bloat','push_left'),('freeze','thaw','face'),('twirl','nodes')):
            row=ttk.Frame(body);row.pack(fill='x',pady=3)
            for name in tools:
                key='liquify_'+name
                short={'push':'向前','pucker':'褶皱','nodes':'节点','face':'脸部'}
                button=ToolButton(row,short.get(name,LABELS[name]),key,lambda key=key:self.toggle_tool(key))
                button.pack(side='left',expand=True,fill='x',padx=1);self.tool_buttons[key]=button;self.controls.append(button)
        self.controls.append(self.slider(body,'笔刷半径 / 原图像素',self.liquify_radius,5,1000,self.draw_tool_cursor,mutating=False))
        self.liquify_strength_control=self.slider(body,'笔刷强度',self.liquify_strength,0,100,lambda:None,mutating=False)
        self.controls.append(self.liquify_strength_control)
        self.controls.append(self.slider(body,'笔刷密度 / 边缘',self.liquify_density,0,100,self.draw_tool_cursor,mutating=False))
        self.liquify_rate_control=self.slider(body,'累积速度（按住）',self.liquify_rate,0,100,lambda:None,mutating=False)
        self.controls.append(self.liquify_rate_control)
        ttk.Checkbutton(body,text='显示冻结保护',variable=self.liquify_protection,command=self.draw).pack(anchor='w',pady=5)
        self.build_guide_controls(body)
        self.button(body,'恢复画笔形变',self.reset_liquify)
        self.button(body,'清除冻结保护',self.clear_liquify_protection)
        row=ttk.Frame(body);row.pack(fill='x',pady=5)
        for title,command in [('撤销',self.undo),('重做',self.redo),('浏览',lambda:self.select_tool('pan'))]:
            b=ttk.Button(row,text=title,command=command);b.pack(side='left',expand=True,fill='x',padx=1);self.controls.append(b)
        self.build_smart_face_controls(body)
        ttk.Label(body,text='向前变形拖动推拉。左推：上拖向左、下拖向右，Alt 反向。膨胀、褶皱、旋转、重建可按住累积；旋转 Alt 反向。\n重建还原画笔形变；平滑整理形变，不磨皮。密度控制边缘软硬，速度控制按住的累积。\nCtrl＋滚轮调大小 · 空格平移',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=6)
        ttk.Label(body,text='液化作用于整张照片，保存到本图项目；美颜配置不携带液化。若继续编辑原图选区或取样，请暂时关闭液化。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=3)
    def liquify_active(self):return self.liquify_enabled.get() and liquify.active(self.liquify_state)
    def sync_liquify_ui(self):
        if not hasattr(self,'liquify_rate_control'):return
        mode=self.mode.get()
        active=self.document is not None and not self.busy and mode in ('liquify_bloat','liquify_pucker','liquify_twirl','liquify_smooth','liquify_restore')
        self.liquify_rate_control.configure(state='normal' if active else 'disabled')
        self.liquify_strength_control.configure(state='normal' if self.document is not None and not self.busy and mode not in ('liquify_nodes','liquify_face') else 'disabled')
        self.sync_guide_controls()
        self.sync_smart_face_ui()
    def liquify_settings(self):
        return {'enabled':bool(self.liquify_enabled.get()),'radius':float(self.liquify_radius.get()),'strength':float(self.liquify_strength.get()),'density':float(self.liquify_density.get()),'rate':float(self.liquify_rate.get()),'guide_face':bool(self.liquify_guide_face.get()),'guide_body':bool(self.liquify_guide_body.get()),'fix_nodes':bool(self.liquify_fix_nodes.get())}
    def toggle_liquify(self):
        if self.busy:return
        if self.drag and self.drag['mode'].startswith('liquify_'):self.finish_liquify()
        self.render_liquify();self.record('启用液化' if self.liquify_enabled.get() else '暂时关闭液化')
    def render_liquify(self):
        if self.liquify_input is None:return
        self.output_float=liquify.apply(self.liquify_input,self.liquify_state) if self.liquify_enabled.get() else self.liquify_input
        self.output=to_uint8(self.output_float);self.make_navigation();self.draw_histogram();self.draw()
    def reset_liquify(self):
        if self.busy or self.liquify_state is None:return
        self.liquify_state['flow'].fill(0);self.render_liquify();self.sync_liquify_ui();self.record('恢复画笔形变')
    def clear_liquify_protection(self):
        if self.busy or self.liquify_state is None:return
        self.liquify_state['freeze'].fill(0);self.draw();self.sync_liquify_ui();self.record('清除冻结保护')
    def start_liquify(self,event,erase=False):
        if self.mode.get() in ('liquify_nodes','liquify_face') and not erase:self.start_liquify_node(event);return
        if self.shape_pending():self.status.set('请等待面部重塑完成，再进行手动液化。');return
        p=self.point(event);h,w=self.document.rgb.shape[:2]
        if not (0<=p[0]<w and 0<=p[1]<h):return
        self.commit_edit('液化前')
        if self.liquify_state is None:self.liquify_state=liquify.create((h,w))
        self.liquify_enabled.set(True)
        self.liquify_preview_factor=min(1,max(.05,self.view.scale))
        h,w=self.liquify_input.shape[:2]
        self.liquify_preview=to_uint8(cv2.resize(self.liquify_input,(max(1,round(w*self.liquify_preview_factor)),max(1,round(h*self.liquify_preview_factor))),interpolation=cv2.INTER_AREA) if self.liquify_preview_factor<1 else self.liquify_input)
        mode='liquify_restore' if erase else self.mode.get()
        self.drag={'mode':mode,'last':p,'r':float(self.liquify_radius.get()),'strength':float(self.liquify_strength.get()),'density':float(self.liquify_density.get()),'rate':float(self.liquify_rate.get()),'reverse':bool(event.state&(0x0008|0x20000)),'changed':False,'time':time.monotonic()}
        self.update_liquify(p,initial=True);self.liquify_timer=self.root.after(60,self.liquify_tick)
    def update_liquify(self,p,initial=False):
        d=self.drag
        if not d or not d['mode'].startswith('liquify_'):return
        if d['mode']=='liquify_node':self.update_liquify_node(p);return
        now=time.monotonic();elapsed=max(0,min(.3,now-d['time']));d['time']=now
        tool=d['mode'][8:]
        dose=(1 if initial else elapsed/.06)*d['rate']/50 if tool in ('bloat','pucker','twirl','smooth','restore') else None
        changed=liquify.stroke(self.liquify_state,d['last'],p,d['r'],d['strength'],tool,density=d['density'],dose=dose,reverse=d['reverse'])
        d['last']=p;d['changed']|=changed
        if changed:self.draw()
        else:self.draw_tool_cursor()
    def liquify_tick(self):
        d=self.drag
        if d and d['mode'].startswith('liquify_'):
            if d['mode'] not in ('liquify_push','liquify_push_left','liquify_node'):self.update_liquify(d['last'])
            self.liquify_timer=self.root.after(60,self.liquify_tick)
    def finish_liquify(self):
        d=self.drag
        if self.liquify_timer:self.root.after_cancel(self.liquify_timer);self.liquify_timer=None
        self.drag=None;self.render_liquify();self.sync_liquify_ui()
        if d and d['changed']:self.record('液化 · '+(d['label'] if d['mode']=='liquify_node' else LABELS[d['mode'][8:]]))
    def display_rgb(self,bounds):
        if self.drag and self.drag['mode'].startswith('liquify_') and self.liquify_input is not None:
            return to_uint8(liquify.crop(self.liquify_input,self.liquify_state,bounds))
        a,b,c,d=bounds;return self.output[b:d,a:c].copy()
    def fast_display(self,bounds,size,localcut):
        # Match the screen pixel centres, not the full-resolution crop size.
        a,b,c,d=bounds;pw,ph=size
        x,y=np.meshgrid(a+(np.arange(pw,dtype=np.float32)+.5)*(c-a)/pw-.5,b+(np.arange(ph,dtype=np.float32)+.5)*(d-b)/ph-.5)
        sx,sy=liquify.spacing(self.liquify_state)
        delta=cv2.remap(self.liquify_state['flow'],x/sx,y/sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        # A cached reduced source avoids aliasing at fit zoom. Its coordinates
        # remain those of the full image; it is never written back to output.
        source=self.liquify_preview;factor=self.liquify_preview_factor
        rgb=cv2.remap(source,(x+delta[:,:,0]+.5)*factor-.5,(y+delta[:,:,1]+.5)*factor-.5,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        cut=int(round(localcut*pw/(c-a)))
        if cut:
            original=cv2.remap(self.session.original,x[:,:cut],y[:,:cut],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101);rgb[:,:cut]=original
        if self.liquify_protection.get() and np.any(self.liquify_state['freeze']):
            alpha=cv2.remap(self.liquify_state['freeze'],x/sx,y/sy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)*.45
            alpha[:,:cut]=0;rgb=np.rint(rgb*(1-alpha[:,:,None])+np.asarray([48,174,244])*alpha[:,:,None]).astype(np.uint8)
        return Image.fromarray(rgb)
    def decorate_display(self,rgb,bounds,localcut):
        if self.liquify_state is not None and self.liquify_protection.get() and self.mode.get().startswith('liquify_'):
            alpha=liquify.freeze_crop(self.liquify_state,bounds)*.45
            alpha[:,:localcut]=0
            rgb[:]=np.rint(rgb*(1-alpha[:,:,None])+np.asarray([48,174,244])*alpha[:,:,None]).astype(np.uint8)
    def mask_for_display(self,mask,bounds,localcut=0):
        if not self.liquify_active():return super().mask_for_display(mask,bounds,localcut)
        h,w=mask.shape
        source=face_reshape.display_mask(mask,self.reshape_cache,self.face_settings,(0,0,w,h))
        x,y,_=liquify.maps(self.liquify_state,bounds)
        result=cv2.remap(source.astype(np.uint8),x,y,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)>0
        if localcut:
            a,b,c,d=bounds;result[:,:localcut]=mask[b:d,a:a+localcut]
        return result
