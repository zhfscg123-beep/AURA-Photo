"""Unicode Explorer file drops for Tk HWNDs, without a third-party Tk DLL."""
import ctypes,queue,sys
from pathlib import Path

def photo_paths(paths,extensions):
    accepted=[];ignored=[];seen=set()
    for item in paths:
        try:
            p=Path(item).resolve();key=str(p).casefold()
            if key in seen:continue
            seen.add(key)
            if p.is_file() and p.suffix.casefold() in extensions:accepted.append(str(p))
            else:ignored.append(str(p))
        except (OSError,ValueError):ignored.append(str(item))
    return accepted,ignored

class FileDrop:
    """Subclass only this app's windows on their owning Tk thread.

    The native callback copies HDROP strings and frees HDROP. A Tk timer
    dispatches them later, so no Tcl or import work runs inside the WndProc.
    """
    def __init__(self,root,receive):
        self.root=root;self.receive=receive;self.windows=set();self.pending=queue.Queue();self.closed=False;self.timer=None
        if sys.platform!='win32':return
        from ctypes import wintypes as w
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.shell=ctypes.WinDLL('shell32',use_last_error=True)
        self.common=ctypes.WinDLL('comctl32',use_last_error=True)
        result=ctypes.c_ssize_t;pointer=ctypes.c_size_t
        self.callback_type=ctypes.WINFUNCTYPE(result,w.HWND,w.UINT,w.WPARAM,w.LPARAM,pointer,pointer)
        self.enum_type=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        self.user.GetAncestor.argtypes=[w.HWND,w.UINT];self.user.GetAncestor.restype=w.HWND
        self.user.EnumChildWindows.argtypes=[w.HWND,self.enum_type,w.LPARAM];self.user.EnumChildWindows.restype=w.BOOL
        self.user.IsWindow.argtypes=[w.HWND];self.user.IsWindow.restype=w.BOOL
        self.shell.DragAcceptFiles.argtypes=[w.HWND,w.BOOL]
        self.shell.DragQueryFileW.argtypes=[w.HANDLE,w.UINT,w.LPWSTR,w.UINT];self.shell.DragQueryFileW.restype=w.UINT
        self.shell.DragFinish.argtypes=[w.HANDLE]
        self.common.SetWindowSubclass.argtypes=[w.HWND,self.callback_type,pointer,pointer];self.common.SetWindowSubclass.restype=w.BOOL
        self.common.RemoveWindowSubclass.argtypes=[w.HWND,self.callback_type,pointer];self.common.RemoveWindowSubclass.restype=w.BOOL
        self.common.DefSubclassProc.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];self.common.DefSubclassProc.restype=result
        self.callback=self.callback_type(self._message);self.identity=id(self)
        root.update_idletasks();self.hwnd=self.user.GetAncestor(root.winfo_id(),2)
        self.sync();root.bind('<Map>',self._mapped,add='+');root.bind('<Destroy>',self._destroy,add='+')
        self.timer=root.after(80,self.pump)
    def _message(self,hwnd,message,wp,lp,identity,data):
        if message==0x233:
            try:
                count=self.shell.DragQueryFileW(wp,0xffffffff,None,0)
                paths=[]
                for i in range(count):
                    size=self.shell.DragQueryFileW(wp,i,None,0)
                    buffer=ctypes.create_unicode_buffer(size+1)
                    self.shell.DragQueryFileW(wp,i,buffer,size+1);paths.append(buffer.value)
                self.pending.put(paths)
            finally:self.shell.DragFinish(wp)
            return 0
        if message==0x82:
            self.common.RemoveWindowSubclass(hwnd,self.callback,self.identity);self.windows.discard(hwnd)
        return self.common.DefSubclassProc(hwnd,message,wp,lp)
    def sync(self):
        if self.closed or not hasattr(self,'user'):return
        def add(hwnd):
            if hwnd not in self.windows and self.common.SetWindowSubclass(hwnd,self.callback,self.identity,0):
                self.shell.DragAcceptFiles(hwnd,True);self.windows.add(hwnd)
        add(self.hwnd)
        callback=self.enum_type(lambda hwnd,lp:(add(hwnd),True)[1])
        self.user.EnumChildWindows(self.hwnd,callback,0)
    def _mapped(self,event):
        if not self.closed:self.root.after_idle(self.sync)
    def pump(self):
        if self.closed:return
        while not self.pending.empty():self.receive(self.pending.get_nowait())
        self.timer=self.root.after(80,self.pump)
    def _destroy(self,event):
        if event.widget is self.root:self.close()
    def close(self):
        if self.closed:return
        self.closed=True
        if self.timer:
            try:self.root.after_cancel(self.timer)
            except Exception:pass
        for hwnd in list(self.windows):
            if self.user.IsWindow(hwnd):
                self.shell.DragAcceptFiles(hwnd,False);self.common.RemoveWindowSubclass(hwnd,self.callback,self.identity)
        self.windows.clear()
