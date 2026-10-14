"""AURA canvas popovers. No OS menu widgets or nested native message loops."""
import re,tkinter as tk
from tkinter import font as tkfont
from dark_ui import COLORS
from dpi_support import dp,ui_font

class RoundedMenu:
    def __init__(self,root,title='',parent=None):
        self.root=root;self.title=title;self.parent=parent;self.items=[];self.active=None;self.child=None
        self.anchor=None;self.visible=False;self.offset=0;self.hover_job=None;self.alive=True
        self.canvas=tk.Canvas(root,highlightthickness=0,bg=COLORS['panel'],takefocus=1,cursor='arrow')
        self.canvas._aura_managed_geometry=True
        self.canvas.bind('<Motion>',self.motion);self.canvas.bind('<ButtonPress-1>',self.click)
        self.canvas.bind('<MouseWheel>',self.wheel);self.canvas.bind('<Leave>',lambda e:self.cancel_hover())
        self.canvas.bind('<FocusIn>',lambda e:self.paint());self.canvas.bind('<FocusOut>',self.focus_out)
        self.canvas.bind('<KeyPress>',self.key)
    @property
    def top(self):return self.parent.top if self.parent else self
    def add_command(self,label,command,state='normal',shortcut='',icon=''):
        parts=re.split(r'\s{2,}',label,maxsplit=1)
        self.items.append(dict(kind='command',label=parts[0],command=command,state=state,shortcut=shortcut or (parts[1] if len(parts)>1 else ''),icon=icon))
    def add_separator(self):self.items.append(dict(kind='separator',label='',state='disabled'))
    def add_checkbutton(self,label,variable,command):self.items.append(dict(kind='check',label=label,variable=variable,command=command,state='normal',shortcut='',icon=''))
    def add_cascade(self,label,menu):
        menu.parent=self;self.items.append(dict(kind='cascade',label=label,menu=menu,state='normal',shortcut='',icon='group'))
    def index(self,value):return len(self.items)-1 if value=='end' else int(value)
    def entrycget(self,index,option):return self.items[int(index)].get(option,'')
    def winfo_exists(self):return self.alive and self.canvas.winfo_exists()
    def winfo_ismapped(self):return self.visible and self.canvas.winfo_ismapped()
    def focus_set(self):self.canvas.focus_set()
    def cancel_hover(self):
        if self.hover_job is not None:
            self.root.after_cancel(self.hover_job);self.hover_job=None
    def measure(self):
        font=tkfont.Font(self.root,font=ui_font(self.root,10));hint=tkfont.Font(self.root,font=ui_font(self.root,9))
        self.width=max(dp(self.root,240),max((font.measure(i['label'])+hint.measure(i.get('shortcut',''))+dp(self.root,86) for i in self.items),default=0))
        self.rows=[];y=0
        for i in self.items:
            height=dp(self.root,10 if i['kind']=='separator' else 38);self.rows.append((y,y+height));y+=height
        self.total=y;self.header=dp(self.root,35);self.pad=dp(self.root,8)
    def place(self,x,y,limit_width=None,limit_height=None):
        self.measure();rw,rh=self.root.winfo_width(),self.root.winfo_height();margin=dp(self.root,8)
        self.width=min(self.width,limit_width or rw-2*margin,rw-2*margin)
        preferred=self.total+self.header+2*self.pad
        self.height=max(dp(self.root,90),min(preferred,limit_height or rh-2*margin,rh-2*margin))
        self.x=max(margin,min(round(x),rw-self.width-margin));self.y=max(margin,min(round(y),rh-self.height-margin))
        self.viewport=self.height-self.header-self.pad
        self.offset=max(0,min(self.offset,max(0,self.total-self.viewport)))
        self.canvas.configure(width=self.width,height=self.height)
        self.canvas.place(x=self.x,y=self.y,width=self.width,height=self.height);self.root.tk.call('raise',self.canvas._w);self.visible=True;self.paint()
    def post(self,x,y):
        self.root.update_idletasks();rx=x-self.root.winfo_rootx();ry=y-self.root.winfo_rooty()
        available=self.root.winfo_height()-ry-dp(self.root,8)
        self.place(rx,ry,limit_height=available);self.focus_set();self.activate(self.first())
    def first(self):return next((n for n,i in enumerate(self.items) if i['state']!='disabled'),None)
    def activate(self,index):
        if index is not None and (not 0<=index<len(self.items) or self.items[index]['state']=='disabled'):return
        if self.active!=index:
            self.close_child();self.active=index
        self.ensure_visible();self.paint()
    def ensure_visible(self):
        if self.active is None or not hasattr(self,'viewport'):return
        a,b=self.rows[self.active]
        if a<self.offset:self.offset=a
        if b>self.offset+self.viewport:self.offset=b-self.viewport
        self.offset=max(0,min(self.offset,max(0,self.total-self.viewport)))
    def close_child(self):
        self.cancel_hover()
        if self.child:self.child.unpost();self.child=None
    def open_child(self,focus=False):
        if self.active is None or self.items[self.active]['kind']!='cascade':return
        child=self.items[self.active]['menu'];child.measure();gap=dp(self.root,4);margin=dp(self.root,8)
        right=self.root.winfo_width()-self.x-self.width-gap-margin;left=self.x-gap-margin
        preferred=min(child.width,max(right,left))
        x=self.x+self.width+gap if right>=left else self.x-preferred-gap
        y=self.y+self.header+self.rows[self.active][0]-self.offset
        if self.child and self.child is not child:self.child.unpost()
        self.child=child;child.place(x,y,limit_width=max(dp(self.root,120),preferred))
        if focus:child.focus_set();child.activate(child.first())
    def relayout(self):
        if not self.visible:return
        self.close_child()
        if self.anchor and self.anchor.winfo_exists():
            self.place(self.anchor.winfo_rootx()-self.root.winfo_rootx(),self.anchor.winfo_rooty()+self.anchor.winfo_height()-self.root.winfo_rooty(),limit_height=self.root.winfo_height()-(self.anchor.winfo_rooty()+self.anchor.winfo_height()-self.root.winfo_rooty())-dp(self.root,8))
        else:self.place(self.x,self.y)
        self.ensure_visible();self.paint()
    def unpost(self):
        self.close_child();self.visible=False;self.canvas.place_forget()
    def destroy(self):
        self.unpost()
        for item in self.items:
            if item['kind']=='cascade':item['menu'].destroy()
        self.alive=False;self.canvas.destroy()
    def inside(self,widget):
        if widget is self.canvas:return True
        return bool(self.child and self.child.inside(widget))
    def dismiss_outside(self,event):
        if self.visible and not self.inside(event.widget) and event.widget is not self.anchor:self.unpost()
    def focus_out(self,event):
        self.paint()
        def check():
            if self.top.alive and self.top.visible:
                focus=self.root.focus_get()
                if focus is None or not self.top.inside(focus):self.top.unpost()
        self.root.after_idle(check)
    def row_at(self,y):
        if y<self.header or y>self.header+self.viewport:return None
        value=y-self.header+self.offset
        return next((n for n,(a,b) in enumerate(self.rows) if a<=value<b and self.items[n]['state']!='disabled'),None)
    def motion(self,event):
        index=self.row_at(event.y)
        if index is None:return
        self.activate(index)
        if self.items[index]['kind']=='cascade' and not self.child:
            self.cancel_hover()
            def open_delayed():
                self.hover_job=None
                if self.visible and self.active==index:self.open_child()
            self.hover_job=self.root.after(160,open_delayed)
    def click(self,event):
        index=self.row_at(event.y)
        if index is not None:
            self.activate(index)
            if self.items[index]['kind']=='cascade':self.open_child(True)
            else:self.invoke(index)
        return 'break'
    def invoke(self,index):
        if not self.visible:return
        item=self.items[index]
        if item['state']=='disabled' or item['kind']=='separator':return
        if item['kind']=='cascade':self.activate(index);self.open_child(True);return
        self.top.unpost()
        def execute():
            if item['kind']=='check':item['variable'].set(not bool(item['variable'].get()))
            item['command']()
        self.root.after_idle(execute)
    def move(self,step):
        available=[i for i,x in enumerate(self.items) if x['state']!='disabled']
        if not available:return
        at=available.index(self.active) if self.active in available else (-1 if step>0 else 0)
        self.activate(available[(at+step)%len(available)])
    def wheel(self,event):
        self.close_child();self.offset=max(0,min(max(0,self.total-self.viewport),self.offset-int(event.delta/120)*dp(self.root,38)));self.paint();return 'break'
    def key(self,event):
        if event.keysym=='Down':self.move(1)
        elif event.keysym=='Up':self.move(-1)
        elif event.keysym=='Home':self.activate(self.first())
        elif event.keysym=='End':self.activate(next((n for n in range(len(self.items)-1,-1,-1) if self.items[n]['state']!='disabled'),None))
        elif event.keysym in ('Return','space'):
            if self.active is not None:self.invoke(self.active)
        elif event.keysym=='Right':self.open_child(True)
        elif event.keysym=='Left' and self.parent:self.unpost();self.parent.child=None;self.parent.focus_set()
        elif event.keysym=='Escape':
            top=self.top;top.unpost()
            if top.anchor:top.anchor.focus_set()
        elif event.keysym=='Tab':
            top=self.top;top.unpost()
            if top.anchor:(top.anchor.tk_focusPrev() if event.state&1 else top.anchor.tk_focusNext()).focus_set()
        else:return
        return 'break'
    def round(self,x,y,w,h,r,fill,outline=''):
        self.canvas.create_polygon(x+r,y,x+w-r,y,x+w,y+r,x+w,y+h-r,x+w-r,y+h,x+r,y+h,x,y+h-r,x,y+r,fill=fill,outline=outline,smooth=True)
    def fit_text(self,text,space,font):
        from i18n import tr
        text=tr(text)
        if font.measure(text)<=space:return text
        while text and font.measure(text+'…')>space:text=text[:-1]
        return text+'…'
    def paint(self):
        if not self.visible:return
        c=self.canvas;c.delete('all');w,h=self.width,self.height;s=lambda n:dp(self.root,n)
        self.round(s(2),s(3),w-s(4),h-s(4),s(12),'#dfe5ed')
        self.round(s(1),s(1),w-s(4),h-s(5),s(12),COLORS['panel'],COLORS['border'])
        c.create_text(s(16),s(18),text=self.title,anchor='w',fill=COLORS['muted'],font=ui_font(self.root,9,'bold'))
        font=tkfont.Font(self.root,font=ui_font(self.root,10));hint=tkfont.Font(self.root,font=ui_font(self.root,9))
        for n,item in enumerate(self.items):
            a,b=self.rows[n];y=self.header+a-self.offset;rh=b-a
            if y<self.header or y+rh>self.header+self.viewport:continue
            if item['kind']=='separator':c.create_line(s(16),y+rh/2,w-s(16),y+rh/2,fill=COLORS['border']);continue
            disabled=item['state']=='disabled';color='#7e8999' if disabled else COLORS['text']
            if n==self.active:
                self.round(s(7),y,w-s(18),rh,s(7),COLORS['selected'])
                if c.focus_get() is c:self.round(s(7),y,w-s(18),rh,s(7),'',COLORS['accent'])
            cy=y+rh/2;shortcut=item.get('shortcut','');reserve=hint.measure(shortcut)+s(24) if shortcut else s(22)
            label=self.fit_text(item['label'],max(0,w-s(51)-reserve),font)
            if item['kind']=='check':
                checked=bool(item['variable'].get());self.round(s(15),cy-s(7),s(14),s(14),s(3),COLORS['accent'] if checked else COLORS['panel'],COLORS['accent'] if checked else COLORS['border'])
                if checked:c.create_line(s(18),cy,s(21),cy+s(3),s(26),cy-s(3),fill='white',width=s(1.5))
            else:
                c.create_oval(s(19),cy-s(3),s(25),cy+s(3),fill=COLORS['accent'] if n==self.active else '#b8c5d7',outline='')
            c.create_text(s(38),cy,text=label,anchor='w',fill=color,font=ui_font(self.root,10))
            if shortcut:c.create_text(w-s(17),cy,text=shortcut,anchor='e',fill=COLORS['muted'],font=ui_font(self.root,9))
            if item['kind']=='cascade':c.create_line(w-s(24),cy-s(4),w-s(20),cy,w-s(24),cy+s(4),fill=COLORS['muted'],width=s(1.4))
        if self.total>self.viewport:
            rail=h-self.header-s(16);thumb=max(s(18),rail*self.viewport/self.total);top=self.header+(rail-thumb)*self.offset/max(1,self.total-self.viewport)
            self.round(w-s(8),top,s(3),thumb,s(1.5),'#b8c5d7')
