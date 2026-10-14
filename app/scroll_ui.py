"""Hover-based wheel routing for static and dynamically created Tk controls."""
import tkinter as tk
import math
from tkinter import ttk
from dpi_support import dp


class ScrollRouter:
    def __init__(self,root):
        self.root=root;self.panes=[];self.tag='AURAScroll'+str(id(self))
        root.bind_class(self.tag,'<MouseWheel>',self.wheel)
        root.bind_class(self.tag,'<Button-4>',self.wheel)
        root.bind_class(self.tag,'<Button-5>',self.wheel)
        root.bind_all('<Map>',self.mapped,add='+')
    def pane_for(self,widget):
        while widget is not None:
            found=next((p for p in self.panes if widget in (p.canvas,p.content)),None)
            if found:return found
            widget=getattr(widget,'master',None)
    def tag_widget(self,widget):
        if self.pane_for(widget):
            tags=widget.bindtags()
            if self.tag not in tags:widget.bindtags((self.tag,)+tags)
        for child in widget.winfo_children():self.tag_widget(child)
    def mapped(self,event):
        if self.pane_for(event.widget):self.tag_widget(event.widget)
    def wheel(self,event):
        hovered=self.root.winfo_containing(event.x_root,event.y_root)
        pane=self.pane_for(hovered) if hovered is not None else self.pane_for(event.widget)
        if not pane:return
        grabbed=self.root.grab_current()
        if grabbed is not None and getattr(grabbed,'dragging',False):return 'break'
        delta=getattr(event,'delta',0) or (120 if getattr(event,'num',None)==4 else -120 if getattr(event,'num',None)==5 else 0)
        pane.move_pixels(-delta/120*dp(self.root,36))
        return 'break'


class ScrollPane:
    def __init__(self,canvas,content,bar=None,compact=False):
        self.canvas=canvas;self.content=content;self.bar=bar;self.pending=None;self.compact=compact;self.pixel_remainder=0.
        root=canvas._root()
        if not hasattr(root,'_aura_scroll_router'):root._aura_scroll_router=ScrollRouter(root)
        router=root._aura_scroll_router;router.panes.append(self)
        self.note=tk.StringVar(master=root)
        self.hint=ttk.Frame(canvas.master);self.hint.pack(side='bottom',fill='x',before=canvas)
        if not compact:
            self.up=ttk.Button(self.hint,text='向上',width=0,style='Compact.TButton',command=lambda:self.move_pixels(-canvas.winfo_height()*.8));self.up.pack(side='left')
            self.down=ttk.Button(self.hint,text='向下',width=0,style='Compact.TButton',command=lambda:self.move_pixels(canvas.winfo_height()*.8));self.down.pack(side='right')
        else:self.up=self.down=None
        ttk.Label(self.hint,textvariable=self.note,style='Muted.TLabel',anchor='center',wraplength=90 if compact else 260).pack(fill='x',expand=True)
        canvas.configure(yscrollcommand=self.view_changed)
        for widget in (canvas,content):widget.bind('<Configure>',lambda e:self.schedule_sync(),add='+')
        router.tag_widget(canvas);self.schedule_sync()
    def schedule_sync(self):
        if self.pending is None:self.pending=self.canvas.after_idle(self.sync)
    def sync(self):
        self.pending=None
        if not self.canvas.winfo_exists():return
        bounds=self.canvas.bbox('all')
        if bounds:self.canvas.configure(scrollregion=bounds)
        self.view_changed(*self.canvas.yview())
    def view_changed(self,first,last):
        first,last=float(first),float(last)
        if self.bar:self.bar.set(first,last)
        above=first>.001;below=last<.999
        if self.compact:self.note.set('可上下滑动' if above and below else '↓ 可下滑' if below else '↑ 可上滑 · 已到底' if above else '全部显示')
        else:self.note.set('↑ 上方还有内容 · ↓ 下方还有内容' if above and below else '↓ 下方还有内容' if below else '↑ 上方还有内容 · 已到底' if above else '全部内容已显示')
        if self.up:self.up.configure(state='normal' if above else 'disabled');self.down.configure(state='normal' if below else 'disabled')
    def move_pixels(self,pixels):
        bounds=self.canvas.bbox('all')
        if not bounds:return
        height=max(1,bounds[3]-bounds[1]);visible=self.canvas.winfo_height()
        if height<=visible:self.pixel_remainder=0.;self.canvas.yview_moveto(0);return
        if pixels*self.pixel_remainder<0:self.pixel_remainder=0.
        self.pixel_remainder+=pixels;pixels=math.trunc(self.pixel_remainder)
        if not pixels:return
        self.pixel_remainder-=pixels
        top=self.canvas.yview()[0]*height
        self.canvas.yview_moveto(max(0,min(height-visible,top+pixels))/height)


def attach_scroll(canvas,content,bar=None,compact=False):
    pane=getattr(canvas,'_aura_scroll_pane',None)
    if pane is None:canvas._aura_scroll_pane=pane=ScrollPane(canvas,content,bar,compact)
    return pane
