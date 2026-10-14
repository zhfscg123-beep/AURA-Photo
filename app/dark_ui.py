"""Light, rounded desktop workspace and validated editing controls."""
import tkinter as tk
from tkinter import ttk
import math
from dpi_support import dp,scale_canvas_art,ui_font

class ParameterScale(ttk.Scale):
    """Numeric entry and a release-to-apply slider sharing one validated value.

    No expensive command runs while the pointer is dragging. Keyboard changes
    debounce; Return/focus-out commits a typed value once. Disabled state also
    disables the entry, including controls with conditional RAW/mask availability.
    """
    def __init__(self,parent,title,variable,lo,hi,command,record,decimals=0,mutating=True,focus_target=None):
        row=ttk.Frame(parent);row.pack(fill='x',pady=(4,3))
        self.label=ttk.Label(row,text=title,style='Muted.TLabel',width=13,wraplength=120);self.label.pack(side='left')
        self.number=tk.StringVar(value=f'{variable.get():.{decimals}f}')
        self.entry=ttk.Entry(row,textvariable=self.number,width=6,justify='right',style='Parameter.TEntry')
        self.entry.pack(side='right');self.variable=variable;self.lo=lo;self.hi=hi
        self.decimals=decimals;self.apply_command=command;self.record_command=record
        self.title=title;self.mutating=mutating;self.focus_target=focus_target
        self.dragging=False;self.pending=None;self.dirty=False;self.preview_command=None
        self.default_value=float(variable.get())
        super().__init__(row,from_=lo,to=hi,variable=variable,command=self.changed)
        self.pack(side='left',fill='x',expand=True,padx=(5,7))
        variable.trace_add('write',self.sync_number)
        self.bind('<ButtonPress-1>',self.start_drag)
        self.bind('<ButtonRelease-1>',self.end_drag)
        self.bind('<KeyRelease>',self.key_release)
        self.entry.bind('<Return>',self.submit)
        self.entry.bind('<FocusOut>',self.leave)
        self.entry.bind('<Escape>',self.escape)
        self.entry.bind('<FocusIn>',lambda e:self.entry.after_idle(lambda:self.entry.selection_range(0,'end')))
        self.label.bind('<Double-Button-1>',self.reset_default)
        self.bind('<Double-Button-1>',self.reset_default)
    def reset_default(self,event=None):
        if str(self.cget('state'))=='disabled':return 'break'
        self.dragging=False;self.cancel_pending();self.variable.set(self.default_value);self.dirty=True;self.commit()
        return 'break'
    def configure(self,cnf=None,**kwargs):
        result=super().configure(cnf,**kwargs)
        state=kwargs.get('state',cnf.get('state') if isinstance(cnf,dict) else None)
        if state is not None and hasattr(self,'entry'):self.entry.configure(state=state)
        return result
    def sync_number(self,*_):
        self.number.set(f'{self.variable.get():.{self.decimals}f}')
        self.entry.configure(style='Parameter.TEntry')
    def cancel_pending(self):
        if self.pending is not None:self.after_cancel(self.pending);self.pending=None
    def start_drag(self,event=None):
        self.cancel_pending();self.dragging=True
    def changed(self,value):
        self.dirty=True
        if not self.mutating:self.apply_command();return
        if self.dragging and self.preview_command:self.preview_command()
        if not self.dragging:
            self.cancel_pending();self.pending=self.after(220,self.commit)
    def end_drag(self,event=None):
        self.dragging=False;self.cancel_pending()
        self.pending=self.after_idle(self.commit)
    def key_release(self,event):
        if event.keysym in ('Left','Right','Up','Down','Home','End','Prior','Next'):
            self.cancel_pending();self.pending=self.after(150,self.commit)
    def commit(self):
        self.pending=None
        if not self.dirty or str(self.cget('state'))=='disabled':return
        self.dirty=False
        # Integer controls display and apply the same value, not hidden fractions.
        value=round(float(self.variable.get()),self.decimals)
        self.variable.set(int(value) if isinstance(self.variable,tk.IntVar) else value)
        self.apply_command()
        if self.mutating:self.record_command(f'{self.title} → {value:.{self.decimals}f}')
    def typed(self):
        try:
            value=float(self.number.get().strip())
            if not math.isfinite(value) or not self.lo<=value<=self.hi:raise ValueError()
        except (ValueError,OverflowError):
            self.entry.configure(style='Invalid.TEntry');return False
        value=round(value,self.decimals)
        old=float(self.variable.get());self.variable.set(int(value) if isinstance(self.variable,tk.IntVar) else value)
        self.cancel_pending();self.dirty=self.dirty or value!=old;self.commit();return True
    def submit(self,event=None):
        if self.typed() and self.focus_target:self.focus_target()
        return 'break'
    def leave(self,event=None):
        if str(self.entry.cget('state'))!='disabled' and not self.typed():self.sync_number()
    def escape(self,event=None):
        self.sync_number()
        if self.focus_target:self.focus_target()
        return 'break'

