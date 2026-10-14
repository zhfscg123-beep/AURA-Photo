"""Native direct-manipulation controls; numeric alternatives share the recipe."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image, ImageTk
import color_science as cs
from dark_ui import COLORS
from dpi_support import dp,ui_font


class GradingWheel(ttk.Frame):
    def __init__(self,parent,app,name,compact=False):
        super().__init__(parent);self.pack(fill='x');self.app=app;self.name=name;self.dragging=False;self.enabled=True;self.image_key=None
        self.hue=app.creative_vars[name+'_hue'];self.saturation=app.creative_vars[name+'_color']
        self.canvas=tk.Canvas(self,width=dp(app.root,90 if compact else 180),height=dp(app.root,104 if compact else 160),bg=COLORS['panel'],highlightthickness=0,takefocus=1);self.canvas.pack(fill='x')
        self.canvas._aura_managed_geometry=True
        self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        for key in ('Left','Right','Up','Down'):self.canvas.bind('<'+key+'>',self.key)
        self.canvas.bind('<FocusIn>',lambda e:self.draw());self.canvas.bind('<FocusOut>',lambda e:self.draw())
        self.hue.trace_add('write',lambda *_:self.draw());self.saturation.trace_add('write',lambda *_:self.draw())
        if not compact:ttk.Label(self,text='色轮中心为中性 · 左右键色相 · 上下键强度',style='Muted.TLabel',wraplength=300).pack(fill='x')
        app.controls.append(self)
    def configure(self,cnf=None,**kw):
        if 'state' in kw:self.enabled=kw.pop('state')!='disabled'
        return super().configure(cnf,**kw)
    def geometry(self):
        return self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,min(self.canvas.winfo_width(),self.canvas.winfo_height())/2-dp(self.app.root,9)
    def draw(self):
        if not self.canvas.winfo_exists():return
        c=self.canvas;cx,cy,r=self.geometry();r=max(12,int(r));key=(r,self.app.root._ui_scale)
        if self.image_key!=key:
            yy,xx=np.mgrid[-r:r+1,-r:r+1].astype(np.float32);distance=np.sqrt(xx*xx+yy*yy)/r
            lab=np.stack([np.full_like(xx,.72),xx/r*.17,-yy/r*.17],2)
            rgb=np.clip(cs.encode(cs.oklab_rgb(lab))*255,0,255).astype(np.uint8);rgb[distance>1]=[255,255,255]
            self.photo=ImageTk.PhotoImage(Image.fromarray(rgb));self.image_key=key
        c.delete('all');c.create_image(cx,cy,image=self.photo)
        angle=np.deg2rad(self.hue.get());radius=r*self.saturation.get()/100;x=cx+np.cos(angle)*radius;y=cy-np.sin(angle)*radius
        c.create_oval(cx-r,cy-r,cx+r,cy+r,outline=COLORS['muted'])
        c.create_oval(x-5,y-5,x+5,y+5,fill='white',outline=COLORS['text'],width=2)
        if c.focus_get() is c:c.create_rectangle(2,2,c.winfo_width()-2,c.winfo_height()-2,outline=COLORS['accent'],width=2)
    def position(self,e):
        cx,cy,r=self.geometry();x,y=e.x-cx,cy-e.y
        self.hue.set(float(np.rad2deg(np.arctan2(y,x))%360));self.saturation.set(float(np.clip(np.hypot(x,y)/max(1,r)*100,0,100)))
    def press(self,e):
        if not self.enabled or self.app.busy:return
        self.canvas.focus_set();self.app.commit_edit('色轮调整前');self.dragging=True;self.position(e)
    def motion(self,e):
        if self.dragging:self.position(e);self.app.preview_global_color()
    def release(self,e):
        if self.dragging:self.position(e);self.dragging=False;self.app.parameter_apply(self.app.color_changed);self.app.commit_edit('色轮调整')
    def key(self,e):
        if not self.enabled or self.app.busy:return 'break'
        self.app.commit_edit('色轮调整前')
        if e.keysym in ('Left','Right'):self.hue.set((self.hue.get()+(1 if e.keysym=='Right' else -1))%360)
        else:self.saturation.set(np.clip(self.saturation.get()+(1 if e.keysym=='Up' else -1),0,100))
        self.app.parameter_apply(self.app.color_changed);return 'break'


class ParametricCurve(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.pack(fill='x');self.app=app;self.selected=None;self.enabled=True;self.dragging=False
        self.canvas=tk.Canvas(self,height=dp(app.root,135),bg=COLORS['canvas'],highlightthickness=0,takefocus=1);self.canvas.pack(fill='x',pady=6);self.canvas._aura_managed_geometry=True
        self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        app.controls.append(self)
    def configure(self,cnf=None,**kw):
        if 'state' in kw:self.enabled=kw.pop('state')!='disabled'
        return super().configure(cnf,**kw)
    def draw(self):
        from develop_advanced import parametric_curve
        c=self.canvas;c.delete('all');w=max(80,c.winfo_width());h=c.winfo_height();pad=dp(self.app.root,16)
        xs=np.linspace(0,1,129,dtype=np.float32);values={k:v.get() for k,v in self.app.creative_vars.items()};ys=parametric_curve(xs,values)
        c.create_line(pad,h-pad,w-pad,pad,fill='#adb9ca',dash=(3,3))
        c.create_line(*np.stack([pad+xs*(w-2*pad),h-pad-ys*(h-2*pad)],1).ravel().tolist(),fill=COLORS['accent'],width=2)
        for i,key in enumerate(('curve_split_shadow','curve_split_mid','curve_split_highlight')):
            x=pad+values[key]/100*(w-2*pad);c.create_line(x,pad,x,h-pad,fill=COLORS['muted'],dash=(2,3));c.create_polygon(x-5,h-pad,x+5,h-pad,x,h-pad-8,fill=COLORS['accent'])
    def press(self,e):
        if not self.enabled or self.app.busy:return
        w=self.canvas.winfo_width();pad=dp(self.app.root,16)
        keys=('curve_split_shadow','curve_split_mid','curve_split_highlight');self.selected=min(keys,key=lambda k:abs(pad+self.app.creative_vars[k].get()/100*(w-2*pad)-e.x));self.app.commit_edit('参数曲线分界前');self.dragging=True;self.motion(e)
    def motion(self,e):
        if not self.dragging:return
        keys=('curve_split_shadow','curve_split_mid','curve_split_highlight');i=keys.index(self.selected);pad=dp(self.app.root,16)
        lo=1 if i==0 else self.app.creative_vars[keys[i-1]].get()+1;hi=99 if i==2 else self.app.creative_vars[keys[i+1]].get()-1
        self.app.creative_vars[self.selected].set(float(np.clip((e.x-pad)/max(1,self.canvas.winfo_width()-2*pad)*100,lo,hi)));self.draw()
    def release(self,e):
        if self.dragging:self.motion(e);self.dragging=False;self.app.parameter_apply(self.app.color_changed)
