"""Automatic drafts, cache reuse and recoverable desktop workflow."""
import copy,threading,time,tkinter as tk
from tkinter import ttk,messagebox
from pathlib import Path
from dark_ui import Section
from dpi_support import dp
from recovery_store import RecoveryStore,compact,analysis_key,frozen
import liquify

class WorkflowUI:
    def init_workflow(self):
        import os
        from app_preferences import preferences
        prefs=preferences();quota=prefs.get('cache_limit_GB',2)
        if quota not in (0,1,2,4):quota=2
        self.recovery=RecoveryStore(cache_limit=quota*1024**3)
        self.auto_save=tk.BooleanVar(value=(os.environ.get('AURA_AUTOSAVE')!='0') if 'AURA_AUTOSAVE' in os.environ else prefs.get('auto_save',True))
        self.reuse_cache=tk.BooleanVar(value=prefs.get('reuse_cache',True));self.cache_choice=tk.StringVar(value={0:'不保留 AI 缓存',1:'1 GB',2:'2 GB',4:'4 GB'}[quota])
        self.auto_note=tk.StringVar(value='自动保存已开启' if self.auto_save.get() else '自动保存已关闭')
        self._draft_dirty=False;self._draft_time=time.monotonic();self._draft_thread=None;self._draft_result=None;self._draft_receipt=None
        self._last_analysis={};self._closing=False;self._skip_recovery=False
        self.workflow_extensions={};self.batch_selected=set()
    def build_file_popup(self):
        super().build_file_popup()
        self.button(self.file_popup,'自动保存与恢复',lambda:self.file_action(self.show_recovery))
        self.button(self.file_popup,'批量同步与导出',lambda:self.file_action(self.show_batch))
    def build_settings_drawer(self):
        super().build_settings_drawer()
        section=Section(self.settings_content,'自动保存与缓存')
        ttk.Checkbutton(section.body,text='自动保存编辑记录',variable=self.auto_save,command=self.save_workflow_preferences).pack(anchor='w',pady=4)
        ttk.Checkbutton(section.body,text='重开时复用有效 AI 缓存',variable=self.reuse_cache,command=self.save_workflow_preferences).pack(anchor='w',pady=4)
        c=ttk.Combobox(section.body,textvariable=self.cache_choice,values=['不保留 AI 缓存','1 GB','2 GB','4 GB'],state='readonly');c.pack(fill='x',pady=4);c.bind('<<ComboboxSelected>>',lambda e:self.save_workflow_preferences())
        c._aura_search_name='AI缓存空间限制'
        ttk.Label(section.body,textvariable=self.auto_note,style='Muted.TLabel',wraplength=290).pack(anchor='w',pady=5)
        ttk.Label(section.body,text='默认 AI 缓存限额 2 GB，可关闭或调节。超限淘汰缓存，恢复项目继续保留；原图变化后重新分析。',style='Muted.TLabel',wraplength=290).pack(anchor='w',pady=5)
        self.button(section.body,'查看自动保存',self.show_recovery)
    def save_workflow_preferences(self):
        from app_preferences import save_preferences
        quota={'不保留 AI 缓存':0,'1 GB':1,'2 GB':2,'4 GB':4}[self.cache_choice.get()];self.recovery.cache_limit=quota*1024**3
        try:save_preferences(dict(auto_save=self.auto_save.get(),reuse_cache=self.reuse_cache.get(),cache_limit_GB=quota))
        except OSError as e:self.auto_note.set('设置未保存：'+str(e));return
        self.auto_note.set('自动保存已开启' if self.auto_save.get() else '自动保存已关闭')
        self.recovery.prune()
    def mark_draft(self):
        if not hasattr(self,'recovery') or self._closing:return
        self._draft_dirty=True;self._draft_time=time.monotonic()
    def extensions_snapshot(self):return frozen(getattr(self,'workflow_extensions',{}))
    def load_extensions(self,data):
        self.workflow_extensions=frozen(data or {})
        from fuji_profiles import repair_legacy_filter
        self._filter_lut_repaired=repair_legacy_filter(self.workflow_extensions,self.document)
        self.sync_effect_ui()
        self.sync_creative_color_ui()
        self.sync_scene_ui()
        self.sync_composition_ui()
        if hasattr(self,'beauty_draft_notes'):self.sync_beauty_draft_ui()
    def project_arguments(self):
        return dict(document=copy.copy(self.document),parameters=self.parameters(),threshold=float(self.threshold.get()),
          selection=copy.deepcopy(self.selection),done=self.done_mask.copy() if self.done_mask is not None else None,
          small=self.small_mask.copy() if self.small_mask is not None else None,defaults=copy.deepcopy(self.defaults),
          tool_settings=dict(radius=self.brushradius(),feather=float(self.feather.get())),face_settings=copy.deepcopy(self.people_records()),
          patches=copy.deepcopy(self.patches),layers=frozen(self.region_layers),liquify_record=liquify.snapshot(self.liquify_state),
          liquify_settings=self.liquify_settings(),manual_records=copy.deepcopy(self.manual_records),manual_tools=self.manual_settings(),
          manual_enabled=bool(self.manual_enabled.get()),extensions=self.extensions_snapshot())
    def checkpoint(self):
        if getattr(self,'_render_pending',False):return False
        if not self.document or not self.session or self.busy or self.drag or self.shape_pending():return False
        if self._draft_thread and self._draft_thread.is_alive() or self._draft_result is not None:return False
        self.flush_parameters()
        if self.busy:return False
        captured=self.capture_photo();key=analysis_key(captured);state=compact(captured);args=self.project_arguments();path=str(self.path)
        write_cache=self._last_analysis.get(path)!=key
        self._draft_dirty=False;self.auto_note.set('正在自动保存…')
        def writer():
            try:entry=self.recovery.save(state,args,write_cache);self._draft_result=(path,key,entry,None)
            except Exception as e:self._draft_result=(path,key,None,str(e))
        self._draft_thread=threading.Thread(target=writer,daemon=False);self._draft_thread.start();return True
    def poll_workflow(self):
        if not hasattr(self,'recovery'):return
        if self._draft_result:
            path,key,entry,error=self._draft_result;self._draft_result=None
            self._draft_receipt=dict(thread=id(self._draft_thread),path=path,entry=entry,error=error)
            if error:self.auto_note.set('自动保存失败：'+error);self._draft_dirty=True;self._draft_time=time.monotonic()
            else:
                self._last_analysis[path]=key;self.auto_note.set('已自动保存 '+time.strftime('%H:%M:%S',time.localtime(entry['saved_at'])))
        if self.auto_save.get() and self._draft_dirty and time.monotonic()-self._draft_time>8:self.checkpoint()
        self.poll_batch()
    def try_recovery(self,path):
        if not self.reuse_cache.get() or self._skip_recovery:return False
        entry=self.recovery.find(path)
        if not entry:return False
        self.status.set('正在恢复自动保存与有效 AI 缓存…')
        def ready(result):
            state,project=result
            if state is not None:self.restore_photo(state);self.update_recent();self.status.set(self.status.get()+' / 自动恢复，已复用 AI 缓存')
            elif project is not None:self.open(path,project[0]['raw_settings'],project=project)
            else:
                self._skip_recovery=True
                try:self.open(path)
                finally:self._skip_recovery=False
        self.work(lambda:self.recovery.load(entry),ready);return True
    def show_recovery(self):
        window=tk.Toplevel(self.root);window.title('自动保存与恢复');window.geometry(f'{dp(self.root,660)}x{dp(self.root,390)}');window.transient(self.root)
        ttk.Label(window,text='选择恢复记录；缓存无效时从恢复项目重新处理。',padding=12).pack(anchor='w')
        tree=ttk.Treeview(window,columns=('date','version'),show='tree headings',height=10)
        tree.heading('#0',text='照片');tree.heading('date',text='保存时间');tree.heading('version',text='版本')
        tree.column('#0',width=dp(self.root,300));tree.column('date',width=dp(self.root,170));tree.column('version',width=dp(self.root,80));tree.pack(fill='both',expand=True,padx=12)
        entries=sorted(self.recovery.entries().values(),key=lambda e:e['saved_at'],reverse=True)
        for i,e in enumerate(entries):tree.insert('', 'end',iid=str(i),text=Path(e['source']).name,values=(time.strftime('%m-%d %H:%M',time.localtime(e['saved_at'])),e.get('version','')))
        def restore():
            if self.busy or not tree.selection():return
            entry=entries[int(tree.selection()[0])];window.destroy()
            if self.document:self.keep_current()
            def ready(result):
                state,project=result
                if state is not None:self.restore_photo(state);self.update_recent()
                else:self.load_recipe(self.recovery.child(entry['recipe']))
            self.work(lambda:self.recovery.load(entry),ready)
        row=ttk.Frame(window,padding=12);row.pack(fill='x')
        ttk.Button(row,text='恢复所选',command=restore).pack(side='left');ttk.Button(row,text='关闭',command=window.destroy).pack(side='right')
    def close_workspace(self,for_update=False):
        if not for_update and getattr(self,'_update_saving',False):
            self.status.set('正在为更新保存编辑，请等待保存完成。');return
        if getattr(self,'_update_running',False):
            self._update_cancel.set()
            self.status.set('正在取消更新传输并清理临时下载，随后退出…')
            self.root.after(150,lambda:self.close_workspace(for_update=for_update));return
        video=getattr(self,'video_preview_window',None)
        if video is not None and video.winfo_exists() and video.pending=='export':
            self.status.set('视频正在完整导出，请完成或取消后退出。');return
        live=getattr(self,'live_photo_window',None)
        if live is not None and live.winfo_exists() and live.busy:
            self.status.set('实况照片正在处理，请完成或取消后退出。');return
        if self.auto_save.get() and getattr(self,'_render_pending',False):
            self.auto_note.set('正在完成参数渲染，随后保存并退出…');self.root.after(150,lambda:self.close_workspace(for_update=for_update));return
        if self.busy or self.drag:self.status.set('请等待处理结束或取消处理后退出。');return
        if self.auto_save.get() and self.document:
            if self._draft_thread and self._draft_thread.is_alive():
                self.auto_note.set('正在完成自动保存，随后退出…');self.root.after(150,lambda:self.close_workspace(for_update=for_update));return
            self.poll_workflow()
            if self._draft_dirty:
                if '失败' in self.auto_note.get():
                    if for_update:self._stop_update_save('保存失败，已停止安装；请先手动保存项目。');return
                    if not messagebox.askyesno('自动保存失败','建议先手动保存项目。仍要退出吗？',parent=self.root):return
                elif self.checkpoint():self.root.after(150,lambda:self.close_workspace(for_update=for_update));return
        if video is not None and video.winfo_exists():video.close()
        if for_update and not self.start_update_installer():return
        self._closing=True
        if hasattr(self,'color_workbench'):self.color_workbench.display_renderer.close();self.color_workbench.drag_renderer.close()
        self.renderer.close();self.feature_renderer.close();self.filter_renderer.close();self.library.close();self.root.destroy()
