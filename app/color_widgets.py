"""Native code color ramps and a compact HSV palette; no bitmap photo editing."""
import colorsys,tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image,ImageTk
from dark_ui import ParameterScale,COLORS
from dpi_support import dp,ui_font

def rgb_hex(rgb):return '#'+''.join(f'{max(0,min(255,round(v))):02X}' for v in rgb)
def hue_rgb(h,s=1,v=1):return tuple(round(x*255) for x in colorsys.hsv_to_rgb((h%360)/360,s,v))

class ColorParameterScale(ParameterScale):
    def __init__(self,*args,colors=None,**kw):
        self.ramp_colors=colors or ['#aebdce','#3169ec'];super().__init__(*args,**kw);self.pack_forget()
        self.bar=tk.Canvas(self.master,height=28,bg=COLORS['panel'],highlightthickness=0,takefocus=1)
        self.bar._aura_managed_geometry=True;self.bar.pack(side='left',fill='x',expand=True,padx=6)
        self.bar.bind('<Configure>',lambda e:self.paint());self.bar.bind('<FocusIn>',lambda e:self.paint());self.bar.bind('<FocusOut>',lambda e:self.paint())
        self.bar.bind('<ButtonPress-1>',self.press_bar);self.bar.bind('<B1-Motion>',self.move_bar);self.bar.bind('<ButtonRelease-1>',self.release_bar)
        self.bar.bind('<KeyPress>',self.key_bar);self.variable.trace_add('write',lambda *_:self.paint())
    def configure(self,cnf=None,**kw):
        result=super().configure(cnf,**kw)
        if hasattr(self,'bar'):self.bar.configure(state=str(self.cget('state')));self.paint()
        return result
    def set_colors(self,colors):self.ramp_colors=colors;self.paint()
    def paint(self):
        if not hasattr(self,'bar') or not self.bar.winfo_exists():return
        c=self.bar;c.configure(height=dp(c,28));c.delete('all');w=max(24,c.winfo_width());h=dp(c,28);pad=dp(c,8)
        colors=[np.array(c.winfo_rgb(v))/257 for v in self.ramp_colors]
        for x in range(pad,w-pad):
            t=(x-pad)/max(1,w-2*pad-1)*(len(colors)-1);i=min(len(colors)-2,int(t));color=colors[i]*(1-(t-i))+colors[i+1]*(t-i)
            c.create_line(x,h/2-dp(c,3),x,h/2+dp(c,3),fill=rgb_hex(color))
        x=pad+(w-2*pad)*np.clip((self.variable.get()-self.lo)/(self.hi-self.lo),0,1);r=dp(c,7)
        c.create_oval(x-r,h/2-r,x+r,h/2+r,fill='white',outline=COLORS['accent'] if str(self.cget('state'))!='disabled' else COLORS['muted'],width=dp(c,2))
        if c.focus_get() is c:c.create_rectangle(1,1,w-1,h-1,outline=COLORS['accent'],dash=(2,2))
    def set_at(self,x):
        pad=dp(self.bar,8);t=np.clip((x-pad)/max(1,self.bar.winfo_width()-2*pad),0,1);self.variable.set(round(self.lo+t*(self.hi-self.lo),self.decimals));self.changed(self.variable.get())
    def press_bar(self,e):
        if str(self.cget('state'))=='disabled':return 'break'
        self.bar.focus_set();self.start_drag();self.set_at(e.x);return 'break'
    def move_bar(self,e):
        if self.dragging:self.set_at(e.x)
        return 'break'
    def release_bar(self,e):
        if self.dragging:self.set_at(e.x);self.end_drag()
        return 'break'
    def key_bar(self,e):
        if str(self.cget('state'))=='disabled':return 'break'
        if e.keysym in ('Left','Right','Up','Down'):
            step=10**-self.decimals*(10 if e.state&1 else 1);self.variable.set(np.clip(self.variable.get()+step*(1 if e.keysym in ('Right','Up') else -1),self.lo,self.hi));self.changed(self.variable.get());self.key_release(e)
        elif e.keysym=='Home':self.variable.set(self.lo);self.dirty=True;self.commit()
        elif e.keysym=='End':self.variable.set(self.hi);self.dirty=True;self.commit()
        else:return
        return 'break'