def dark_caption(root):
    try:
        import ctypes
        from ctypes import wintypes
        user=ctypes.WinDLL('user32');user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
        window=user.GetParent(root.winfo_id());dwm=ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        for key,value in [(20,0),(35,0x00ffffff),(36,0x0031251c)]:
            data=wintypes.DWORD(value);dwm.DwmSetWindowAttribute(window,key,ctypes.byref(data),ctypes.sizeof(data))
    except (OSError,AttributeError):pass

COLORS={'bg':'#f5f7fa','panel':'#ffffff','raised':'#f1f4f8','border':'#dce3ed','text':'#202b3c','muted':'#59677a','accent':'#3169ec','canvas':'#f5f7fa','viewport':'#e9edf2','selected':'#eaf1ff'}

def style(root):
    root.configure(bg=COLORS['bg']);root.option_add('*Font',ui_font(root,11))
    root.after(250,lambda:dark_caption(root))
    s=ttk.Style(root);s.theme_use('clam')
    from PIL import Image,ImageDraw,ImageTk
    root._theme_images=[];root._theme_generation=getattr(root,'_theme_generation',0)+1
    generation=str(root._theme_generation)
    def shape(fill,border,radius=8,size=(32,32),ellipse=False):
        size=tuple(dp(root,n) for n in size);im=Image.new('RGBA',size,COLORS['panel']);draw=ImageDraw.Draw(im)
        if ellipse:draw.ellipse((dp(root,2),dp(root,2),size[0]-dp(root,3),size[1]-dp(root,3)),fill=fill,outline=border,width=max(1,dp(root,1)))
        else:draw.rounded_rectangle((dp(root,1),dp(root,1),size[0]-dp(root,2),size[1]-dp(root,2)),radius=dp(root,radius),fill=fill,outline=border,width=max(1,dp(root,1)))
        photo=ImageTk.PhotoImage(im,master=root);root._theme_images.append(photo);return photo
    for name,fill,hover in [('Round','#ffffff','#f0f5ff'),('Accent','#3169ec','#2459d4')]:
        normal=shape(fill,'#e0e6ef');active=shape(hover,'#b4c8f8');pressed=shape('#dde8ff','#95b5fa');disabled=shape('#f5f7fa','#e6ebf2');focused=shape(fill,COLORS['accent'])
        element=name+generation+'.border'
        s.element_create(element,'image',normal,('disabled',disabled),('pressed',pressed),('focus',focused),('active',active),border=dp(root,10),sticky='nswe')
        target='TButton' if name=='Round' else 'Accent.TButton'
        s.layout(target,[(element,{'sticky':'nswe','children':[('Button.padding',{'sticky':'nswe','children':[('Button.label',{'sticky':'nswe'})]})]})])
    header=shape('#f6f8fb','#e7ecf3',radius=10)
    element='Section'+generation+'.round';s.element_create(element,'image',header,border=dp(root,10),sticky='nswe')
    s.layout('Section.TLabel',[(element,{'sticky':'nswe','children':[('Label.padding',{'sticky':'nswe','children':[('Label.label',{'sticky':'nswe'})]})]})])
    s.configure('Section.TLabel',font=ui_font(root,11,'bold'),padding=(dp(root,8),dp(root,8)))
    s.map('Section.TLabel',foreground=[('focus',COLORS['accent'])])
    knob=shape('#3169ec','#ffffff',size=(16,16),ellipse=True);knob_active=shape('#2459d4','#d3dfff',size=(16,16),ellipse=True)
    slider='Photo'+generation+'.slider';trough_element='Photo'+generation+'.trough'
    s.element_create(slider,'image',knob,('active',knob_active),('pressed',knob_active),sticky='')
    trough=Image.new('RGB',(dp(root,16),dp(root,16)),COLORS['panel']);td=ImageDraw.Draw(trough);td.rounded_rectangle(tuple(dp(root,v) for v in (2,7,13,9)),radius=dp(root,1),fill='#b8c5d7')
    trough_photo=ImageTk.PhotoImage(trough,master=root);root._theme_images.append(trough_photo)
    s.element_create(trough_element,'image',trough_photo,border=(dp(root,4),0,dp(root,4),0),sticky='we')
    s.layout('Horizontal.TScale',[(trough_element,{'sticky':'we','children':[(slider,{'side':'left','sticky':''})]})])
    s.configure('.',background=COLORS['panel'],foreground=COLORS['text'],font=ui_font(root,11))
    s.configure('TFrame',background=COLORS['panel']);s.configure('TLabel',background=COLORS['panel'],foreground=COLORS['text'])
    s.configure('Workspace.TFrame',background=COLORS['bg'])
    s.configure('Muted.TLabel',foreground=COLORS['muted'],font=ui_font(root,10));s.configure('Title.TLabel',font=ui_font(root,18,'bold'))
    s.configure('TButton',background=COLORS['raised'],foreground=COLORS['text'],bordercolor=COLORS['border'],padding=(dp(root,8),dp(root,4)),focuscolor=COLORS['raised'],font=ui_font(root,10))
    s.configure('Compact.TButton',padding=(0,dp(root,2)),font=ui_font(root,10))
    s.map('TButton',background=[('active','#f0f5ff'),('pressed','#dde8ff')],foreground=[('disabled','#a7b0bf')])
    s.configure('Accent.TButton',background='#3169ec',foreground='#ffffff');s.map('Accent.TButton',background=[('active','#2459d4')],foreground=[('disabled','#9aa8be'),('!disabled','#ffffff')])
    s.configure('TCheckbutton',background=COLORS['panel'],foreground=COLORS['text'],indicatorbackground=COLORS['canvas'],indicatorforeground=COLORS['accent'],focuscolor=COLORS['panel'])
    s.map('TCheckbutton',background=[('active',COLORS['panel'])],indicatorbackground=[('selected','#3169ec')])
    s.configure('TRadiobutton',background=COLORS['panel'],foreground=COLORS['text'],indicatorbackground=COLORS['canvas'],indicatorforeground=COLORS['accent'],focuscolor=COLORS['panel'])
    s.map('TRadiobutton',background=[('active',COLORS['panel'])])
    s.configure('TScale',background=COLORS['raised'],troughcolor=COLORS['canvas'],bordercolor=COLORS['raised'])
    for name in ('TEntry','TSpinbox','TCombobox'):
        s.configure(name,fieldbackground=COLORS['canvas'],background=COLORS['raised'],foreground=COLORS['text'],insertcolor=COLORS['text'],bordercolor=COLORS['border'],lightcolor=COLORS['border'],darkcolor=COLORS['border'],borderwidth=1,relief='flat',arrowsize=dp(root,12))
    s.configure('Invalid.TEntry',foreground='#ce3c4c')
    s.configure('Parameter.TEntry',fieldbackground=COLORS['panel'],bordercolor=COLORS['panel'],lightcolor=COLORS['panel'],darkcolor=COLORS['panel'],padding=(dp(root,2),dp(root,2)))
    for option in ('bordercolor','lightcolor','darkcolor'):
        s.map('Parameter.TEntry',**{option:[('focus',COLORS['accent'])]})
    s.map('Parameter.TEntry',fieldbackground=[('focus',COLORS['canvas'])])
    s.map('TCombobox',fieldbackground=[('readonly',COLORS['canvas'])],foreground=[('readonly',COLORS['text'])])
    root.option_add('*TCombobox*Listbox.background',COLORS['panel']);root.option_add('*TCombobox*Listbox.foreground',COLORS['text'])
    for name in ('Vertical.TScrollbar','Horizontal.TScrollbar'):
        s.configure(name,background=COLORS['raised'],troughcolor=COLORS['panel'],bordercolor=COLORS['panel'],lightcolor=COLORS['panel'],darkcolor=COLORS['panel'],borderwidth=0,arrowsize=dp(root,12))
    s.configure('TProgressbar',background=COLORS['accent'],troughcolor=COLORS['canvas'],bordercolor=COLORS['border'])
    s.configure('Treeview',font=ui_font(root,10),rowheight=dp(root,28),background=COLORS['panel'],fieldbackground=COLORS['panel'],foreground=COLORS['text'])
    s.configure('Treeview.Heading',font=ui_font(root,10,'bold'),padding=(dp(root,5),dp(root,4)))
    s.map('Treeview',background=[('selected',COLORS['selected'])],foreground=[('selected',COLORS['text'])])
    return s

