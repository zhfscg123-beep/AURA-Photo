"""Responsive light workspace, file popup, settings drawer and category rail."""
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from dark_ui import COLORS,Section
from dpi_support import enable_dpi,dp,set_ui_dpi,window_dpi,scale_widget_tree,scale_canvas_art,ui_font

from aura_version import VERSION

def fit_screen(root):
    root.update_idletasks();sw,sh=root.winfo_screenwidth(),root.winfo_screenheight();x=y=0
    try:
        import ctypes
        from ctypes import wintypes
        user=ctypes.WinDLL('user32')
        user.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD];user.MonitorFromWindow.restype=wintypes.HANDLE
        class Info(ctypes.Structure):
            _fields_=[('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]
        info=Info();info.size=ctypes.sizeof(Info)
        user.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Info)]
        if user.GetMonitorInfoW(user.MonitorFromWindow(root.winfo_id(),2),ctypes.byref(info)):
            rect=info.work;x,y,sw,sh=rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top
    except (OSError,AttributeError):pass
    margin=dp(root,16);w=max(1,sw-margin*2);h=max(1,sh-dp(root,48))
    root.geometry(f'{w}x{h}+{x+margin}+{y+margin}')
    root.minsize(min(dp(root,960),max(600,sw-margin*2)),min(dp(root,640),max(420,sh-dp(root,80))))

class CategoryButton(tk.Canvas):
    def __init__(self,parent,label,kind,command):
        super().__init__(parent,width=72,height=64,bg=COLORS['panel'],highlightthickness=0,cursor='hand2',takefocus=1)
        self.label=label;self.kind=kind;self.command=command;self.selected=False;self.hovered=False
        self.bind('<Button-1>',lambda e:self.command())
        self.bind('<Return>',lambda e:self.command());self.bind('<space>',lambda e:self.command())
        self.bind('<FocusIn>',lambda e:self.paint());self.bind('<FocusOut>',lambda e:self.paint())
        self.bind('<Enter>',lambda e:self.set_hover(True));self.bind('<Leave>',lambda e:self.set_hover(False))
        self.bind('<Configure>',lambda e:self.paint());self.paint()
    def set_hover(self,value):self.hovered=value;self.paint()
    def set_active(self,value):self.selected=value;self.paint()
    def paint(self):
        self.delete('all');scale=getattr(self.winfo_toplevel(),'_ui_scale',1)
        w=int(self.cget('width'))/scale;h=int(self.cget('height'))/scale;x=w/2;y=max(13,(h-20)/2)
        color=COLORS['accent'] if self.selected else COLORS['muted']
        if self.selected or self.hovered:
            self.create_polygon(12,3,w-12,3,w-5,10,w-5,h-10,w-12,h-3,12,h-3,5,h-10,5,10,smooth=True,fill=COLORS['selected'] if self.selected else COLORS['raised'],outline='')
        if self.kind=='person':
            self.create_oval(x-9,y-11,x+9,y+8,outline=color,width=2)
            self.create_arc(x-5,y-1,x+5,y+5,start=180,extent=180,style='arc',outline=color,width=2)
        elif self.kind=='color':
            self.create_oval(x-10,y-10,x+10,y+10,outline=color,width=2)
            for dx,dy in [(-4,-4),(4,-3),(-3,4)]:self.create_oval(x+dx-1,y+dy-1,x+dx+1,y+dy+1,fill=color,outline=color)
        elif self.kind=='mask':self.create_rectangle(x-9,y-9,x+9,y+9,outline=color,width=2,dash=(3,2))
        elif self.kind=='detail':
            self.create_line(x-8,y+7,x+7,y-8,fill=color,width=5)
            self.create_line(x-9,y-5,x-3,y-5,fill=color,width=2);self.create_line(x-6,y-8,x-6,y-2,fill=color,width=2)
        elif self.kind=='wrinkle':
            for shift in (-6,0,6):self.create_line(x-10,y+shift+2,x-4,y+shift-1,x+3,y+shift+1,x+10,y+shift-2,smooth=True,fill=color,width=2)
        elif self.kind=='shape':
            self.create_arc(x-10,y-11,x+10,y+12,start=205,extent=135,style='arc',outline=color,width=2)
            self.create_line(x-12,y-2,x-7,y-2,fill=color,arrow='last');self.create_line(x+12,y-2,x+7,y-2,fill=color,arrow='last')
        elif self.kind=='repair':
            self.create_line(x-7,y+7,x+6,y-6,fill=color,width=7)
            self.create_line(x-5,y+5,x+4,y-4,fill=COLORS['panel'],width=2)
        elif self.kind=='body':
            self.create_oval(x-3,y-13,x+3,y-7,outline=color,width=1.5)
            self.create_line(x,y-7,x,y+8,fill=color,width=2)
            self.create_line(x-9,y-2,x,y-5,x+9,y-2,fill=color,width=2)
            self.create_line(x-6,y+13,x,y+5,x+6,y+13,fill=color,width=2)
        elif self.kind=='clothes':
            self.create_polygon(x-4,y-10,x-10,y-7,x-15,y-1,x-9,y+3,x-7,y,x-7,y+11,x+7,y+11,x+7,y,x+9,y+3,x+15,y-1,x+10,y-7,x+4,y-10,x,y-6,fill='',outline=color,width=1.5)
        elif self.kind=='background':
            self.create_rectangle(x-12,y-10,x+12,y+10,outline=color,width=1.5)
            self.create_oval(x+4,y-6,x+8,y-2,outline=color,width=1.5)
            self.create_line(x-10,y+7,x-3,y-2,x+2,y+4,x+6,y,x+11,y+7,fill=color,width=1.5)
        elif self.kind=='makeup':
            self.create_line(x-8,y+9,x+5,y-5,fill=color,width=5)
            self.create_line(x+4,y-6,x+9,y-11,fill=color,width=2)
            self.create_line(x-10,y+11,x-4,y+11,fill=color,width=2)
        elif self.kind=='crop':
            self.create_line(x-8,y-13,x-8,y+8,x+13,y+8,fill=color,width=2)
            self.create_line(x-13,y-8,x+8,y-8,x+8,y+13,fill=color,width=2)
        else:
            for dy,dx in [(-7,3),(0,-4),(7,5)]:
                self.create_line(x-10,y+dy,x+10,y+dy,fill=color,width=2)
                self.create_oval(x+dx-2,y+dy-2,x+dx+2,y+dy+2,fill=COLORS['panel'],outline=color,width=2)
        self.create_text(x,h-12,text=self.label,fill=color,font=ui_font(self,10,'bold' if self.selected else 'normal'))
        if self.focus_get() is self:self.create_rectangle(4,2,w-4,h-2,outline=COLORS['accent'],dash=(2,2))
        scale_canvas_art(self)

