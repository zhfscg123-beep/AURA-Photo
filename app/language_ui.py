"""Immediate, persistent interface language selection."""
import tkinter as tk
from tkinter import ttk,messagebox
from i18n import language,set_language
from dark_ui import Section
def build_language_settings(app,parent):
    section=Section(parent,'语言 / Language')
    selected=tk.StringVar(value='English' if language()=='en_US' else '简体中文')
    combo=ttk.Combobox(section.body,textvariable=selected,values=('简体中文','English'),state='readonly')
    combo.pack(fill='x');combo._aura_search_name='语言 / Language'
    ttk.Label(section.body,text='立即切换界面语言，保留当前照片和编辑状态。',style='Muted.TLabel',wraplength=300).pack(anchor='w',pady=8)
    def change(event=None):
        code='en_US' if combo.current()==1 else 'zh_CN'
        try:set_language(code)
        except OSError as error:
            selected.set('English' if language()=='en_US' else '简体中文')
            messagebox.showerror('无法保存语言设置',str(error),parent=app.root)
    combo.bind('<<ComboboxSelected>>',change)
    app.language_control=combo;app.language_variable=selected
    app.root.bind('<<AuraLanguageChanged>>',lambda e:app.queue_layout(),add='+')
