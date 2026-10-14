"""Hold a process-local reference to the installer-visible running-app mutex."""
import os,ctypes

APP_MUTEX='AURA.Photo.Standalone.Running'

def register_app_mutex(root):
    if os.name!='nt':return None
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle.restype=ctypes.c_int
    handle=kernel.CreateMutexW(None,False,APP_MUTEX)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    def close(event):
        nonlocal handle
        if event.widget is root and handle:kernel.CloseHandle(handle);handle=None
    root.bind('<Destroy>',close,add='+')
    return handle
