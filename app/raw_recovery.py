"""Explicit RAW error recovery: no hidden engine change or live-edit mutation."""
import queue,threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from photo_document import validate_raw_settings
from dpi_support import dp

AUTO='按拍摄风格匹配'
BASIC='基础相机色彩（不使用 DCP）'

def recovery_settings(settings,action,profile=None):
    result=validate_raw_settings(settings)
    if action=='retry':return result
    if action=='compat':
        result.update(raw_engine='libraw-compat',camera_mode='profile',camera_look=False,process=1)
    elif action=='profile':
        if not profile:raise ValueError('请选择配置。')
        result.update(raw_engine='rawtherapee',camera_mode='profile',process=1,
                      camera_look=profile!=BASIC,camera_profile='as_shot' if profile in (AUTO,BASIC) else profile)
    else:raise ValueError('未知 RAW 恢复操作。')
    return validate_raw_settings(result)

def validate_edit_source(document,old_document=None,project=None,extensions=None):
    """Reject changes that cannot carry existing edits safely, before live assignment."""
    shape=old_document.rgb.shape[:2] if old_document is not None else tuple(project[0]['shape']) if project else None
    if shape is not None and tuple(document.rgb.shape[:2])!=tuple(shape):
        raise ValueError('新显影的尺寸与原编辑不一致，无法可靠保留蒙版和局部修复；已保留原编辑。')
    previous=old_document.metadata.get('camera_source') if old_document is not None else project[0].get('camera_source') if project else None
    current=document.metadata.get('camera_source')
    if previous!=current and 'embedded_preview' in (previous,current):
        raise ValueError('机内预览与 RAW 显影可能有不同的镜头校正，无法可靠保留局部编辑；已保留原编辑。')
    from fuji_profiles import base_ready
    state=(extensions or {}).get('color_filter',{})
    if state.get('preset',{}).get('raw_base') and state.get('amount',100)>0 and not base_ready(document):
        raise ValueError('当前富士 RAW 滤镜依赖线性 DCP 基底，所选显影不能保留该效果；已保留原编辑。请重试原配置，或先恢复套用前再切换。')

def validate_people(records,faces):
    if len(records)!=len(faces):raise ValueError('新显影的人物数量改变，无法可靠保留逐人编辑；已保留原编辑。')
    matched=set()
    for record_index,record in enumerate(records):
        a,b,c,d=record['box'];scores=[]
        for face in faces:
            e,f,g,h=face.box;area=max(0,min(c,g)-max(a,e))*max(0,min(d,h)-max(b,f))
            scores.append(area/max(1,(c-a)*(d-b)+(g-e)*(h-f)-area))
        index=max(range(len(scores)),key=scores.__getitem__) if scores else -1
        if index<0 or scores[index]<.5 or index in matched:raise ValueError('新显影的人脸位置改变，无法可靠保留逐人编辑；已保留原编辑。')
        if index!=record_index:raise ValueError('新显影的人物顺序改变，无法可靠保留逐人局部编辑；已保留原编辑。')
        matched.add(index)