class Section(ttk.Frame):
    def __init__(self,parent,title,opened=True):
        super().__init__(parent);self.pack(fill='x',pady=(0,8));self.opened=opened;self.title=title
        self.caption=title.replace(' · 当前人像','')
        self.header=ttk.Label(self,text=('▾  ' if opened else '▸  ')+self.caption,style='Section.TLabel',anchor='w',cursor='hand2',takefocus=1,wraplength=270)
        self.header.pack(fill='x');self.body=ttk.Frame(self,padding=(10,8))
        if opened:self.body.pack(fill='x')
        self.header.bind('<Button-1>',self.toggle)
        self.header.bind('<Return>',self.toggle);self.header.bind('<space>',self.toggle)
        self.header.bind('<FocusIn>',lambda e:self.header.state(['focus']));self.header.bind('<FocusOut>',lambda e:self.header.state(['!focus']))
        self.bind('<Configure>',lambda e:self.header.configure(wraplength=max(dp(self,80),e.width-dp(self,32))))
    def toggle(self,event=None):
        self.opened=not self.opened;self.header.configure(text=('▾  ' if self.opened else '▸  ')+self.caption)
        if self.opened:self.body.pack(fill='x')
        else:self.body.pack_forget()

class ToolButton(tk.Canvas):
    """Compact vector tool icon with explicit active and disabled states."""
    def __init__(self,parent,label,kind,command):
        super().__init__(parent,width=59,height=54,bg=COLORS['panel'],highlightthickness=0,cursor='hand2',takefocus=1)
        self.label=label;self.kind=kind;self.command=command;self.selected=False
        self.bind('<Button-1>',self.click);self.bind('<Return>',self.click);self.bind('<space>',self.click)
        self.bind('<FocusIn>',lambda e:self.paint());self.bind('<FocusOut>',lambda e:self.paint());self.paint()
    def click(self,event):
        if self.cget('state')!='disabled':self.command()
    def configure(self,cnf=None,**kwargs):
        result=super().configure(cnf,**kwargs)
        if hasattr(self,'kind'):self.paint()
        return result
    def set_active(self,value):self.selected=value;self.paint()
    def paint(self):
        self.delete('all');disabled=self.cget('state')=='disabled'
        color='#626a74' if disabled else COLORS['accent'] if self.selected else COLORS['text']
        if self.selected:self.create_polygon(9,1,50,1,58,9,58,44,50,52,9,52,1,44,1,9,fill=COLORS['raised'],outline=COLORS['accent'],smooth=True)
        if self.kind in ('retouch_dodge','retouch_burn'):
            self.create_oval(21,9,38,26,outline=color,width=2)
            if self.kind=='retouch_burn':self.create_arc(21,9,38,26,start=90,extent=180,fill=color,outline=color)
            else:
                for x,y,z,t in [(29,3,29,6),(29,29,29,32),(15,17,18,17),(41,17,44,17)]:self.create_line(x,y,z,t,fill=color,width=2)
        elif self.kind=='retouch_heal':
            self.create_polygon(18,22,34,6,41,13,25,29,fill='',outline=color,width=2)
            self.create_line(23,17,30,24,fill=color);self.create_line(29,11,36,18,fill=color)
            self.create_oval(28,17,30,19,fill=color,outline=color)
        elif self.kind=='retouch_clone':
            self.create_oval(24,5,35,16,outline=color,width=2)
            self.create_line(26,15,25,23,34,23,33,15,fill=color,width=2)
            self.create_rectangle(19,24,40,29,outline=color,width=2)
        elif self.kind=='retouch_restore':
            self.create_arc(18,7,40,29,start=30,extent=280,outline=color,width=2,style='arc')
            self.create_line(38,10,41,17,34,16,fill=color,width=2)
        elif self.kind=='liquify_nodes':
            self.create_line(18,24,28,8,42,24,fill=color,width=1.5)
            for x,y in ((18,24),(28,8),(42,24)):self.create_oval(x-3,y-3,x+3,y+3,fill=COLORS['panel'],outline=color,width=1.5)
        elif self.kind=='liquify_face':
            self.create_oval(19,4,40,31,outline=color,width=1.5)
            self.create_line(22,14,26,14,fill=color,width=2);self.create_line(33,14,37,14,fill=color,width=2)
            self.create_line(29,15,27,21,30,21,fill=color,width=1.5)
            self.create_arc(25,22,35,28,start=180,extent=180,style='arc',outline=color,width=1.5)
        elif self.kind=='liquify_push_left':
            self.create_line(36,29,36,6,fill=color,width=1.5,arrow='last')
            self.create_line(37,17,17,17,fill=color,width=2,arrow='last')
        elif self.kind=='liquify_twirl':
            self.create_arc(18,7,40,29,start=10,extent=290,outline=color,width=2,style='arc')
            self.create_line(39,13,41,7,34,8,fill=color,width=2)
            self.create_arc(24,13,35,24,start=30,extent=270,outline=color,width=1.5,style='arc')
        elif self.kind=='liquify_smooth':
            for y in (11,18,25):self.create_line(18,y+2,24,y-2,34,y+2,41,y-2,fill=color,width=1.5,smooth=True)
        elif self.kind in ('liquify_bloat','liquify_pucker'):
            self.create_oval(20,9,39,28,outline=color,width=1.5)
            for a,b,c,d in [(14,18,24,18),(45,18,35,18),(29,3,29,13),(29,34,29,24)]:
                if self.kind=='liquify_bloat':a,b,c,d=c,d,a,b
                self.create_line(a,b,c,d,fill=color,width=1.5,arrow='last',arrowshape=(4,5,2))
        elif self.kind=='liquify_restore':
            self.create_arc(18,7,40,29,start=30,extent=280,outline=color,width=2,style='arc')
            self.create_line(38,10,41,17,34,16,fill=color,width=2)
        elif self.kind in ('liquify_freeze','liquify_thaw'):
            self.create_oval(21,8,39,29,outline=color,width=1.5)
            for angle in (0,60,120):
                dx=math.cos(math.radians(angle))*8;dy=math.sin(math.radians(angle))*8
                self.create_line(30-dx,18-dy,30+dx,18+dy,fill=color,width=1.5)
            if self.kind=='liquify_thaw':self.create_line(18,29,41,6,fill=color,width=2)
        elif self.kind in ('circle','exclude','restore'):
            self.create_oval(19,7,40,28,outline=color,width=2)
            self.create_line(25,17,34,17,fill=color,width=2 if self.kind=='exclude' else 1)
            if self.kind!='exclude':self.create_line(30,13,30,22,fill=color)
        elif self.kind in ('brush','mask_add','mask_subtract'):
            self.create_polygon(24,19,35,6,40,10,29,23,outline=color,fill='',width=2)
            self.create_polygon(24,20,29,24,25,29,19,30,21,24,fill=color,outline=color)
            if self.kind!='brush':
                self.create_line(40,24,48,24,fill=color,width=2)
                if self.kind=='mask_add':self.create_line(44,20,44,28,fill=color,width=2)
        elif self.kind=='erase':
            self.create_polygon(19,22,32,7,41,15,29,29,25,29,fill='',outline=color,width=2)
            self.create_line(23,18,32,26,fill=color,width=2);self.create_line(19,31,41,31,fill=color)
        else:
            self.create_line(29,7,29,30,fill=color,width=2,arrow='both')
            self.create_line(18,18,41,18,fill=color,width=2,arrow='both')
        self.create_text(30,43,text=self.label,fill=color,font=ui_font(self,10))
        if self.focus_get() is self:self.create_rectangle(2,2,57,52,outline=COLORS['accent'],dash=(2,2))
        scale_canvas_art(self)
