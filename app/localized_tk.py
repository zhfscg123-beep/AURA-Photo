"""Localize Tk presentation while preserving canonical variables and selections.

Bindings and processing code continue to read the original values. A readonly
combo uses a separate display variable; selecting an English entry maps back to
its canonical value. Switching languages redraws labels, not the photo editor.
"""
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,simpledialog,font
import weakref,functools
from i18n import tr
_widgets=weakref.WeakKeyDictionary();_windows=weakref.WeakKeyDictionary()
_canvas=weakref.WeakKeyDictionary();_trees=weakref.WeakKeyDictionary();_lists=weakref.WeakKeyDictionary()
_menus=weakref.WeakKeyDictionary();_original={};_active=False;_refreshing=False
def _remember(widget):return _widgets.setdefault(widget,{})
def _translate_options(widget,options):
    result=dict(options);record=_remember(widget)
    for key in ('text','label'):
        if key in result and isinstance(result[key],str):record[key]=result[key];result[key]=tr(result[key])
    if isinstance(widget,ttk.Combobox) and 'values' in result:
        values=result['values'];values=widget.tk.splitlist(values) if isinstance(values,str) else tuple(values)
        record['values']=values;result['values']=tuple(tr(v) for v in values)
    if 'textvariable' in result and result['textvariable']:
        # Editable text is user input: do not translate it or attach a mirror.
        readonly_combo=isinstance(widget,ttk.Combobox) and str(result.get('state',record.get('state','readonly')))=='readonly'
        label=not isinstance(widget,(tk.Entry,ttk.Entry,tk.Spinbox,ttk.Spinbox))
        if readonly_combo or label:
            source=str(result['textvariable'])
            if source!=record.get('source') and source!=str(record.get('display','')):
                _clear_mirror(widget,record);_mirror(widget,record,source,readonly_combo)
            if 'display' in record:result['textvariable']=record['display']
    if 'state' in result:record['state']=result['state']
    return result
def _clear_mirror(widget,record):
    if record.get('trace'):
        try:widget.tk.call('trace','remove','variable',record['source'],'write',record['trace']);widget.deletecommand(record['trace'])
        except tk.TclError:pass
    record.pop('trace',None);record.pop('display',None);record.pop('source',None)
def _mirror(widget,record,source,combo):
    record['source']=source;record['display']=tk.StringVar(master=widget.master);record['syncing']=False
    ref=weakref.ref(widget)
    def source_changed(*_):
        w=ref()
        if w is None or record['syncing']:return
        try:
            record['syncing']=True;record['display'].set(tr(str(w.getvar(source))))
        except tk.TclError:pass
        finally:record['syncing']=False
    def display_changed(*_):
        w=ref()
        if w is None or record['syncing'] or _refreshing:return
        try:
            value=record['display'].get();values=record.get('values',())
            logical=next((v for v in values if tr(v)==value),value)
            record['syncing']=True;w.setvar(source,logical)
        finally:record['syncing']=False
    callback=widget._register(source_changed);record['trace']=callback
    widget.tk.call('trace','add','variable',source,'write',callback)
    if combo:record['display'].trace_add('write',display_changed)
    source_changed()