class RecoveryDialog:
    def __init__(self,parent,path,settings,error):
        self.settings=validate_raw_settings(settings);self.path=Path(path);self.result=None
        self.previous_focus=parent.focus_get();self.previous_grab=parent.grab_current()
        self.window=window=tk.Toplevel(parent);window.title('RAW 显影未完成');window.transient(parent)
        self.queue=queue.Queue();self.lookup_started=False
        width=dp(parent,600);window.geometry(f'{width}x{dp(parent,540)}');window.minsize(dp(parent,480),dp(parent,500))
        body=ttk.Frame(window,padding=dp(parent,18));body.pack(fill='both',expand=True)
        self.intro=ttk.Label(body,text='当前图像与编辑已保留。选择一种方式继续，成功后才替换当前结果。',wraplength=width-dp(parent,50));self.intro.pack(fill='x',pady=(0,10))
        ttk.Label(body,text=self.path.name,wraplength=width-dp(parent,50)).pack(fill='x',pady=(0,8))
        box=ttk.Frame(body);box.pack(fill='both',expand=True,pady=(0,12))
        self.error=tk.Text(box,height=4,wrap='word',font='TkDefaultFont',borderwidth=1)
        scroll=ttk.Scrollbar(box,orient='vertical',command=self.error.yview);self.error.configure(yscrollcommand=scroll.set)
        self.error.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        self.error.insert('1.0',error);self.error.configure(state='disabled')
        self.retry=ttk.Button(body,text='重试',style='Accent.TButton',command=lambda:self.finish('retry'));self.retry.pack(fill='x',pady=4)
        self.choose=ttk.Button(body,text='选择其他配置',command=self.show_profiles);self.choose.pack(fill='x',pady=4)
        self.profile_area=ttk.Frame(body)
        self.profile=tk.StringVar(value=AUTO)
        ttk.Label(self.profile_area,text='相机配置').pack(anchor='w')
        self.combo=ttk.Combobox(self.profile_area,textvariable=self.profile,state='readonly',values=(AUTO,BASIC));self.combo.pack(fill='x',pady=4)
        self.profile_status=tk.StringVar(value='正在读取此照片对应机型的配置…')
        self.profile_note=ttk.Label(self.profile_area,textvariable=self.profile_status,wraplength=width-dp(parent,50));self.profile_note.pack(fill='x')
        ttk.Button(self.profile_area,text='使用所选配置',command=self.use_profile).pack(fill='x',pady=4)
        self.compat=ttk.Button(body,text='使用兼容引擎打开',command=self.use_compat);self.compat.pack(fill='x',pady=4)
        self.cancel=ttk.Button(body,text='取消 · 保留当前编辑',command=self.close);self.cancel.pack(fill='x',pady=(12,0))
        window.protocol('WM_DELETE_WINDOW',self.close);window.bind('<Escape>',lambda e:self.close())
        window.bind('<Configure>',self.layout)
        window.update_idletasks();window.grab_set();self.retry.focus_set()

    def layout(self,event):
        if event.widget is not self.window:return
        width=max(240,event.width-48)
        self.intro.configure(wraplength=width);self.profile_note.configure(wraplength=width)

    def show_profiles(self):
        self.profile_area.pack(fill='x',after=self.choose,pady=6)
        self.window.geometry(f'{self.window.winfo_width()}x{dp(self.window.master,710)}')
        self.combo.focus_set()
        if self.lookup_started:return
        self.lookup_started=True
        def find():
            try:
                import camera_profiles
                entries=camera_profiles.matching(camera_profiles.metadata(self.path))
                self.queue.put(([p['name'] for p in entries],None))
            except Exception as error:self.queue.put(([],str(error)))
        threading.Thread(target=find,daemon=True).start();self.window.after(50,self.poll_profiles)

    def poll_profiles(self):
        if not self.window.winfo_exists():return
        try:names,error=self.queue.get_nowait()
        except queue.Empty:self.window.after(50,self.poll_profiles);return
        self.combo.configure(values=[AUTO,BASIC]+sorted(set(names)))
        self.profile_status.set('配置列表读取失败；仍可尝试基础相机色彩。'+error if error else f'已找到 {len(set(names))} 个机型匹配配置。切换前会提示色彩差异。')

    def confirm(self,text):
        return messagebox.askyesno('确认更换 RAW 显影方式',text+'\n\n曝光、调色、美颜与局部编辑会尝试保留；只有显影及编辑恢复成功后才替换当前结果。若无法可靠对齐，将保留原编辑。',parent=self.window,default='no')

    def use_profile(self):
        if self.confirm('切换相机配置可能改变颜色、亮度和对比度。是否使用所选配置重新显影？'):
            self.finish('profile',self.profile.get())

    def use_compat(self):
        if self.confirm('兼容引擎使用 LibRaw 基础显影，不应用 DCP 相机风格。颜色、亮度和白平衡可能与当前结果不同。是否继续？'):
            self.finish('compat')

    def finish(self,action,profile=None):
        self.result=(recovery_settings(self.settings,action,profile),action)
        self.close()

    def close(self):
        if not self.window.winfo_exists():return
        self.window.grab_release();self.window.destroy()
        for widget,method in ((self.previous_grab,'grab_set'),(self.previous_focus,'focus_set')):
            try:
                if widget is not None and widget.winfo_exists():getattr(widget,method)()
            except tk.TclError:pass

def offer(app,path,settings,error,resume):
    parent=app.color_workbench.window if getattr(getattr(app,'color_workbench',None),'active',False) else app.root
    app._raw_recovery_pending=True
    try:
        dialog=RecoveryDialog(parent,path,settings,error)
        parent.wait_window(dialog.window)
        if dialog.result:
            selected,action=dialog.result
            def restart():
                app._raw_recovery_pending=False
                if action!='retry':
                    pending=getattr(app,'_pending_fuji_filter',None)
                    if pending:app.fail_raw_action(pending,'已取消未完成的滤镜套用，正在尝试其他显影方式。')
                resume(selected,action!='retry')
            app.root.after_idle(restart)
        else:
            app._raw_recovery_pending=False
            pending=getattr(app,'_pending_fuji_filter',None)
            if pending:app.fail_raw_action(pending,'已取消 RAW 显影，保留当前编辑。')
            app.status.set('已取消 RAW 显影，保留当前编辑。')
    except Exception:
        app._raw_recovery_pending=False
        raise
    return True
