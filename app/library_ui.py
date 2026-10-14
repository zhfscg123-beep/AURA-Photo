"""Paged grid, persistent culling marks and equal-sized comparison panes."""
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image,ImageTk
from dark_ui import COLORS
from dpi_support import dp,ui_font
from library_catalog import Catalog,quality_hint

class LibraryUI:
    def init_catalog(self):self.catalog=Catalog()
    def show_photo_library(self):
        if self.busy:return
        self.keep_current()
        if self.busy:return
        window=tk.Toplevel(self.root);window.title('照片库');window.transient(self.root)
        window.geometry(f'{min(dp(self.root,980),self.root.winfo_screenwidth()-dp(self.root,32))}x{min(dp(self.root,700),self.root.winfo_screenheight()-dp(self.root,70))}')
        outer=ttk.Frame(window,padding=12);outer.pack(fill='both',expand=True)
        query=tk.StringVar();rating=tk.StringVar(value='0');flag=tk.StringVar(value='全部');sort=tk.StringVar(value='文件名');note=tk.StringVar()
        row=ttk.Frame(outer);row.pack(fill='x');ttk.Label(row,text='搜索').pack(side='left');ttk.Entry(row,textvariable=query,width=22).pack(side='left',padx=6)
        for title,var,values in [('最低评分',rating,list(map(str,range(6)))),('标记',flag,['全部','未标记','保留','待剔除']),('排序',sort,['文件名','评分'])]:
            ttk.Label(row,text=title).pack(side='left',padx=(8,2));ttk.Combobox(row,textvariable=var,values=values,state='readonly',width=8).pack(side='left')
        canvas=tk.Canvas(outer,bg=COLORS['bg'],highlightthickness=0,takefocus=1);canvas.pack(fill='both',expand=True,pady=10)
        selected=set();page=[0];photos=[];items=[]
        def paint(*_):
            if not window.winfo_exists():return
            items[:]=self.catalog.select(self.library.entries,query.get(),int(rating.get()),flag.get(),sort.get())
            page[0]=max(0,min(page[0],max(0,(len(items)-1)//12)));canvas.delete('all');photos.clear()
            columns=4 if canvas.winfo_width()>=dp(self.root,720) else 3;rows=4 if columns==3 else 3
            cellw=max(1,canvas.winfo_width()/columns);cellh=max(1,canvas.winfo_height()/rows)
            for i,(key,entry) in enumerate(items[page[0]*12:(page[0]+1)*12]):
                x=(i%columns)*cellw;y=(i//columns)*cellh;tag='card'+str(i);data=self.catalog.get(entry)
                canvas.create_rectangle(x+4,y+4,x+cellw-4,y+cellh-4,fill=COLORS['selected'] if key in selected else COLORS['panel'],outline=COLORS['accent'] if key in selected else COLORS['border'],tags=tag)
                image=entry['thumb'].copy();image.thumbnail((max(1,int(cellw-20)),max(1,int(cellh-54))),Image.Resampling.LANCZOS)
                photo=ImageTk.PhotoImage(image,master=window);photos.append(photo);canvas.create_image(x+cellw/2,y+(cellh-42)/2,image=photo,tags=tag)
                canvas.create_text(x+cellw/2,y+cellh-34,text=entry['path'].name[:26],fill=COLORS['text'],font=ui_font(self.root,10),tags=tag)
                canvas.create_text(x+cellw/2,y+cellh-16,text=('★'*data['rating'] or '未评分')+' · '+data['flag']+' · '+data['label'],fill=COLORS['muted'],font=ui_font(self.root,9),tags=tag)
                def choose(event,key=key):
                    if not event.state&4:selected.clear()
                    if key in selected:selected.remove(key)
                    else:selected.add(key)
                    canvas.focus_set();paint()
                canvas.tag_bind(tag,'<Button-1>',choose)
                canvas.tag_bind(tag,'<Double-Button-1>',lambda e,p=entry['path']:(window.destroy(),self.open(p)))
            text=f'{len(items)} 张 · 第 {page[0]+1}/{max(1,(len(items)+11)//12)} 页 · 已选 {len(selected)} 张'
            if len(selected)==1:
                entry=self.library.entries.get(next(iter(selected)))
                if entry:
                    quality=quality_hint(entry['thumb']);text+=f' · 缩略图清晰度参考 {quality["sharpness"]}'
            note.set(text)
        def mark(**values):
            try:self.catalog.set([self.library.entries[k] for k in selected if k in self.library.entries],**values);paint();self.draw_filmstrip()
            except OSError as e:messagebox.showerror('标记未保存',str(e),parent=window)
        def compare():
            keys=[k for k in self.library.entries if k in selected]
            if len(keys)!=2:note.set('请选择两张照片（Ctrl＋点击多选）。');return
            window.destroy();self.compare_library_photos(keys)
        row=ttk.Frame(outer);row.pack(fill='x')
        ttk.Button(row,text='上一页',command=lambda:(page.__setitem__(0,page[0]-1),paint())).pack(side='left')
        ttk.Button(row,text='下一页',command=lambda:(page.__setitem__(0,page[0]+1),paint())).pack(side='left',padx=5)
        ttk.Button(row,text='对照所选两张',command=compare).pack(side='right');ttk.Label(row,textvariable=note).pack(side='left',padx=8)
        marks=ttk.Frame(outer);marks.pack(fill='x',pady=(8,0));ttk.Label(marks,text='评分').pack(side='left')
        for value in range(6):ttk.Button(marks,text=str(value),width=2,command=lambda v=value:mark(rating=v)).pack(side='left',padx=1)
        for value in ('保留','待剔除','未标记'):ttk.Button(marks,text=value,command=lambda v=value:mark(flag=v)).pack(side='left',padx=3)
        label=tk.StringVar(value='无');c=ttk.Combobox(marks,textvariable=label,values=['无','红','黄','绿','蓝','紫'],state='readonly',width=4);c.pack(side='right');c.bind('<<ComboboxSelected>>',lambda e:mark(label=label.get()))
        ttk.Label(outer,text='Ctrl＋点击多选；双击进入编辑。0–5评分，P保留，X待剔除，U取消标记。待剔除只作标记，原图保留。',style='Muted.TLabel',wraplength=dp(self.root,860)).pack(anchor='w',pady=6)
        for key in range(6):canvas.bind(str(key),lambda e,v=key:mark(rating=v))
        for key,value in [('p','保留'),('x','待剔除'),('u','未标记')]:canvas.bind(key,lambda e,v=value:mark(flag=v))
        canvas.bind('<Configure>',paint)
        for var in (query,rating,flag,sort):var.trace_add('write',lambda *_:(page.__setitem__(0,0),paint()))
        self.library_window=window;self.library_grid=canvas;window.after_idle(paint)
    def compare_library_photos(self,keys):
        if self.busy:return
        def job():
            pairs=[]
            for key in keys:
                state=self.library.load(key);pairs.append((self.library.entries[key]['path'].name,Image.fromarray(state['output']).copy()))
            return pairs
        def ready(pairs):
            window=tk.Toplevel(self.root);window.title('照片对照');window.transient(self.root)
            window.geometry(f'{min(dp(self.root,1120),self.root.winfo_screenwidth()-40)}x{min(dp(self.root,760),self.root.winfo_screenheight()-80)}')
            bar=ttk.Frame(window,padding=10);bar.pack(fill='x');zoom=[None];center=[.5,.5];canvases=[];images=[];start=[None]
            def draw(*_):
                images.clear()
                for canvas,(_,image) in zip(canvases,pairs):
                    canvas.delete('all');w,h=max(1,canvas.winfo_width()),max(1,canvas.winfo_height());scale=zoom[0] or min(w/image.width,h/image.height)
                    cw,ch=min(image.width,w/scale),min(image.height,h/scale);x=max(0,min(image.width-cw,center[0]*image.width-cw/2));y=max(0,min(image.height-ch,center[1]*image.height-ch/2))
                    frame=image.crop((int(x),int(y),int(x+cw),int(y+ch)));frame=frame.resize((max(1,round(cw*scale)),max(1,round(ch*scale))),Image.Resampling.LANCZOS)
                    photo=ImageTk.PhotoImage(frame,master=window);images.append(photo);canvas.create_image(w/2,h/2,image=photo)
            ttk.Button(bar,text='适合',command=lambda:(zoom.__setitem__(0,None),center.__setitem__(slice(None),[.5,.5]),draw())).pack(side='left')
            ttk.Button(bar,text='100%',command=lambda:(zoom.__setitem__(0,1),draw())).pack(side='left',padx=5)
            ttk.Label(bar,text='100%或滚轮采用同一缩放；适合时各自完整显示。拖动同步平移。').pack(side='left',padx=10)
            area=ttk.Frame(window);area.pack(fill='both',expand=True)
            for name,image in pairs:
                frame=ttk.Frame(area,padding=6);frame.pack(side='left',fill='both',expand=True);ttk.Label(frame,text=name).pack()
                canvas=tk.Canvas(frame,bg=COLORS['viewport'],highlightthickness=0);canvas.pack(fill='both',expand=True);canvases.append(canvas);canvas.bind('<Configure>',draw)
                canvas.bind('<MouseWheel>',lambda e:(zoom.__setitem__(0,max(.05,min(8,(zoom[0] or .5)*1.2**(e.delta/120)))),draw()))
                canvas.bind('<ButtonPress-1>',lambda e:start.__setitem__(0,(e.x,e.y)))
                def move(e,image=image):
                    if start[0] is None:return
                    x,y=start[0];scale=zoom[0] or min(e.widget.winfo_width()/image.width,e.widget.winfo_height()/image.height)
                    center[0]=max(0,min(1,center[0]-(e.x-x)/scale/image.width));center[1]=max(0,min(1,center[1]-(e.y-y)/scale/image.height));start[0]=(e.x,e.y);draw()
                canvas.bind('<B1-Motion>',move);canvas.bind('<ButtonRelease-1>',lambda e:start.__setitem__(0,None))
            self.compare_window=window;window.after_idle(draw)
        self.work(job,ready)
