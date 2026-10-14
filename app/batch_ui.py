"""Sequential, cancellable batch synchronization and export with explicit scope."""
import copy,time,tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
from core import ROOT
from dpi_support import dp
from photo_document import export_document
from reshape_settings import KEYS as SHAPE_KEYS
import batch_workflow as batch,liquify

class BatchUI:
    def show_batch(self):
        if self.busy:return
        if not self.library.entries:messagebox.showinfo('批量处理','请先导入要处理的照片。',parent=self.root);return
        self.keep_current()
        if self.busy:return
        from person_mapping_ui import face_thumbnails
        source_snapshot=dict(path=self.path,parameters=copy.deepcopy(self.parameters()),extensions=self.extensions_snapshot(),person=self.active_face,
                             face_count=len(self.face_settings),thumbnail=face_thumbnails(self.capture_photo())[self.active_face] if self.face_settings else None)
        window=tk.Toplevel(self.root);window.title('批量同步与导出');window.transient(self.root)
        window._batch_source=source_snapshot
        window.geometry(f'{min(dp(self.root,760),self.root.winfo_screenwidth()-dp(self.root,32))}x{min(dp(self.root,680),self.root.winfo_screenheight()-dp(self.root,70))}');window.grab_set()
        shell=ttk.Frame(window);shell.pack(fill='both',expand=True)
        footer=ttk.Frame(shell,padding=(14,4,14,10));footer.pack(side='bottom',fill='x')
        viewport=ttk.Frame(shell);viewport.pack(fill='both',expand=True)
        canvas=tk.Canvas(viewport,highlightthickness=0,borderwidth=0)
        bar=ttk.Scrollbar(viewport,orient='vertical',command=canvas.yview);bar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        frame=ttk.Frame(canvas,padding=14);item=canvas.create_window((0,0),window=frame,anchor='nw')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        from scroll_ui import ScrollPane
        window._batch_scroll=ScrollPane(canvas,frame,bar)
        source_name=source_snapshot['path'].name if source_snapshot['path'] is not None else '未选择（可直接导出）'
        ttk.Label(frame,text='同步来源（打开窗口时的参数）：'+source_name,wraplength=dp(self.root,670)).pack(anchor='w')
        ttk.Label(frame,text='同步所选类别或直接导出；每张照片保留自身的识别范围。检查目标照片不会改变来源。',style='Muted.TLabel',wraplength=dp(self.root,670)).pack(anchor='w')
        mapping={};tree=ttk.Treeview(frame,columns=('person','state'),show='tree headings',height=8,selectmode='extended')
        tree.heading('person',text='对应人物');tree.column('person',width=dp(self.root,110))
        tree.heading('#0',text='照片（Ctrl / Shift 多选）');tree.heading('state',text='处理状态');tree.column('#0',width=dp(self.root,450));tree.pack(fill='both',expand=True,pady=8)
        paths=[e['path'] for e in self.library.entries.values()]
        for i,p in enumerate(paths):tree.insert('','end',iid=str(i),text=p.name,values=('待确认','待处理'))
        tree.selection_set(tree.get_children())
        groups=ttk.LabelFrame(frame,text='同步类别');groups.pack(fill='x',pady=5)
        checks={}
        for i,name in enumerate(batch.GROUPS):
            v=tk.BooleanVar(value=name in ('基础美颜','肤色与质感'));checks[name]=v
            ttk.Checkbutton(groups,text=name,variable=v).grid(row=i//3,column=i%3,sticky='w',padx=8,pady=4)
        if hasattr(self,'creative_vars'):
            v=tk.BooleanVar(value=False);checks['全局调色']=v;ttk.Checkbutton(groups,text='全局调色',variable=v).grid(row=len(batch.GROUPS)//3,column=len(batch.GROUPS)%3,sticky='w',padx=8,pady=4)
            for i,name in enumerate(batch.COLOR_GROUPS,start=len(batch.GROUPS)+1):
                v=tk.BooleanVar(value=False);checks[name]=v;ttk.Checkbutton(groups,text=name,variable=v).grid(row=i//3,column=i%3,sticky='w',padx=8,pady=4)
        all_people=tk.BooleanVar(value=False)
        ttk.Label(frame,text='镜头自动匹配与复制参数二选一；透视可独立同步。旧调色引擎不支持的参数会报告失败并保留原设置。',style='Muted.TLabel',wraplength=dp(self.root,670)).pack(anchor='w')
        ttk.Checkbutton(frame,text=f'应用到每张图全部人物（未勾选：来源人像 {source_snapshot["person"]+1}）',variable=all_people).pack(anchor='w',pady=4)
        ttk.Button(frame,text='确认所选照片的人物对应',command=lambda:self.choose_people_mapping(paths,[int(i) for i in tree.selection()],mapping,tree,window,source_info=source_snapshot)).pack(anchor='w',pady=4)
        ttk.Label(frame,text='单人同步先确认每张照片的对应人物。液化笔画、修复取样位置和手绘蒙版保持各图独立。',style='Muted.TLabel',wraplength=dp(self.root,670)).pack(anchor='w')
        output=ttk.LabelFrame(frame,text='导出');output.pack(fill='x',pady=8)
        format_var=tk.StringVar(value='TIFF · 16位');edge=tk.StringVar(value='0')
        ttk.Combobox(output,textvariable=format_var,values=['TIFF · 16位','PNG · 8位','JPEG · 8位'],state='readonly',width=16).grid(row=0,column=0,padx=8,pady=5)
        ttk.Label(output,text='长边像素，0为原尺寸').grid(row=0,column=1);ttk.Entry(output,textvariable=edge,width=8).grid(row=0,column=2,padx=8)
        folder=tk.StringVar(value=str(ROOT/'outputs'/time.strftime('批量-%Y%m%d-%H%M%S')))
        ttk.Entry(output,textvariable=folder,width=55).grid(row=1,column=0,columnspan=2,sticky='ew',padx=8,pady=5)
        def choose():
            p=filedialog.askdirectory(initialdir=str(ROOT),parent=window)
            if p:folder.set(p)
        ttk.Button(output,text='选择目录',command=choose).grid(row=1,column=2,padx=8)
        info=tk.StringVar(value='准备就绪');ttk.Label(footer,textvariable=info,wraplength=dp(self.root,680)).pack(anchor='w',pady=6)
        progress=ttk.Progressbar(footer,mode='determinate');progress.pack(fill='x')
        row=ttk.Frame(footer);row.pack(fill='x',pady=10);buttons=[]
        def start(sync,export,preflight_only=False):
            if getattr(self,'_batch_task',None) or self.busy:return
            try:
                maximum=int(edge.get());batch.resize_output(__import__('numpy').zeros((2,2,3)),maximum)
                dest=Path(folder.get()).resolve()
                if dest.exists() and not dest.is_dir():raise ValueError('请选择一个导出文件夹。')
                selected=[int(i) for i in tree.selection()]
                if not selected:raise ValueError('请选择照片。')
                chosen=[name for name,v in checks.items() if v.get()]
                if sync and source_snapshot['path'] is None:raise ValueError('请先选择来源照片，或使用“只导出”。')
                if {'自动匹配各图镜头','复制镜头校正参数'}<=set(chosen):raise ValueError('请选择镜头自动匹配或复制参数其中一种。')
                if sync and not chosen:raise ValueError('请选择需要同步的类别。')
                if sync and any(g in batch.GROUPS for g in chosen) and not all_people.get() and any(i not in mapping for i in selected):raise ValueError('请先确认所选照片的人物对应，或明确勾选应用到全部人物。')
                if sync and not source_snapshot['face_count'] and any(g in batch.GROUPS for g in chosen):raise ValueError('来源照片未识别到人物，无法作为人像参数来源。')
            except (ValueError,OSError) as e:info.set(str(e));return
            for b in buttons:b.configure(state='disabled')
            self._batch_task=dict(queue=selected.copy(),total=len(selected),done=0,errors=[],paths=paths,tree=tree,info=info,progress=progress,
                window=window,buttons=buttons,groups=chosen,source=copy.deepcopy(source_snapshot['parameters']),source_extensions=copy.deepcopy(source_snapshot['extensions']),source_path=str(source_snapshot['path']) if source_snapshot['path'] is not None else None,
                person=source_snapshot['person'],mapping=dict(mapping),all_people=all_people.get(),sync=sync,export=export,folder=dest,max_edge=maximum,
                extension={ 'TIFF · 16位':'.tif','PNG · 8位':'.png','JPEG · 8位':'.jpg'}[format_var.get()],phase='preflight',cancelled=False,
                preflight_only=preflight_only,run_id=str(time.time_ns()))
            from feature_actions_ui import descendants
            self._batch_task['input_states']=[(w,str(w.cget('state'))) for w in descendants(frame) if isinstance(w,(ttk.Entry,ttk.Combobox,ttk.Checkbutton,ttk.Button))]
            for widget,state in self._batch_task['input_states']:widget.configure(state='disabled')
            progress.configure(maximum=len(selected));progress['value']=0;self.begin_batch_preflight(self._batch_task)
        for title,sy,ex in [('只同步',True,False),('只导出',False,True),('同步并导出',True,True)]:
            b=ttk.Button(row,text=title,command=lambda sy=sy,ex=ex:start(sy,ex));b.pack(side='left',padx=3);buttons.append(b)
        preflight=ttk.Button(row,text='预检同步与导出',command=lambda:start(True,True,True));preflight.pack(side='left',padx=3);buttons.append(preflight)
        secondary=ttk.Frame(footer);secondary.pack(fill='x')
        for text,action in [('继续未完成',lambda:self.resume_batch(window)),('重试失败项',lambda:self.retry_failed_batch(window)),('检查所选照片',lambda:self.review_batch_photo(window,paths,tree,info))]:
            button=ttk.Button(secondary,text=text,command=action,state='normal' if text=='检查所选照片' else 'disabled');button.pack(side='left',padx=3);buttons.append(button)
            if text=='继续未完成':window._batch_resume=button
            elif text=='重试失败项':window._batch_retry=button
        def cancel():
            task=getattr(self,'_batch_task',None)
            if task:task['cancelled']=True;self.cancel.set();info.set('正在停止，保留已完成文件…')
            else:window.destroy()
        ttk.Button(secondary,text='停止 / 关闭',command=cancel).pack(side='right');window.protocol('WM_DELETE_WINDOW',cancel)
    def begin_batch_preflight(self,t):
        from batch_preflight import audit
        t['phase']='preflight';t['info'].set('正在预检文件、人物对应、调色兼容性与输出设置…')
        def ready(result):
            if getattr(self,'_batch_task',None) is not t:return
            t['preflight']=result
            for row in result['rows']:
                t['tree'].set(str(row['index']),'state','预检通过' if row['status']=='ready' else '预检失败：'+'；'.join(row['errors']))
                if not t['sync'] or not any(g in batch.GROUPS or g=='打光与改色' for g in t['groups']):t['tree'].set(str(row['index']),'person','无需对应')
                elif t['all_people']:t['tree'].set(str(row['index']),'person','全部人物')
            if not result['passed'] or t.get('preflight_only'):
                t['cancelled']=True;t['phase']='next';return
            try:
                if t['export']:t['folder'].mkdir(parents=True,exist_ok=True)
            except OSError as error:
                t['preflight_error']=str(error);t['cancelled']=True
            t['phase']='next'
        self.work(lambda:audit(self.library,t,self.cancel),ready)
    def resume_batch(self,window):
        if self.busy or getattr(self,'_batch_task',None):return
        previous=getattr(self,'_last_batch_task',None)
        if not previous or previous['window'] is not window or not previous.get('queue') or previous.get('preflight_only'):return
        self.restart_batch(previous,list(previous['queue']))
    def restart_batch(self,previous,queue):
        task=dict(previous,queue=queue,total=len(queue),done=0,errors=[],failed=[],results=[],phase='preflight',cancelled=False,
                  preflight_only=False,preflight=None,preflight_error=None,recovery_error=None,recovery_recipe=None,
                  run_id=str(time.time_ns()),parent_run_id=previous.get('run_id'))
        for button in task['buttons']:button.configure(state='disabled')
        for widget,state in task.get('input_states',[]):widget.configure(state='disabled')
        task['progress'].configure(maximum=task['total']);task['progress']['value']=0
        self._batch_task=task;self.begin_batch_preflight(task)
    def review_batch_photo(self,window,paths,tree,info):
        if self.busy or getattr(self,'_batch_task',None):return
        selected=tree.selection()
        if len(selected)!=1:info.set('请选择一张照片进入成片检查。');return
        path=paths[int(selected[0])].resolve();self.open(path);deadline=time.monotonic()+240
        def ready():
            if not window.winfo_exists():return
            if self.busy or self._render_pending:
                if time.monotonic()>deadline:info.set('照片准备超时，请关闭批量窗口后重新打开照片。');return
                self.root.after(80,ready);return
            if self.path!=path or getattr(self,'_render_failed',False):info.set('照片未能准备，请查看处理提示。');return
            from production_review_ui import show
            show(self)
        self.root.after_idle(ready)
    def _batch_failure(self,text):
        t=self._batch_task;t['errors'].append(t['paths'][t['current']].name+'：'+text)
        t.setdefault('failed',[]).append(t['current'])
        t.setdefault('results',[]).append(dict(source=str(t['paths'][t['current']]),status='failed',error=text))
        t['tree'].set(str(t['current']),'state','失败');t['done']+=1;t['progress']['value']=t['done'];t['phase']='next'
    def retry_failed_batch(self,window):
        if self.busy or getattr(self,'_batch_task',None):return
        previous=getattr(self,'_last_batch_task',None)
        if not previous or previous['window'] is not window or not previous.get('failed'):return
        # Retain the original source recipe and mapping, not the last target's
        # sliders. Successful photos and their output files are never retried.
        self.restart_batch(previous,list(previous['failed']))
    def finish_batch_report(self,t):
        if not t['export'] or t.get('preflight_only') or not t['folder'].is_dir():return None
        import json
        path=t['folder']/('AURA-交付检查-'+str(time.time_ns())+'.json')
        receipt=dict(schema=1,cancelled=t['cancelled'],processed=t['done'],total=t['total'],failed=len(t['errors']),
                     groups=t['groups'],source_path=t.get('source_path'),results=t.get('results',[]),run_id=t.get('run_id'),parent_run_id=t.get('parent_run_id'),
                     unfinished=[str(t['paths'][i]) for i in t.get('queue',[])],preflight=t.get('preflight'),
                     scope='数值与来源检查记录；不代表肤色、蒙版边缘或审美已通过人工检查。')
        with path.open('x',encoding='utf8') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2)
        return path
    def save_batch_photo(self,t):
        enabled=getattr(self,'auto_save',None)
        if t['phase']!='saving' and (enabled is None or not enabled.get()):return False
        if t['phase']=='finished':
            t['info'].set('正在保存当前照片的恢复记录，再继续下一张…')
            try:
                if not self.checkpoint():return True
            except Exception as error:
                t['recovery_error']=str(error);t['cancelled']=True;t['phase']='finished_saved';return False
            t['saving_thread']=self._draft_thread;t['phase']='saving';return True
        if t['phase']=='saving':
            receipt=getattr(self,'_draft_receipt',None)
            if not receipt or receipt['thread']!=id(t['saving_thread']):return True
            if receipt['error']:t['recovery_error']=receipt['error'];t['cancelled']=True
            else:t['recovery_recipe']=receipt['entry']['recipe']
            t['phase']='finished_saved'
        return False
    def poll_batch(self):
        if getattr(self,'_render_pending',False):return
        t=getattr(self,'_batch_task',None)
        if not t or self.busy:return
        if t['phase']=='preflight':
            # A worker error/cancellation never entered the mutation stages.
            t['preflight_error']=self.status.get();t['cancelled']=True;t['phase']='next'
        if t['phase'] in ('finished','saving') and self.save_batch_photo(t):return
        if t['cancelled'] or (t['phase']=='next' and not t['queue']):
            if t['phase'] in ('finished','finished_saved'):self.complete_batch_photo(t)
            elif t['phase'] not in ('next','preflight') and 'current' in t and t['current'] not in t['queue']:
                t['queue'].insert(0,t['current']);t['tree'].set(str(t['current']),'state','未完成，可继续')
            message=f'已处理 {t["done"]}/{t["total"]}；成功 {t["done"]-len(t["errors"])}；失败 {len(t["errors"])}'+(('\n'+'\n'.join(t['errors'][:4])) if t['errors'] else '')
            if t.get('preflight_only') or t.get('preflight_error') or t.get('preflight') and not t['preflight']['passed']:
                details=[str(e) for row in (t.get('preflight') or {}).get('rows',[]) for e in row['errors']]
                message=('预检通过，尚未同步或导出。' if (t.get('preflight') or {}).get('passed') else '预检未通过，尚未同步或导出。')+'\n'+'；'.join(details[:3])+(t.get('preflight_error') or '')
            elif t['queue']:message+=f'\n还有 {len(t["queue"])} 张未完成，可继续；已成功导出文件保留。'
            if t.get('recovery_error'):message+='\n恢复记录保存失败，请先手动保存当前照片：'+t['recovery_error']
            try:
                receipt=self.finish_batch_report(t)
                if receipt:message+='\n已保存交付检查记录：'+receipt.name
            except OSError as error:message+='\n检查记录保存失败：'+str(error)
            t['info'].set(message);self._last_batch_task=t
            for b in t['buttons']:b.configure(state='normal')
            for widget,state in t.get('input_states',[]):widget.configure(state=state)
            resume=getattr(t['window'],'_batch_resume',None);retry=getattr(t['window'],'_batch_retry',None)
            if resume is not None:resume.configure(state='normal' if t['queue'] and not t.get('preflight_only') else 'disabled')
            if retry is not None:retry.configure(state='normal' if t.get('failed') else 'disabled')
            self._batch_task=None;self.cancel.clear();self.update_recent();return
        if t['phase'] in ('processing','exporting'):
            self._batch_failure(self.status.get());return
        if t['phase']=='raw_source':return
        if t['phase']=='next':
            t['current']=t['queue'].pop(0);t['phase']='loaded'
            t['output_path']=None;t['checks']=None;t['export_dimensions']=None;t['output_sha256']=None;t['recovery_recipe']=None;t['recovery_error']=None
            t['info'].set(f'{t["done"]+1}/{t["total"]} · {t["paths"][t["current"]].name}')
            t['tree'].set(str(t['current']),'state','正在处理');self.open(t['paths'][t['current']]);return
        if t['phase']=='loaded':
            target=t.get('mapping',{}).get(t['current'],t['person']);t['target_person']=target
            if self.path!=t['paths'][t['current']].resolve():self._batch_failure('导入失败');return
            if self.shape_pending():return
            if t['sync']:
                try:requirement=batch.raw_requirement(self.workflow_extensions,t['source_extensions'],t['groups'],self.document.metadata)
                except ValueError as e:self._batch_failure(str(e));return
                if requirement is not None:
                    action=dict(kind='batch',task=id(t),current=t['current']);t['phase']='raw_source'
                    if not self.check_filter_raw_base(requirement,action):
                        if self._pending_fuji_filter is None:self._batch_failure(self.status.get())
                        return
            t['phase']='sync'
        if t['phase']=='sync':
            target=t.get('target_person',t['person'])
            if t['sync']:
                try:values=batch.merge_people(self.face_settings,t['source'],[g for g in t['groups'] if g in batch.GROUPS],target,t['all_people']) if any(g in batch.GROUPS for g in t['groups']) else copy.deepcopy(self.face_settings)
                except ValueError as e:self._batch_failure(str(e));return
                if liquify.active(self.liquify_state) or self.liquify_state is not None and self.liquify_state['freeze'].any():
                    if any(any(a[k]!=b[k] for k in SHAPE_KEYS) for a,b in zip(values,self.face_settings)):
                        self._batch_failure('已有画笔液化，请先恢复形变与保护，再同步脸型参数。');return
                t['phase']='processing'
                def ready(result):
                    self.generated,self.done_mask,self.form_cache,self.reshape_cache=result;self.face_settings=values;self.load_person_controls()
                    if '全局调色' in t['groups']:self.sync_global_creative(t['source_extensions'])
                    selected_color=[g for g in t['groups'] if g in batch.COLOR_GROUPS]
                    if selected_color:batch.sync_color_groups(self.workflow_extensions,t['source_extensions'],selected_color,self.document.metadata);self.sync_creative_color_ui()
                    if '打光与改色' in t['groups']:
                        import creative_portrait as ops
                        source=t['source_extensions'].get('people',{}).get(str(t['person']),{})
                        fields=[k for k in ops.DEFAULTS if k!='clothes_clean']+list(ops.COLORS)+['relight']
                        targets=range(len(values)) if t['all_people'] else [t['target_person']]
                        for fi in targets:
                            item=self.workflow_extensions.setdefault('people',{}).setdefault(str(fi),{})
                            for k in fields:
                                if k=='relight':
                                    if k in source:item[k]=copy.deepcopy(source[k])
                                    else:item.pop(k,None)
                                else:item[k]=copy.deepcopy(source.get(k,ops.DEFAULTS.get(k,ops.COLORS.get(k))))
                            item['box']=list(self.session.faces[fi].box)
                        self.sync_scene_ui()
                    self.refresh();self.record('批量分项同步');self.update_recent();t['phase']='prepared'
                self.work(lambda:batch.prepare(self,values),ready);return
            t['phase']='prepared'
        if t['phase']=='prepared':
            if getattr(self,'_render_failed',False):self._batch_failure('当前照片渲染失败，未导出旧预览。');return
            if t['export']:
                if self.repair_pending() or self.shape_pending():self._batch_failure('仍有待处理选区或形变，请先完成后再导出。');return
                from production_checks import for_app
                t['checks']=for_app(self)
                if not t['checks']['exportable']:
                    self._batch_failure('；'.join(r['message'] for r in t['checks']['checks'] if r['status']=='error'));return
                path=batch.destination(t['folder'],self.path.stem,t['extension'],t['done']+1)
                t['output_path']=str(path)
                image=batch.resize_output(self.prepare_export_image(self.output_float.copy()),t['max_edge']);t['phase']='exporting'
                t['export_dimensions']=[int(image.shape[1]),int(image.shape[0])]
                def ready(digest):t['output_sha256']=digest;t['phase']='finished';t['tree'].set(str(t['current']),'state','已导出')
                options=copy.deepcopy(self.workflow_extensions.get('output',{}))
                if options.get('hdr') and path.suffix.lower() not in ('.tif','.tiff'):
                    self._batch_failure('此照片启用了 HDR，请选择 TIFF 导出。');return
                def export_job():
                    export_document(path,image,16,options=options)
                    from photo_document import sha256_file
                    return sha256_file(path)
                self.work(export_job,ready,cancellable=False);return
            t['phase']='finished'
        if t['phase'] in ('finished','finished_saved'):
            if t['phase']=='finished' and self.save_batch_photo(t):return
            self.complete_batch_photo(t)
    def complete_batch_photo(self,t):
        t.setdefault('results',[]).append(dict(source=str(t['paths'][t['current']]),status='completed',output=t.get('output_path'),output_sha256=t.get('output_sha256'),
            recovery_recipe=t.get('recovery_recipe'),recovery_error=t.get('recovery_error'),
            raw_settings=copy.deepcopy(self.document.raw_settings),profile=self.document.metadata.get('profile_name'),
            baseline=self.document.metadata.get('raw_baseline'),source_precision=self.document.metadata.get('bit_depth',self.document.precision),
            export_dimensions=t.get('export_dimensions'),output_format=t['extension'],
            output_settings=copy.deepcopy(self.workflow_extensions.get('output',{})),checks=t.get('checks')))
        t['done']+=1;t['progress']['value']=t['done'];t['tree'].set(str(t['current']),'state','恢复记录未保存' if t.get('recovery_error') else '已完成');t['phase']='next'
