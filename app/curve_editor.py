"""Direct point curve editing with histogram/grid and explicit numeric coordinates."""
import tkinter as tk
from tkinter import ttk
import numpy as np,cv2
from dark_ui import COLORS
from dpi_support import dp,ui_font
import point_curves

class CurveEditor(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent);self.app=app;self.pack(fill='x');self.channel=tk.StringVar(value='RGB');self.selected=0;self.dragging=False
        self.hist_cache=None
        row=ttk.Frame(self);row.pack(fill='x');ttk.Label(row,text='点曲线通道').pack(side='left')
        c=ttk.Combobox(row,textvariable=self.channel,values=['RGB','红','绿','蓝'],state='readonly',width=7);c.pack(side='right');c.bind('<<ComboboxSelected>>',lambda e:self.draw())
        self.canvas=tk.Canvas(self,height=dp(app.root,240),bg='#f4f7fb',highlightthickness=0);self.canvas._aura_managed_geometry=True;self.canvas.pack(fill='x',pady=8)
        self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Button-3>',self.remove);self.canvas.bind('<Delete>',self.remove);self.canvas.configure(takefocus=1)
        row=ttk.Frame(self);row.pack(fill='x');self.x=tk.StringVar();self.y=tk.StringVar()
        for title,var in [('输入',self.x),('输出',self.y)]:
            ttk.Label(row,text=title).pack(side='left');e=ttk.Entry(row,textvariable=var,width=5);e.pack(side='left',padx=4);e.bind('<Return>',self.typed)
        ttk.Button(row,text='恢复本通道',width=0,command=self.reset).pack(side='right')
        ttk.Label(self,text='左：暗部 → 右：亮部；上移提亮，下移压暗。点击加点，拖动调整，右键删点。',style='Muted.TLabel',wraplength=270).pack(anchor='w',pady=5)
    def key(self):return {'RGB':'rgb','红':'r','绿':'g','蓝':'b'}[self.channel.get()]
    def points(self):return self.app.workflow_extensions.get('color',{}).get('points',{}).get(self.key(),point_curves.IDENTITY)
    def set_points(self,pts):
        data=self.app.workflow_extensions.setdefault('color',{});data['process']=2 if self.app.color_process.get()=='专业浮点调色' else 1;curves=data.setdefault('points',{});curves[self.key()]=pts;point_curves.checked(curves);self.draw()
    def bounds(self):
        w=max(80,self.canvas.winfo_width());h=max(80,self.canvas.winfo_height());pad=dp(self.app.root,25);return pad,pad,w-pad,h-pad
    def graph_point(self,e):
        a,b,c,d=self.bounds();return float(np.clip((e.x-a)/(c-a),0,1)),float(np.clip((d-e.y)/(d-b),0,1))
    def draw(self):
        if not self.canvas.winfo_exists():return
        c=self.canvas;width=max(100,c.winfo_width());want=dp(self.app.root,min(260,max(170,width/self.app.root._ui_scale)))
        if int(c.cget('height'))!=want:c.configure(height=want)
        c.delete('all');a,b,x1,y1=self.bounds();color={'rgb':'#3169ec','r':'#cc5862','g':'#42a26f','b':'#588bc5'}[self.key()]
        source=getattr(self.app,'color_input',None)
        if source is not None:
            key=id(source),self.key()
            if self.hist_cache is None or self.hist_cache[0]!=key:
                small=cv2.resize(source,(256,128));values=small.mean(2) if self.key()=='rgb' else small[:,:,{'r':0,'g':1,'b':2}[self.key()]]
                self.hist_cache=key,np.histogram(values,bins=64,range=(0,256))[0]
            hist=self.hist_cache[1];peak=max(1,hist.max())
            path=[a,y1]
            for i,v in enumerate(hist):path.extend([a+i/63*(x1-a),y1-v/peak*(y1-b)*.8])
            path.extend([x1,y1]);c.create_polygon(*path,fill='#e0e6ef',outline='')
        for t in np.linspace(0,1,5):c.create_line(a+t*(x1-a),b,a+t*(x1-a),y1,fill='#d9e1ec');c.create_line(a,b+t*(y1-b),x1,b+t*(y1-b),fill='#d9e1ec')
        c.create_line(a,y1,x1,b,fill='#b5c2d3',dash=(3,3));pts=self.points();xx=np.linspace(0,1,129);yy=point_curves.evaluate(xx,pts)
        c.create_line(*np.stack([a+xx*(x1-a),y1-yy*(y1-b)],axis=1).ravel().tolist(),fill=color,width=dp(self.app.root,2))
        for i,(x,y) in enumerate(pts):
            px,py=a+x*(x1-a),y1-y*(y1-b);r=dp(self.app.root,4);c.create_oval(px-r,py-r,px+r,py+r,fill=color if i==self.selected else 'white',outline=color,width=dp(self.app.root,1))
        c.create_text(a,y1+dp(self.app.root,13),text='0',fill=COLORS['muted'],font=ui_font(self.app.root,8));c.create_text(x1,y1+dp(self.app.root,13),text='255 输入',anchor='e',fill=COLORS['muted'],font=ui_font(self.app.root,8))
        c.create_text(a-dp(self.app.root,5),b,text='255',anchor='e',fill=COLORS['muted'],font=ui_font(self.app.root,8))
        self.selected=min(self.selected,len(pts)-1);self.x.set(str(round(pts[self.selected][0]*255)));self.y.set(str(round(pts[self.selected][1]*255)))
    def press(self,e):
        if self.app.busy:return
        if not self.app._render_pending:self.app.flush_parameters()
        self.canvas.focus_set();p=self.graph_point(e);pts=[list(v) for v in self.points()];a,b,c,d=self.bounds()
        if self.app.busy:return
        distances=[np.hypot((p[0]-x)*(c-a),(p[1]-y)*(d-b)) for x,y in pts];i=int(np.argmin(distances))
        if distances[i]>dp(self.app.root,10) and len(pts)<64:
            if p[0]<.002 or p[0]>.998:return
            pts.append(list(p));pts.sort();i=pts.index(list(p));self.app.commit_edit('点曲线调整前');self.set_points(pts)
        else:self.app.commit_edit('点曲线调整前')
        self.selected=i;self.dragging=True;self.motion(e)
    def motion(self,e):
        if not self.dragging:return
        x,y=self.graph_point(e);pts=[list(v) for v in self.points()];i=self.selected
        x=pts[i][0] if i in (0,len(pts)-1) else float(np.clip(x,pts[i-1][0]+.002,pts[i+1][0]-.002));pts[i]=[x,y];self.set_points(pts);self.app.preview_global_color()
    def release(self,e):
        if not self.dragging:return
        self.motion(e);self.dragging=False;self.commit()
    def commit(self):self.app.refresh_color();self.app.record('调整点曲线 '+self.channel.get())
    def remove(self,e=None):
        pts=[list(v) for v in self.points()]
        if 0<self.selected<len(pts)-1:self.app.commit_edit('删除曲线点前');pts.pop(self.selected);self.selected=0;self.set_points(pts);self.commit()
        return 'break'
    def typed(self,e=None):
        try:
            x,y=float(self.x.get())/255,float(self.y.get())/255;assert 0<=x<=1 and 0<=y<=1
            pts=[list(v) for v in self.points()];i=self.selected
            if i in (0,len(pts)-1):x=pts[i][0]
            elif not pts[i-1][0]+.002<=x<=pts[i+1][0]-.002:raise ValueError()
            self.app.commit_edit('曲线数值调整前');pts[i]=[x,y];self.set_points(pts);self.commit()
        except (ValueError,AssertionError):self.app.status.set('曲线坐标应为0–255，输入坐标需保持点的顺序。')
        return 'break'
    def reset(self):self.app.commit_edit('重置曲线前');self.set_points(point_curves.IDENTITY);self.commit()
