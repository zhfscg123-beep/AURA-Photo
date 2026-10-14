"""Per-record visibility, strength and removal, using the ordinary undo recipe."""
import tkinter as tk
from tkinter import ttk
from dpi_support import dp
from retouch_ui import LABELS

class EditRecordsUI:
    def show_edit_records(self):
        if not self.document or self.busy:return
        self.flush_parameters()
        if self.busy:return
        window=tk.Toplevel(self.root);window.title('编辑记录');window.transient(self.root)
        window.geometry(f'{min(dp(self.root,620),self.root.winfo_screenwidth()-40)}x{min(dp(self.root,530),self.root.winfo_screenheight()-80)}');window.grab_set()
        frame=ttk.Frame(window,padding=12);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='按原始顺序重放；隐藏或删除一笔后，后续修复会重新取样。',wraplength=dp(self.root,550)).pack(anchor='w')
        tree=ttk.Treeview(frame,columns=('visible','opacity'),show='tree headings',selectmode='browse');tree.heading('#0',text='修饰记录');tree.heading('visible',text='显示');tree.heading('opacity',text='不透明度');tree.column('#0',width=dp(self.root,270));tree.column('visible',width=dp(self.root,70));tree.column('opacity',width=dp(self.root,100));tree.pack(fill='both',expand=True,pady=10)
        enabled=tk.BooleanVar(value=True);opacity=tk.StringVar(value='100');note=tk.StringVar();records={}
        def populate():
            tree.delete(*tree.get_children());records.clear()
            for kind,values in [('manual',self.manual_records),('patch',self.patches)]:
                for i,rec in enumerate(values):
                    key=kind+str(i);records[key]=(values,i);title=LABELS.get(rec['mode'],rec['mode']) if kind=='manual' else ('迁移' if rec['mode']=='heal' else '仿制')
                    tree.insert('','end',iid=key,text=f'{title} · 第 {i+1} 笔',values=('是' if rec.get('enabled',True) else '否',rec['opacity']))
        def select(e=None):
            if not tree.selection():return
            values,i=records[tree.selection()[0]];enabled.set(values[i].get('enabled',True));opacity.set(str(values[i]['opacity']))
        def apply(delete=False):
            if self.busy or not tree.selection():return
            try:
                value=float(opacity.get())
                if not 0<=value<=100:raise ValueError()
            except ValueError:note.set('不透明度请输入0–100');return
            values,i=records[tree.selection()[0]];self.commit_edit('编辑修饰记录前')
            if delete:del values[i]
            else:values[i].update(enabled=enabled.get(),opacity=value)
            self.selected_patch=None;self.refresh();self.record('删除修饰记录' if delete else '调整修饰记录');self.sync_tools();populate();note.set('已更新；Ctrl＋Z可撤销。')
        row=ttk.Frame(frame);row.pack(fill='x');ttk.Checkbutton(row,text='显示',variable=enabled).pack(side='left');ttk.Label(row,text='不透明度').pack(side='left',padx=8);entry=ttk.Entry(row,textvariable=opacity,width=6);entry.pack(side='left');entry.bind('<Return>',lambda e:apply())
        buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=8)
        ttk.Button(buttons,text='应用',command=apply).pack(side='right');ttk.Button(buttons,text='删除所选',command=lambda:apply(True)).pack(side='right',padx=5)
        ttk.Label(frame,textvariable=note).pack(anchor='w',pady=5);tree.bind('<<TreeviewSelect>>',select);populate();self.records_window=window