def install():
    global _active
    if _active:return
    _active=True
    init=tk.BaseWidget.__init__;_original['init']=init
    def widget_init(self,master,widgetName,cnf={},kw={},extra=()):
        # Tk needs _setup before variables can be mirrored. Construct first,
        # then translate once without changing values seen by the application.
        init(self,master,widgetName,cnf,kw,extra)
        options=dict(cnf) if isinstance(cnf,dict) else {};options.update(kw)
        changes={k:v for k,v in options.items() if k in ('text','textvariable','values','state')}
        if changes:_original['configure'](self,'configure',_translate_options(self,changes),{})
        def cleanup(event):
            if event.widget is self:_clear_mirror(self,_widgets.pop(self,{}))
        self.bind('<Destroy>',cleanup,add='+')
    tk.BaseWidget.__init__=widget_init
    configure=tk.Misc._configure;_original['configure']=configure
    def configured(self,cmd,cnf,kw):
        if cmd=='configure' and (isinstance(cnf,dict) or kw):
            options=dict(cnf or {});options.update(kw or {})
            return configure(self,cmd,_translate_options(self,options),{})
        return configure(self,cmd,cnf,kw)
    tk.Misc._configure=configured
    cget=tk.Misc.cget;_original['cget']=cget
    def logical_cget(self,key):
        record=_widgets.get(self,{})
        if key=='textvariable' and 'source' in record:return record['source']
        if key in record and key in ('text','label','values'):return record[key]
        return cget(self,key)
    tk.Misc.cget=logical_cget;tk.Misc.__getitem__=logical_cget
    get=ttk.Entry.get;_original['combo_get']=get
    def combo_get(self):
        record=_widgets.get(self,{})
        if 'source' in record:return str(self.getvar(record['source']))
        value=get(self);return next((v for v in record.get('values',()) if tr(v)==value),value)
    ttk.Combobox.get=combo_get
    combo_set=ttk.Combobox.set;_original['combo_set']=combo_set
    def set_combo(self,value):
        record=_widgets.get(self,{})
        if 'source' in record:self.setvar(record['source'],value)
        else:combo_set(self,tr(value))
    ttk.Combobox.set=set_combo
    title=tk.Wm.wm_title;_original['title']=title
    def window_title(self,string=None):
        if string is None:return _windows.get(self,title(self))
        _windows[self]=string;return title(self,tr(string))
    tk.Wm.title=tk.Wm.wm_title=window_title
    create=tk.Canvas.create_text;itemconfigure=tk.Canvas.itemconfigure;delete=tk.Canvas.delete
    _original.update(canvas_create=create,canvas_config=itemconfigure)
    def create_text(self,*args,**kwargs):
        text=kwargs.get('text');options=dict(kwargs)
        if isinstance(text,str):options['text']=tr(text)
        item=create(self,*args,**options)
        if isinstance(text,str):_canvas.setdefault(self,{})[item]=text
        return item
    def configure_item(self,tagOrId,cnf=None,**kw):
        options=dict(cnf or {}) if not isinstance(cnf,str) else {};options.update(kw)
        if 'text' in options:
            text=options['text']
            for item in self.find_withtag(tagOrId):_canvas.setdefault(self,{})[item]=text
            options['text']=tr(text);return itemconfigure(self,tagOrId,options)
        return itemconfigure(self,tagOrId,cnf,**kw)
    def delete_items(self,*args):
        record=_canvas.get(self,{})
        for tag in args:
            for item in self.find_withtag(tag):record.pop(item,None)
        return delete(self,*args)
    tk.Canvas.create_text=create_text;tk.Canvas.itemconfigure=tk.Canvas.itemconfig=configure_item;tk.Canvas.delete=delete_items
    measure=font.Font.measure
    font.Font.measure=lambda self,text,displayof=None:measure(self,tr(text),displayof)
    # Message and file dialogs are translated at the display boundary.
    for module,names in ((messagebox,('showinfo','showwarning','showerror','askquestion','askokcancel','askyesno','askyesnocancel','askretrycancel')),(filedialog,('askopenfilename','askopenfilenames','asksaveasfilename','askdirectory')),(simpledialog,('askstring','askinteger','askfloat'))):
        for name in names:
            original=getattr(module,name)
            def wrap(fn):
                @functools.wraps(fn)
                def dialog(*args,**kwargs):
                    args=tuple(tr(arg) if index<2 else arg for index,arg in enumerate(args))
                    for key in ('title','message','detail','prompt'):
                        if key in kwargs:kwargs[key]=tr(kwargs[key])
                    if 'filetypes' in kwargs:kwargs['filetypes']=[(tr(label),pattern) for label,pattern in kwargs['filetypes']]
                    return fn(*args,**kwargs)
                return dialog
            setattr(module,name,wrap(original))
    _install_collections()
