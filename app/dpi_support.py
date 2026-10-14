"""Native Windows DPI awareness and pixel metrics for the Tk workspace.

Fonts use points; physical lengths use one shared DIP-to-pixel conversion.
Image zoom and photo coordinates are deliberately independent of UI scaling.
"""
import sys

def enable_dpi():
    if sys.platform!='win32':return {'enabled':False,'reason':'non-Windows'}
    import ctypes
    from ctypes import wintypes
    user=ctypes.WinDLL('user32',use_last_error=True)
    try:
        # DPI_AWARENESS_CONTEXT is a pointer-sized pseudo handle. Passing -4
        # as ctypes' default 32-bit int fails on x64 with ERROR_INVALID_PARAMETER.
        user.SetProcessDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        user.SetProcessDpiAwarenessContext.restype=wintypes.BOOL
        ctypes.set_last_error(0)
        success=bool(user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
        error=ctypes.get_last_error()
        user.GetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        user.GetAwarenessFromDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        user.AreDpiAwarenessContextsEqual.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
        context=user.GetThreadDpiAwarenessContext()
        result={'enabled':user.GetAwarenessFromDpiAwarenessContext(context)==2,
            'pmv2':bool(user.AreDpiAwarenessContextsEqual(context,ctypes.c_void_p(-4))),
            'newly_set':success,'error':error}
    except AttributeError:
        shcore=ctypes.WinDLL('shcore');shcore.SetProcessDpiAwareness(2)
        result={'enabled':True,'pmv2':False,'legacy_api':True}
    try:
        shell=ctypes.WinDLL('shell32')
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes=[wintypes.LPCWSTR]
        shell.SetCurrentProcessExplicitAppUserModelID('AURA.Desktop')
    except (AttributeError,OSError):pass
    return result

def window_dpi(root):
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        try:
            user=ctypes.WinDLL('user32');user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
            user.GetDpiForWindow.argtypes=[wintypes.HWND];user.GetDpiForWindow.restype=wintypes.UINT
            hwnd=user.GetParent(root.winfo_id()) or root.winfo_id()
            value=user.GetDpiForWindow(hwnd)
            if value:return int(value)
        except (OSError,AttributeError):pass
    return round(root.winfo_fpixels('1i'))

def set_ui_dpi(root,dpi=None):
    dpi=window_dpi(root) if dpi is None else dpi
    root._ui_dpi=dpi;root._ui_scale=dpi/96
    root.tk.call('tk','scaling',dpi/72)
    # Recompute existing point fonts when moving between different-DPI monitors.
    for name in root.tk.splitlist(root.tk.call('font','names')):
        size=int(root.tk.call('font','configure',name,'-size'))
        if size>0:root.tk.call('font','configure',name,'-size',size)
    return root._ui_scale

def dp(widget,value):return round(value*getattr(widget.winfo_toplevel(),'_ui_scale',1))

def ui_font(widget,points=11,weight='normal'):
    # Explicit physical pixel sizes avoid Tk 8.6 caching an old point-font
    # realization after tk scaling changes on a different monitor.
    return ('Microsoft YaHei UI',-max(1,dp(widget,points*96/72)),weight)

def scale_widget_tree(root):
    """Scale requested pixel lengths once from original values, never cumulatively.

    ttk widths/heights are character/row units and remain untouched. Layout
    methods own adaptive panel widths; canvas photo coordinates stay unchanged.
    """
    scale=root._ui_scale
    def convert(value):
        values=value if isinstance(value,(tuple,list)) else (value,) if isinstance(value,(int,float)) else root.tk.splitlist(str(value))
        return tuple(round(float(str(v))*scale) for v in values)
    def visit(widget):
        if getattr(widget,'_aura_managed_geometry',False):return
        original=getattr(widget,'_dip_geometry',None)
        if original is None:
            options={};manager={};kind=widget.winfo_class()
            for key in ('padding','wraplength','length'):
                if key in widget.keys():options[key]=widget.cget(key)
            if 'font' in widget.keys():
                value=root.tk.splitlist(str(widget.cget('font')))
                if len(value)>=2:
                    try:
                        size=int(value[1]);pixels=size*96/72 if size>0 else -size/scale
                        if size:options['font']=(value[0],pixels,*value[2:])
                    except ValueError:pass
            if kind=='Canvas':
                # Center photo canvas is fill/expand; only the fixed utility
                # canvases have explicit dimensions that need scaling.
                if widget is not getattr(root,'_photo_canvas',None):options['height']=widget.cget('height')
                if type(widget).__name__ in ('CategoryButton','ToolButton','FacePresetButton'):options['width']=widget.cget('width')
                options['xscrollincrement']=widget.cget('xscrollincrement')
            if widget.winfo_manager()=='pack':
                info=widget.pack_info()
                manager={k:info[k] for k in ('padx','pady','ipadx','ipady')}
            original=widget._dip_geometry=(options,manager)
        options,manager=original
        for key,value in options.items():
            if key=='font':
                widget.configure(font=(value[0],-max(1,round(value[1]*scale)),*value[2:]));continue
            scaled=convert(value)
            if not scaled:continue
            widget.configure(**{key:scaled if key=='padding' else scaled[0]})
        if manager and widget.winfo_manager()=='pack':widget.pack_configure(**{k:convert(v) for k,v in manager.items()})
        for child in widget.winfo_children():visit(child)
    for child in root.winfo_children():visit(child)

def scale_canvas_art(canvas):
    scale=getattr(canvas.winfo_toplevel(),'_ui_scale',1)
    canvas.scale('all',0,0,scale,scale)
    for item in canvas.find_all():
        if canvas.type(item) in ('line','oval','rectangle','arc','polygon'):
            canvas.itemconfigure(item,width=float(canvas.itemcget(item,'width'))*scale)
