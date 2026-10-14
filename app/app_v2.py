"""Offline portrait AI, cursor-anchored zoom and manual selection review."""
import sys,threading,queue,traceback,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import numpy as np
from PIL import Image,ImageTk
from core import ROOT,load_photo,save_photo
from damo_engine import PortraitAISession,inpaint_portrait
from ai_engine import blend_repair
from editing import Viewport,Selection
from complexion import recommend,render_skin,small_blemishes

class App:
    def __init__(self,root):
        self.root=root;self.session=None;self.selection=None;self.path=None;self.output=None
        self.generated=None;self.done_mask=None;self.meta={};self.jobs=queue.Queue();self.busy=False;self.cancel=threading.Event()
        self.defaults={};self.recommendation={};self.small_mask=None
        self.view=Viewport();self.drag=None;self.space=False;self.controls=[];self.smooth_cache=None
        root.title('本地人像美颜 v0.2 · AI识别与修复');root.geometry('1380x930');root.minsize(980,700)
        ttk.Style().theme_use('clam')
        top=ttk.Frame(root,padding=12);top.pack(fill='x')
        ttk.Label(top,text='本地人像美颜 v0.2',font=('Microsoft YaHei UI',18,'bold')).pack(side='left')
        ttk.Label(top,text='离线 AI 识别与修复',foreground='#52656a').pack(side='left',padx=18)
        self.openbutton=ttk.Button(top,text='打开照片',command=self.choose);self.openbutton.pack(side='right',padx=6)
        self.savebutton=ttk.Button(top,text='导出新副本',command=self.export);self.savebutton.pack(side='right')
        self.controls.extend([self.openbutton,self.savebutton])
        body=ttk.Frame(root,padding=(12,0));body.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(body,background='#1b2428',highlightthickness=0);self.canvas.pack(side='left',fill='both',expand=True)
        side=ttk.Frame(body,width=335);side.pack(side='right',fill='y');side.pack_propagate(False)
        scroll=tk.Canvas(side,highlightthickness=0,width=310);scroll.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(side,orient='vertical',command=scroll.yview);bar.pack(side='right',fill='y');scroll.configure(yscrollcommand=bar.set)
        panel=ttk.Frame(scroll,padding=14);window=scroll.create_window(0,0,window=panel,anchor='nw')
        panel.bind('<Configure>',lambda e:scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>',lambda e:scroll.itemconfigure(window,width=e.width))
        self.smooth=tk.DoubleVar(value=0);self.repair=tk.DoubleVar(value=100);self.split=tk.DoubleVar(value=0)
        self.whiten=tk.DoubleVar(value=0);self.texture=tk.DoubleVar(value=50)
        self.threshold=tk.DoubleVar(value=.35);self.radius=tk.IntVar(value=5);self.overlay=tk.BooleanVar(value=True);self.mode=tk.StringVar(value='circle')
        self.zoomlabel=tk.StringVar(value='缩放 100%');self.summary=tk.StringVar(value='打开照片后自动识别并修复。')
        def label(text):ttk.Label(panel,text=text,wraplength=290).pack(anchor='w',pady=(12,4))
        def button(text,fn):
            b=ttk.Button(panel,text=text,command=fn);b.pack(fill='x',pady=4);self.controls.append(b);return b
        label('自动识别优先');ttk.Label(panel,textvariable=self.summary,wraplength=285,foreground='#52656a').pack(anchor='w')
        button('重新 AI 识别（保留手动补选 / 排除）',self.scan)
        label('检测阈值：降低可增加候选')
        scale=ttk.Scale(panel,from_=.15,to=.65,variable=self.threshold);scale.pack(fill='x');self.controls.append(scale)
        self.thresholdlabel=ttk.Label(panel,text='当前阈值 0.35');self.thresholdlabel.pack(anchor='e')
        self.threshold.trace_add('write',lambda *_:self.thresholdlabel.configure(text=f'当前阈值 {self.threshold.get():.2f} · 点击重新识别生效'))
        self.repairbutton=button('AI 修复当前选区',self.run_repair)
        button('恢复 AI 推荐参数',self.apply_defaults)
        for text,var in [('祛痘：修复明显痘点',self.repair),('磨皮：柔化细小不平整',self.smooth),('美白：提亮皮肤',self.whiten),('纹理：50保留 / 更高增强',self.texture),('前后分界：左原图 / 右结果',self.split)]:
            row=ttk.Frame(panel);row.pack(fill='x',pady=(8,2));ttk.Label(row,text=text).pack(side='left')
            value=tk.StringVar();value.set(f'{var.get():.0f}');ttk.Label(row,textvariable=value).pack(side='right')
            var.trace_add('write',lambda *_,v=var,labelvar=value:labelvar.set(f'{v.get():.0f}'))
            s=ttk.Scale(panel,from_=0,to=100,variable=var,command=(lambda v:self.draw()) if var is self.split else (lambda v:self.refresh()));s.pack(fill='x')
            if var is not self.split:self.controls.append(s)
        ttk.Checkbutton(panel,text='显示修复选区',variable=self.overlay,command=self.draw).pack(anchor='w',pady=8)
        label('视图');row=ttk.Frame(panel);row.pack(fill='x')
        for text,fn in [('全图',self.fit),('面部',self.facefit),('1:1',self.actual)]:ttk.Button(row,text=text,command=fn,width=7).pack(side='left',padx=2)
        ttk.Label(panel,textvariable=self.zoomlabel).pack(anchor='w',pady=4)
        ttk.Label(panel,text='滚轮：以鼠标位置缩放\n空格 + 拖动 / 中键：移动画面',wraplength=285,foreground='#52656a').pack(anchor='w')
        label('补选漏点 / 排除误检');row=ttk.Frame(panel);row.pack(fill='x')
        for text,value in [('圈选','circle'),('画笔','brush'),('橡皮','erase'),('移动','pan')]:
            b=ttk.Radiobutton(row,text=text,variable=self.mode,value=value);b.pack(side='left');self.controls.append(b)
        label('画笔 / 点击圈选半径（原图像素）')
        spin=ttk.Spinbox(panel,from_=1,to=100,textvariable=self.radius,width=10);spin.pack(anchor='w');self.controls.append(spin)
        ttk.Label(panel,text='圈选：点击一个痘点，或从中心向外拖动\n画笔：按住左键涂抹；右键随时擦除\n橙色为 AI 候选，蓝色为手动补选',wraplength=285,foreground='#52656a').pack(anchor='w',pady=8)
        row=ttk.Frame(panel);row.pack(fill='x')
        for text,fn in [('撤销',self.undo),('重做',self.redo)]:
            b=ttk.Button(row,text=text,command=fn);b.pack(side='left',fill='x',expand=True,padx=2);self.controls.append(b)
        button('恢复自动选区（清除手动修改）',self.reset)
        ttk.Label(panel,text='打开照片即生成推荐美颜版本。参数由 AI 检测结果与皮肤亮度、粗糙度估算，可手动调整。\n模型仍可能选到痣或雀斑。\nJPEG / PNG / 8位 TIFF；RAW 请从 Lr 导出。',wraplength=285,foreground='#52656a').pack(anchor='w',pady=16)
        def scroll_panel(event):scroll.yview_scroll(-int(event.delta/120),'units');return 'break'
        def bind_panel(widget):
            widget.bind('<MouseWheel>',scroll_panel)
            for child in widget.winfo_children():bind_panel(child)
        bind_panel(panel);scroll.bind('<MouseWheel>',scroll_panel)
        bottom=ttk.Frame(root,padding=10);bottom.pack(fill='x')
        self.status=tk.StringVar(value='打开照片开始。检测、皮肤分割和修复均在本机完成。')
        ttk.Label(bottom,textvariable=self.status,wraplength=1120).pack(side='left',fill='x',expand=True)
        self.cancelbutton=ttk.Button(bottom,text='取消处理',command=self.cancel.set,state='disabled');self.cancelbutton.pack(side='right')
        self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<ButtonPress-3>',lambda e:self.press(e,True));self.canvas.bind('<B3-Motion>',self.motion);self.canvas.bind('<ButtonRelease-3>',self.release)
        self.canvas.bind('<ButtonPress-2>',lambda e:self.press(e,pan=True));self.canvas.bind('<B2-Motion>',self.motion);self.canvas.bind('<ButtonRelease-2>',self.release)
        root.bind('<KeyPress-space>',self.space_down);root.bind('<KeyRelease-space>',lambda e:setattr(self,'space',False))
        root.bind('<Control-z>',lambda e:self.undo());root.bind('<Control-y>',lambda e:self.redo())
        self.enable();root.after(80,self.poll)
    def size(self):return max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
    def enable(self):
        for control in self.controls:control.configure(state='disabled' if self.busy else 'normal')
        if not self.session:self.savebutton.configure(state='disabled');self.repairbutton.configure(state='disabled')
        self.cancelbutton.configure(state='normal' if self.busy else 'disabled')
    def choose(self):
        path=filedialog.askopenfilename(filetypes=[('照片','*.jpg *.jpeg *.png *.tif *.tiff')])
        if path:self.open(path)
    def progress(self,text):self.jobs.put(('progress',text,None))
    def work(self,fn,ready,cancellable=True):
        if self.busy:return
        self.busy=True;self.cancel.clear();self.enable()
        if not cancellable:self.cancelbutton.configure(state='disabled')
        def worker():
            try:
                result=fn()
                if self.cancel.is_set():raise RuntimeError('已取消，保留此前状态。')
                self.jobs.put((ready,result,None))
            except Exception as e:self.jobs.put((ready,None,(str(e),traceback.format_exc())))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        try:
            while True:
                cb,result,error=self.jobs.get_nowait()
                if cb=='progress':self.status.set(result);continue
                self.busy=False
                if error:
                    (ROOT/'error.log').write_text(error[1],encoding='utf8');self.status.set(error[0])
                    automation=getattr(self,'automation',None)
                    remote=automation.report_error(error[0]) if automation else False
                    if not self.cancel.is_set() and not remote:
                        recover=getattr(cb,'on_error',None)
                        try:handled=recover(error[0]) if recover else False
                        except Exception as recovery_error:
                            (ROOT/'error.log').write_text(error[1]+'\nRAW recovery UI:\n'+traceback.format_exc(),encoding='utf8')
                            self.status.set(str(recovery_error));handled=False
                        if not handled:messagebox.showerror('处理失败',error[0])
                else:
                    try:cb(result)
                    except Exception as e:
                        (ROOT/'error.log').write_text(traceback.format_exc(),encoding='utf8');self.status.set(str(e))
                        automation=getattr(self,'automation',None)
                        if not automation or not automation.report_error(str(e)):messagebox.showerror('显示失败',str(e))
                self.enable()
        except queue.Empty:pass
        self.root.after(80,self.poll)
    def open(self,path):
        self.status.set('读取照片并加载本地 AI 模型…');threshold=float(self.threshold.get())
        def job():
            t=time.perf_counter();s=PortraitAISession(load_photo(path),threshold,self.progress)
            small,_=small_blemishes(s)
            out,meta=inpaint_portrait(s.original,(s.ai_auto_mask>0)&~(small>0),self.progress,self.cancel)
            meta['elapsed_seconds']=round(time.perf_counter()-t,2);return s,out,meta
        def ready(result):
            self.session,self.generated,self.meta=result;self.path=Path(path);self.selection=Selection(self.session.ai_auto_mask)
            self.done_mask=self.selection.mask.copy();self.smooth_cache=None
            self.small_mask,_=small_blemishes(self.session);self.defaults,self.recommendation=recommend(self.session)
            self.apply_defaults()
            self.fit();self.refresh()
        self.work(job,ready)
    def scan(self):
        if not self.session or self.busy:return
        threshold=float(self.threshold.get());s=self.session
        def job():s.scan_ai(threshold,self.progress);return s.ai_auto_mask.copy()
        def ready(mask):
            self.selection.rescan(mask);self.small_mask,_=small_blemishes(s);self.defaults,self.recommendation=recommend(s);self.refresh()
        self.work(job,ready)
    def run_repair(self):
        if not self.session or self.busy:return
        mask=self.selection.mask.copy();rgb=self.session.original
        # Manual repair can also explicitly repair small marks with the network.
        def ready(result):self.generated,self.meta=result;self.done_mask=mask;self.small_mask=np.zeros(mask.shape,np.uint8);self.refresh()
        self.work(lambda:inpaint_portrait(rgb,mask,self.progress,self.cancel),ready)
    def refresh(self):
        if not self.session:return
        strength=round(self.smooth.get())
        accepted=self.selection.mask if self.done_mask is None else self.selection.mask&(self.done_mask>0)
        repaired=blend_repair(self.session.original,self.session.original,self.generated,accepted,self.repair.get())
        small=None if self.small_mask is None else (self.small_mask>0)&self.selection.mask
        self.output=render_skin(repaired,self.session,strength,self.whiten.get(),self.texture.get(),small)
        pending=self.selection.pending(self.done_mask);n=len(self.session.spots)
        self.summary.set(f'{len(self.session.faces)} 张脸 · {n} 处 AI 候选\n'+('有新增选区待 AI 修复' if pending else '当前选区已完成 AI 修复'))
        self.status.set(f'{self.path.name} | AI 候选 {n} 处 | 祛痘 {self.repair.get():.0f} · 磨皮 {strength} · 美白 {self.whiten.get():.0f} · 纹理 {self.texture.get():.0f}'+(' | 新选区待 AI 修复' if pending else ' | 参数可手动微调'))
        self.draw()
    def apply_defaults(self):
        if not self.defaults or self.busy:return
        for name,value in self.defaults.items():getattr(self,name).set(value)
        self.refresh()
    def fit(self):
        if not self.session:return
        h,w=self.session.original.shape[:2];self.view.fit((0,0,w,h),self.size());self.draw()
    def facefit(self):
        if not self.session or not self.session.faces:return
        f=max(self.session.faces,key=lambda f:f.width);a,b,c,d=f.box;p=f.width*.15
        self.view.fit((a-p,b-p,c+p,d+p),self.size());self.draw()
    def actual(self):
        if self.session:self.view.scale=1;self.draw()
    def space_down(self,event):
        if not isinstance(self.root.focus_get(),(tk.Entry,ttk.Entry,ttk.Spinbox)):self.space=True
    def wheel(self,event):
        if not self.session:return
        self.view.zoom(1.2**(event.delta/120),event.x,event.y,self.size());self.draw();return 'break'
    def point(self,event):return self.view.to_image(event.x,event.y,self.size())
    def brushradius(self):
        try:return max(1,min(100,int(self.radius.get())))
        except (ValueError,tk.TclError):return 5
    def press(self,event,erase=False,pan=False):
        if not self.session:return
        self.canvas.focus_set();p=self.point(event);moving=pan or self.space or self.mode.get()=='pan'
        if moving:self.drag={'mode':'pan','screen':(event.x,event.y)};return
        if self.busy:return
        h,w=self.selection.mask.shape
        if not(0<=p[0]<w and 0<=p[1]<h):return
        mode='erase' if erase else self.mode.get();self.selection.checkpoint();self.drag={'mode':mode,'start':p,'last':p,'r':self.brushradius()}
        if mode!='circle':self.selection.stroke(p,p,self.drag['r'],mode=='erase');self.refresh()
    def motion(self,event):
        if not self.drag:return
        d=self.drag;p=self.point(event)
        if d['mode']=='pan':
            x,y=d['screen'];self.view.pan(event.x-x,event.y-y);d['screen']=(event.x,event.y);self.draw();return
        if d['mode']=='circle':
            self.draw();sx,sy=self.view.to_canvas(*d['start'],self.size());r=max(d['r'],np.hypot(p[0]-d['start'][0],p[1]-d['start'][1]))*self.view.scale
            self.canvas.create_oval(sx-r,sy-r,sx+r,sy+r,outline='#5bc8ff',width=2,tags='draft')
        else:self.selection.stroke(d['last'],p,d['r'],d['mode']=='erase');self.draw()
        d['last']=p
    def release(self,event):
        if not self.drag:return
        d=self.drag
        if d['mode']=='circle':
            p=self.point(event);r=max(d['r'],round(np.hypot(p[0]-d['start'][0],p[1]-d['start'][1])))
            self.selection.stroke(d['start'],d['start'],r);self.refresh()
        self.drag=None;self.refresh()
    def undo(self):
        if self.selection and not self.busy and self.selection.undo():self.refresh()
    def redo(self):
        if self.selection and not self.busy and self.selection.redo():self.refresh()
    def reset(self):
        if self.selection and not self.busy:self.selection.reset();self.refresh()
    def draw(self):
        if self.session is None or self.output is None:return
        cw,ch=self.size();h,w=self.output.shape[:2];s=self.view.scale
        a=max(0,int(np.floor(self.view.cx-cw/(2*s))));b=max(0,int(np.floor(self.view.cy-ch/(2*s))))
        c=min(w,int(np.ceil(self.view.cx+cw/(2*s))));d=min(h,int(np.ceil(self.view.cy+ch/(2*s))))
        self.canvas.delete('all');self.zoomlabel.set(f'缩放 {s*100:.0f}%')
        if a>=c or b>=d:return
        splitx=cw*self.split.get()/100
        cut=round(self.view.to_image(splitx,0,(cw,ch))[0]);localcut=int(np.clip(cut-a,0,c-a))
        display_size=(max(1,round((c-a)*s)),max(1,round((d-b)*s)))
        gpu_image=None
        try:
            from gpu_render import viewport
            gpu_image=viewport(self,(a,b,c,d),display_size,localcut)
        except Exception as error:
            from gpu_render import record_cpu_recovery
            record_cpu_recovery('画布呈现',error)
        if gpu_image is not None:
            im=gpu_image
        elif getattr(self,'_preview_frame',None) is not None:
            im=self.color_preview_display((a,b,c,d),display_size,localcut)
        elif self.mode.get().startswith('beauty_') and hasattr(self,'fast_beauty_display') and getattr(self,'feature_compare_output',None) is None:
            im=self.fast_beauty_display((a,b,c,d),display_size,localcut)
        elif self.drag and self.drag['mode'].startswith('retouch_') and getattr(self,'manual_preview',None) is not None:
            im=self.fast_manual_display((a,b,c,d),display_size,localcut)
        elif self.drag and self.drag['mode'].startswith('liquify_') and hasattr(self,'fast_display'):
            im=self.fast_display((a,b,c,d),display_size,localcut)
        elif getattr(self,'mask_overlay',None) is not None and self.mask_overlay.get() and 0<=self.active_layer<len(self.region_layers) and self.region_layers[self.active_layer].get('color_process',1)==2 and hasattr(self,'fast_local_display'):
            im=self.fast_local_display((a,b,c,d),display_size,localcut)
        else:
            rgb=self.display_rgb((a,b,c,d)) if hasattr(self,'display_rgb') else self.output[b:d,a:c].copy()
            rgb[:,:localcut]=self.session.original[b:d,a:a+localcut]
            view_mask=lambda mask:self.mask_for_display(mask,(a,b,c,d),localcut) if hasattr(self,'mask_for_display') else mask[b:d,a:c]
            if getattr(self,'mask_overlay',None) is not None and self.mask_overlay.get() and 0<=self.active_layer<len(self.region_layers):
                from smart_selection import refine
                layer=self.region_layers[self.active_layer];selected=view_mask(refine(layer['mask'],layer['parameters'].get('expand',0)))
                rgb[selected]=np.rint(rgb[selected]*.4+np.array([155,110,235])*.6).astype(np.uint8)
            elif self.overlay.get():
                selected=view_mask(self.selection.mask);automatic=view_mask(self.selection.auto);auto=selected&automatic;manual=selected&~auto
                layers=[(auto,[255,156,40]),(manual,[60,190,255])]
                if getattr(self,'show_excluded',False):layers.append((automatic&~selected,[239,102,116]))
                for mask,color in layers:rgb[mask]=np.rint(rgb[mask]*.38+np.array(color)*.62).astype(np.uint8)
            if hasattr(self,'decorate_display'):self.decorate_display(rgb,(a,b,c,d),localcut)
            im=Image.fromarray(rgb).resize((max(1,round((c-a)*s)),max(1,round((d-b)*s))),Image.Resampling.LANCZOS)
        self.photo=ImageTk.PhotoImage(im);x,y=self.view.to_canvas(a,b,(cw,ch));self.canvas.create_image(x,y,anchor='nw',image=self.photo)
        if 0<self.split.get()<100:self.canvas.create_line(splitx,0,splitx,ch,fill='white',width=1)
        self.canvas.create_text(12,12,anchor='nw',text=getattr(self,'selection_legend','橙：AI 选区 / 蓝：手动补选') if self.overlay.get() else '左原图 / 右结果' if self.split.get()>0 else '修复结果',fill='white',font=('Microsoft YaHei UI',11))
    def export(self):
        if not self.session or self.busy:return
        if self.selection.pending(self.done_mask):messagebox.showinfo('有选区尚未修复','请先点击「AI 修复当前选区」，再导出。');return
        path=filedialog.asksaveasfilename(initialdir=str(self.path.parent),initialfile=self.path.stem+'-AI自然美颜.png',defaultextension='.png',filetypes=[('PNG 无损','*.png'),('JPEG','*.jpg'),('TIFF 8位','*.tif')])
        if not path:return
        rgb=self.output.copy()
        def ready(_):self.status.set('已导出新副本：'+path)
        self.work(lambda:save_photo(path,rgb),ready,cancellable=False)

def main():
    root=tk.Tk();app=App(root)
    if len(sys.argv)>1:
        path=next(ROOT.parent.rglob('DSC05501-cinema-texture.jpg')) if sys.argv[1]=='--demo' else sys.argv[1]
        root.after(250,lambda:app.open(path))
    root.mainloop()
if __name__=='__main__':main()