def _install_collections():
    insert=ttk.Treeview.insert;item=ttk.Treeview.item;heading=ttk.Treeview.heading;delete=ttk.Treeview.delete
    _original.update(tree_item=item,tree_heading=heading)
    def options(data):return {k:tuple(tr(x) for x in v) if k=='values' else tr(v) if k=='text' else v for k,v in data.items()}
    def tree_insert(self,parent,index,iid=None,**kw):
        result=insert(self,parent,index,iid,**options(kw));_trees.setdefault(self,{'items':{},'headings':{}})['items'][result]=dict(kw);return result
    def tree_item(self,iid,option=None,**kw):
        if kw:_trees.setdefault(self,{'items':{},'headings':{}})['items'].setdefault(iid,{}).update(kw)
        result=item(self,iid,option,**options(kw))
        record=_trees.get(self,{}).get('items',{}).get(iid,{})
        if not kw and option in ('text','values') and option in record:return record[option]
        if not kw and option is None and isinstance(result,dict):result.update({k:v for k,v in record.items() if k in ('text','values')})
        return result
    def tree_heading(self,column,option=None,**kw):
        if 'text' in kw:_trees.setdefault(self,{'items':{},'headings':{}})['headings'][column]=kw['text']
        return heading(self,column,option,**options(kw))
    def tree_delete(self,*items):
        records=_trees.get(self,{}).get('items',{})
        def forget(i):
            for child in self.get_children(i):forget(child)
            records.pop(i,None)
        for i in items:forget(i)
        return delete(self,*items)
    ttk.Treeview.insert=tree_insert;ttk.Treeview.item=tree_item;ttk.Treeview.heading=tree_heading;ttk.Treeview.delete=tree_delete
    li=tk.Listbox.insert;ld=tk.Listbox.delete;lg=tk.Listbox.get
    _original.update(list_insert=li,list_delete=ld)
    def list_insert(self,index,*elements):
        records=_lists.setdefault(self,[]);pos=len(records) if index=='end' else int(self.index(index));records[pos:pos]=list(elements)
        return li(self,index,*(tr(x) for x in elements))
    def list_delete(self,first,last=None):
        records=_lists.setdefault(self,[]);a=int(self.index(first));b=a if last is None else int(self.index(last));del records[a:b+1]
        return ld(self,first,last)
    def list_get(self,first,last=None):
        records=_lists.get(self)
        if records is None:return lg(self,first,last)
        a=int(self.index(first));b=int(self.index(last)) if last is not None else a
        return tuple(records[a:b+1]) if last is not None else records[a] if a<len(records) else ''
    tk.Listbox.insert=list_insert;tk.Listbox.delete=list_delete;tk.Listbox.get=list_get
    add=tk.Menu.add;entryconfig=tk.Menu.entryconfigure
    _original['menu_config']=entryconfig
    def menu_add(self,itemType,cnf={},**kw):
        opts=dict(cnf);opts.update(kw);label=opts.get('label')
        if label is not None:opts['label']=tr(label)
        result=add(self,itemType,**opts)
        if label is not None:_menus.setdefault(self,{})[self.index('end')]=label
        return result
    def menu_config(self,index,cnf=None,**kw):
        opts=dict(cnf or {}) if not isinstance(cnf,str) else {};opts.update(kw)
        if 'label' in opts:
            _menus.setdefault(self,{})[self.index(index)]=opts['label'];opts['label']=tr(opts['label']);return entryconfig(self,index,opts)
        return entryconfig(self,index,cnf,**kw)
    tk.Menu.add=menu_add;tk.Menu.entryconfigure=tk.Menu.entryconfig=menu_config
def refresh():
    global _refreshing
    _refreshing=True
    try:
        for widget,record in list(_widgets.items()):
            try:
                changes={k:tr(v) for k,v in record.items() if k in ('text','label')}
                if 'values' in record:changes['values']=tuple(tr(v) for v in record['values'])
                if changes:_original['configure'](widget,'configure',changes,{})
                if 'display' in record:record['display'].set(tr(str(widget.getvar(record['source']))))
            except tk.TclError:pass
        for window,text in list(_windows.items()):
            try:_original['title'](window,tr(text))
            except tk.TclError:pass
        for canvas,items in list(_canvas.items()):
            for item,text in list(items.items()):
                try:_original['canvas_config'](canvas,item,text=tr(text))
                except tk.TclError:pass
        for tree,record in list(_trees.items()):
            try:
                for column,text in record['headings'].items():_original['tree_heading'](tree,column,text=tr(text))
                for item,data in record['items'].items():
                    kw={k:tuple(tr(v) for v in value) if k=='values' else tr(value) for k,value in data.items() if k in ('text','values')}
                    if kw:_original['tree_item'](tree,item,**kw)
            except tk.TclError:pass
        for box,items in list(_lists.items()):
            try:
                selected=box.curselection();_original['list_delete'](box,0,'end');_original['list_insert'](box,'end',*(tr(v) for v in items))
                for index in selected:box.selection_set(index)
            except tk.TclError:pass
        for menu,items in list(_menus.items()):
            for index,label in items.items():
                try:_original['menu_config'](menu,index,label=tr(label))
                except tk.TclError:pass
        roots={widget._root() for widget in list(_widgets)}
        for root in roots:
            try:root.event_generate('<<AuraLanguageChanged>>',when='tail')
            except tk.TclError:pass
    finally:_refreshing=False