class WorkspaceUI:
    def queue_layout(self,event=None):
        if event is not None and event.widget not in (self.root,self.left_panel,self.right_panel,self.category_rail):return
        if getattr(self,'_layout_pending',None) is None:
            self._layout_pending=self.root.after_idle(self.finish_layout)
    def finish_layout(self):
        self._layout_pending=None;self.layout_workspace()
    def close_popups(self,event=None):
        if getattr(self,'_navigation_menu',None) is not None:self._navigation_menu.unpost()
        self.file_popup.place_forget();self.close_settings()
        return self.select_tool('pan') if event is not None else None
    def build_file_popup(self):
        self.file_popup=ttk.Frame(self.root,padding=14,relief='solid',borderwidth=1)
        ttk.Label(self.file_popup,text='文件',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w',pady=(0,8))
        self.openbutton=self.button(self.file_popup,'导入照片    Ctrl+O',lambda:self.file_action(self.choose))
        ttk.Label(self.file_popup,text='独立照片版 · 不含 HEIC / 实况 / 视频',style='Muted.TLabel').pack(fill='x',padx=8,pady=6)
        
        self.projectopen=self.button(self.file_popup,'打开项目',lambda:self.file_action(self.choose_project))
        self.projectsave=self.button(self.file_popup,'保存项目    Ctrl+S',lambda:self.file_action(self.save_recipe))
        self.savebutton=self.button(self.file_popup,'导出成片',lambda:self.file_action(self.export),accent=True)
    def file_action(self,fn):self.file_popup.place_forget();fn()
    def toggle_file(self):
        if self.file_popup.winfo_ismapped():self.file_popup.place_forget();return
        self.close_settings();self.file_popup.place(x=dp(self.root,16),y=self.top.winfo_height()+dp(self.root,4),width=dp(self.root,256));self.file_popup.lift()
    def build_settings_drawer(self):
        self.settings_drawer=ttk.Frame(self.root,padding=18,relief='solid',borderwidth=1)
        row=ttk.Frame(self.settings_drawer);row.pack(fill='x',pady=(0,16))
        ttk.Label(row,text='设置',font=('Microsoft YaHei UI',14,'bold')).pack(side='left')
        ttk.Button(row,text='关闭',command=self.close_settings).pack(side='right')
        container=ttk.Frame(self.settings_drawer);container.pack(fill='both',expand=True)
        scroll=tk.Canvas(container,bg=COLORS['panel'],highlightthickness=0);scroll.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(container,orient='vertical',command=scroll.yview);bar.pack(side='right',fill='y');scroll.configure(yscrollcommand=bar.set)
        content=ttk.Frame(scroll);window=scroll.create_window(0,0,window=content,anchor='nw');self.settings_content=content;self.drawer_scroll=scroll
        content.bind('<Configure>',lambda e:scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>',lambda e:scroll.itemconfigure(window,width=e.width))
        from language_ui import build_language_settings
        build_language_settings(self,content)
        section=Section(content,'计算设备')
        device=ttk.Combobox(section.body,textvariable=self.device_mode,values=['自动 · CPU＋GPU','仅 CPU'],state='readonly');device.pack(fill='x')
        device._aura_search_name='计算设备（CPU / GPU）'
        device.bind('<<ComboboxSelected>>',self.change_device_preference)
        ttk.Label(section.body,textvariable=self.device_details,style='Muted.TLabel',wraplength=300).pack(anchor='w',pady=9)
        ttk.Label(section.body,text='计算模式在下次启动时生效。',style='Muted.TLabel',wraplength=300).pack(anchor='w')
        section=Section(content,'界面显示')
        self.dpi_summary=tk.StringVar(value='')
        ttk.Label(section.body,textvariable=self.dpi_summary,style='Muted.TLabel',wraplength=300).pack(anchor='w')
        ttk.Label(section.body,text='自动跟随 Windows 缩放，移动到其他显示器后同步调整。照片的 100% 查看保持原图像素比例。',style='Muted.TLabel',wraplength=300).pack(anchor='w',pady=8)
        section=Section(content,'导入设置');self.preferences_panel=section
        ttk.Checkbutton(section.body,text='自动应用推荐美颜',variable=self.auto_recommend,command=self.change_recommend_preference).pack(anchor='w')
        ttk.Label(section.body,text='默认开启，仅影响后续新导入的照片。关闭后仍识别人像，可在“美颜”中使用推荐参数。',style='Muted.TLabel',wraplength=300).pack(anchor='w',pady=8)
        section=Section(content,'关于 AURA')
        ttk.Label(section.body,text='AI Unified Retouching Assistant',style='Muted.TLabel').pack(anchor='w')
        ttk.Label(section.body,text='版本 '+VERSION,style='Muted.TLabel').pack(anchor='w',pady=6)
        self.build_update_settings(section.body)
        def wheel(widget):
            widget.bind('<MouseWheel>',lambda e:(scroll.yview_scroll(-int(e.delta/120),'units'),'break')[1])
            for child in widget.winfo_children():wheel(child)
        wheel(content);wheel(scroll)
        from scroll_ui import attach_scroll
        self.drawer_scrolling=attach_scroll(scroll,content,bar)
    def toggle_settings(self):
        if self.settings_drawer.winfo_ismapped():self.close_settings();return
        self.file_popup.place_forget();self.settings_open=True;self.layout_workspace();self.settings_drawer.lift()
    def close_settings(self):
        self.settings_open=False
        if hasattr(self,'settings_drawer'):self.settings_drawer.place_forget()
    def setup_categories(self):
        self.setup_feature_navigation()
    def show_module_menu(self):
        self.show_feature_menu()
    def select_category(self,key):
        self.end_feature_compare()
        from feature_catalogue import LEGACY
        key=LEGACY.get(key,key)
        if key not in self.category_sections:raise ValueError('未知功能模块：'+key)
        self.active_category=key;self.category_title.set(key)
        for s in self.settings_panel.winfo_children():s.pack_forget()
        for s in self.category_sections[key]:
            if s.master is self.settings_panel:s.pack(fill='x',pady=(0,dp(self.root,8)))
        if key not in self._visited_categories:
            first=self.category_sections[key][0]
            if not first.opened:first.toggle()
            self._visited_categories.add(key)
        self.sync_navigation_scope()
        for name,button in self.category_buttons.items():button.set_active(name==key)
        self.root.update_idletasks();self.settings_scroll.configure(scrollregion=self.settings_scroll.bbox('all'));self.settings_scroll.yview_moveto(0)
        selected=self.category_buttons[key];top=self.rail_scroll.canvasy(0);y=selected.winfo_y();height=selected.winfo_height();viewport=self.rail_scroll.winfo_height()
        if y<top:self.rail_scroll.yview_moveto(y/max(1,self.category_rail.winfo_height()))
        elif y+height>top+viewport:self.rail_scroll.yview_moveto((y+height-viewport)/max(1,self.category_rail.winfo_height()))
        self.draw()
        self.schedule_feature_compare()
        if key=='调色' and getattr(self,'_color_navigation_ready',False):self.color_workbench.open()
        self._color_navigation_ready=True
    def layout_workspace(self,event=None):
        if event is not None and event.widget is not self.root:return
        if not getattr(self,'_simulated_dpi',False):
            dpi=window_dpi(self.root)
            if dpi!=self.root._ui_dpi:self.apply_ui_dpi(dpi)
        width,height=self.root.winfo_width(),self.root.winfo_height();scale=self.root._ui_scale
        logical=width/scale
        left=240 if logical>=1600 else 224 if logical>=1200 else 212
        right=408 if logical>=1600 else 376 if logical>=1200 else 336
        self.left_panel.configure(width=round(left*scale));self.right_panel.configure(width=round(right*scale))
        # ttk Frame.width is a physical length. The generic widget scaler
        # scales its children, but not this frame: at 150% the rail used to
        # stay 86px wide while icons grew to 96px, clipping the right edge.
        self.rail_panel.configure(width=dp(self.root,104))
        if hasattr(self,'nav_description_label'):self.nav_description_label.configure(wraplength=round((right-32)*scale))
        short=self.left_panel.winfo_height()/scale<720
        if short:self.navigation_hint.pack_forget()
        elif not self.navigation_hint.winfo_manager():self.navigation_hint.pack(side='bottom',anchor='w',pady=dp(self.root,12))
        nav_height=dp(self.root,max(96,min(210,self.left_panel.winfo_height()/scale-310)))
        if int(self.navigator.cget('height'))!=nav_height:
            self.navigator.configure(height=nav_height);self.make_navigation();self.draw()
        self.status_label.configure(wraplength=max(200,width-36))
        available=max(100,self.rail_scroll.winfo_height()-dp(self.root,16))
        for b in self.category_buttons.values():
            b.configure(width=dp(self.root,72),height=min(dp(self.root,64),max(dp(self.root,56),int(available/max(1,len(self.category_buttons)))-dp(self.root,4))))
            # A DPI change can end with the same physical allocation, in which
            # case Tk emits no Configure event. Repaint using final DIP metrics.
            b.paint()
        if hasattr(self,'dpi_summary'):self.dpi_summary.set(f'Windows 缩放 {round(scale*100)}% · 原生清晰渲染')
        if getattr(self,'_navigation_menu',None) is not None and self._navigation_menu.visible:self._navigation_menu.relayout()
        if self.settings_open:
            drawer=min(dp(self.root,408),width)
            self.settings_drawer.place(x=max(0,width-drawer),y=self.top.winfo_height(),width=drawer,height=max(1,height-self.top.winfo_height()))
    def apply_ui_dpi(self,dpi):
        from dark_ui import style
        set_ui_dpi(self.root,dpi);style(self.root);scale_widget_tree(self.root)
        for b in self.tool_buttons.values():b.paint()
        for b in self.category_buttons.values():b.paint()
        from core import ROOT
        from PIL import Image,ImageTk
        if hasattr(self,'brand_label'):
            size=dp(self.root,32)
            self.brand_icon=ImageTk.PhotoImage(Image.open(ROOT/'assets/aura.png').resize((size,size),Image.Resampling.LANCZOS))
            self.brand_label.configure(image=self.brand_icon)
        self.make_navigation();self.draw_filmstrip();self.draw()
    def set_app_icon(self):
        from core import ROOT
        p=ROOT/'assets/aura.ico'
        if p.exists():
            try:self.root.iconbitmap(default=str(p))
            except tk.TclError:pass