class ColorPalette:
    def __init__(self,root,rgb,callback,title='选择颜色'):
        self.root=root;self.callback=callback;self.window=tk.Toplevel(root);self.window.title(title);self.window.transient(root)
        self.window.geometry(f'{min(dp(root,500),root.winfo_screenwidth()-32)}x{min(dp(root,520),root.winfo_screenheight()-70)}')
        self.h,self.s,self.v=colorsys.rgb_to_hsv(*[float(v)/255 for v in rgb]);self.hex=tk.StringVar();self.rgb_vars=[tk.StringVar() for _ in range(3)];self.input_kind='hex'
        f=ttk.Frame(self.window,padding=14);f.pack(fill='both',expand=True)
        self.plane=tk.Canvas(f,height=dp(root,220),highlightthickness=0);self.plane.pack(fill='both',expand=True)
        self.hue=tk.Canvas(f,height=dp(root,25),highlightthickness=0);self.hue.pack(fill='x',pady=8)
        for c,fn in ((self.plane,self.pick_sv),(self.hue,self.pick_hue)):
            c.bind('<Configure>',lambda e:self.paint());c.bind('<Button-1>',fn);c.bind('<B1-Motion>',fn)
        self.swatch=tk.Label(f,width=8,height=1);self.swatch.pack(fill='x',pady=3)
        row=ttk.Frame(f);row.pack(fill='x',pady=8);ttk.Label(row,text='HEX').pack(side='left');entry=ttk.Entry(row,textvariable=self.hex,width=10);entry.pack(side='left',padx=5);entry.bind('<Return>',self.from_hex)
        entry.bind('<FocusIn>',lambda e:setattr(self,'input_kind','hex'))
        for label,var in zip('RGB',self.rgb_vars):
            ttk.Label(row,text=label).pack(side='left');entry=ttk.Entry(row,textvariable=var,width=4);entry.pack(side='left',padx=3);entry.bind('<Return>',self.from_rgb)
            entry.bind('<FocusIn>',lambda e:setattr(self,'input_kind','rgb'))
        presets=ttk.Frame(f);presets.pack(fill='x')
        for color in ('#B4415F','#D26E82','#5F321E','#B47955','#D7AB96','#F0D6C7','#333333','#FFFFFF'):
            tk.Button(presets,bg=color,width=2,relief='flat',command=lambda c=color:self.set_hex(c)).pack(side='left',padx=3,pady=6)
        row=ttk.Frame(f);row.pack(fill='x');ttk.Button(row,text='应用颜色',command=self.apply).pack(side='right');ttk.Button(row,text='取消',command=self.window.destroy).pack(side='right',padx=6)
        self.error=ttk.Label(f,text='',foreground='#b94747');self.error.pack(anchor='w');self.paint()
    def rgb(self):return hue_rgb(self.h*360,self.s,self.v)
    def update_fields(self):
        rgb=self.rgb();self.hex.set(rgb_hex(rgb))
        for var,value in zip(self.rgb_vars,rgb):var.set(str(value))
        self.swatch.configure(bg=rgb_hex(rgb),text=rgb_hex(rgb),fg='white' if sum(rgb)<360 else '#202b3c')
    def paint(self):
        if not self.window.winfo_exists():return
        w,h=max(20,self.plane.winfo_width()),max(20,self.plane.winfo_height());base=np.array(hue_rgb(self.h*360),float)/255
        s=np.linspace(0,1,w)[None,:,None];v=np.linspace(1,0,h)[:,None,None]
        pixels=np.rint(((1-s)+s*base)*v*255).astype(np.uint8)
        self.plane_image=ImageTk.PhotoImage(Image.fromarray(pixels),master=self.window);self.plane.delete('all');self.plane.create_image(0,0,anchor='nw',image=self.plane_image)
        x,y=self.s*(w-1),(1-self.v)*(h-1);self.plane.create_oval(x-5,y-5,x+5,y+5,outline='white',width=2)
        w=max(20,self.hue.winfo_width());h=max(16,self.hue.winfo_height());pixels=np.array([hue_rgb(i/w*360) for i in range(w)],np.uint8)[None].repeat(h,0)
        self.hue_image=ImageTk.PhotoImage(Image.fromarray(pixels),master=self.window);self.hue.delete('all');self.hue.create_image(0,0,anchor='nw',image=self.hue_image);self.hue.create_line(self.h*w,0,self.h*w,h,fill='white',width=3)
        self.update_fields()
    def pick_sv(self,e):self.s=float(np.clip(e.x/max(1,self.plane.winfo_width()-1),0,1));self.v=float(1-np.clip(e.y/max(1,self.plane.winfo_height()-1),0,1));self.paint()
    def pick_hue(self,e):self.h=float(np.clip(e.x/max(1,self.hue.winfo_width()),0,.99999));self.paint()
    def set_hex(self,color):
        rgb=[int(color[i:i+2],16) for i in (1,3,5)];self.h,self.s,self.v=colorsys.rgb_to_hsv(*[v/255 for v in rgb]);self.paint()
    def from_hex(self,e=None):
        try:
            value=self.hex.get().strip();assert len(value)==7 and value.startswith('#');self.set_hex(value);self.error.configure(text='')
        except (ValueError,AssertionError):self.error.configure(text='请输入 #RRGGBB，例如 #B4415F')
        return 'break'
    def from_rgb(self,e=None):
        try:
            rgb=[int(v.get()) for v in self.rgb_vars];assert all(0<=v<=255 for v in rgb);self.set_hex(rgb_hex(rgb));self.error.configure(text='')
        except (ValueError,AssertionError):self.error.configure(text='RGB应为0–255整数')
        return 'break'
    def apply(self):
        (self.from_rgb if self.input_kind=='rgb' else self.from_hex)()
        if self.error.cget('text'):return
        rgb=self.rgb();self.window.destroy();self.callback(rgb)
