"""Non-focus-taking descriptions for compact desktop controls."""
import tkinter as tk
from tkinter import ttk
from dpi_support import dp

def tooltip(widget,text):
    timer=None;window=None
    def hide(event=None):
        nonlocal timer,window
        if timer is not None:
            try:widget.after_cancel(timer)
            except tk.TclError:pass
            timer=None
        if window is not None:
            try:window.destroy()
            except tk.TclError:pass
            window=None
    def show():
        nonlocal timer,window
        timer=None
        if not widget.winfo_exists():return
        window=tk.Toplevel(widget);window.overrideredirect(True)
        ttk.Label(window,text=text,padding=8,wraplength=dp(widget._root(),280),relief='solid',borderwidth=1).pack()
        window.geometry(f'+{widget.winfo_rootx()}+{widget.winfo_rooty()+widget.winfo_height()+4}')
    def enter(event=None):
        nonlocal timer
        hide();timer=widget.after(450,show)
    for event in ('<Enter>','<FocusIn>'):widget.bind(event,enter,add='+')
    for event in ('<Leave>','<FocusOut>','<ButtonPress>','<Destroy>'):widget.bind(event,hide,add='+')
