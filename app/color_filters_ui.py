"""Photo-based preset browser, backed by AURA's existing floating-point engine."""
import copy, time, tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog
from types import SimpleNamespace
import cv2, numpy as np
from PIL import Image, ImageTk, ImageOps
from dark_ui import Section, COLORS
from dpi_support import dp
from render_queue import LatestRenderer
import color_presets as presets
import creative_color as color
PAGE_SIZE=4


def card_text(item,selected,favorite):
    name=item['name']
    from fuji_profiles import SHORT_NAMES
    name=SHORT_NAMES.get(item['id'],name)
    if len(name)>8:name=name[:8]+'…'
    status=('已选 · ' if selected else '')+('收藏' if favorite else item['group'])
    return name+'\n'+status


class ColorFiltersUI:
    def init_color_filters(self):
        from app_preferences import CONFIG
        self.filter_library=presets.PresetLibrary(CONFIG.parent/'color-presets.json')
        self.filter_library.external,self._fuji_library_error=__import__('fuji_profiles').presets()
        self.filter_group=tk.StringVar(value='全部');self.filter_query=tk.StringVar()
        self.filter_amount=tk.DoubleVar(value=100);self.filter_label=tk.StringVar(value='未套用滤镜')
        self.filter_description=tk.StringVar(value='基于当前照片预览。点击滤镜套用，再微调曲线、HSL 和影调。')
        self.filter_page_label=tk.StringVar();self.filter_preview_note=tk.StringVar(value='打开照片后生成滤镜预览')
        self.filter_favorite_label=tk.StringVar(value='收藏当前滤镜')
        self._filter_page=0;self._filter_cards=[];self._filter_photos=[];self._filter_visible=[]
        self._filter_thumbnail_key=None;self._filter_tick=0;self._filter_search_timer=None
        self.filter_renderer=LatestRenderer()

    def build_color_filters(self,body):
        section=Section(body,'滤镜 · 成品风格',opened=True);self.filter_section=section
        section._feature_tools=True  # This section has an explicit restore-to-before action.
        parent=section.body
        self.build_fuji_controls(parent)
        ttk.Label(parent,textvariable=self.filter_label,wraplength=270).pack(fill='x',pady=(0,4))
        ttk.Label(parent,textvariable=self.filter_description,style='Muted.TLabel',wraplength=270).pack(fill='x',pady=(0,5))
        self.filter_amount_control=self.slider(parent,'滤镜强度 %',self.filter_amount,0,200,self.change_filter_amount)
        row=ttk.Frame(parent);row.pack(fill='x',pady=(4,6))
        restore=ttk.Button(row,text='恢复套用前',width=0,command=self.remove_color_filter);restore.pack(side='left',fill='x',expand=True,padx=(0,3));self.controls.append(restore)
        self.filter_favorite_button=ttk.Button(row,textvariable=self.filter_favorite_label,width=0,command=self.toggle_filter_favorite)
        self.filter_favorite_button.pack(side='right',fill='x',expand=True,padx=(3,0));self.controls.append(self.filter_favorite_button)
        row=ttk.Frame(parent);row.pack(fill='x')
        ttk.Label(row,text='分类').pack(side='left')
        self.filter_group_control=ttk.Combobox(row,textvariable=self.filter_group,values=presets.GROUPS,state='readonly',width=10)
        self.filter_group_control.pack(side='right',fill='x',expand=True,padx=(8,0))
        self.filter_group_control.bind('<<ComboboxSelected>>',lambda e:self.rebuild_filter_cards())
        row=ttk.Frame(parent);row.pack(fill='x',pady=(6,6))
        ttk.Label(row,text='搜索').pack(side='left')
        entry=ttk.Entry(row,textvariable=self.filter_query);entry.pack(side='right',fill='x',expand=True,padx=(8,0))
        self.filter_query.trace_add('write',lambda *_:self.schedule_filter_search())
        self.filter_grid=ttk.Frame(parent);self.filter_grid.pack(fill='x')
        for col in range(2):self.filter_grid.columnconfigure(col,weight=1,uniform='filters')
        row=ttk.Frame(parent);row.pack(fill='x',pady=(6,0))
        self.filter_previous=ttk.Button(row,text='上一页',width=0,command=lambda:self.change_filter_page(-1));self.filter_previous.pack(side='left')
        ttk.Label(row,textvariable=self.filter_page_label,style='Muted.TLabel').pack(side='left',expand=True)
        self.filter_next=ttk.Button(row,text='下一页',width=0,command=lambda:self.change_filter_page(1));self.filter_next.pack(side='right')
        ttk.Label(parent,textvariable=self.filter_preview_note,style='Muted.TLabel',wraplength=270).pack(fill='x',pady=5)
        self.button(parent,'保存当前风格到「我的」',self.save_personal_filter)
        self.button(parent,'XMP 导入到滤镜库（多选）',self.import_lightroom_filters)
        self.button(parent,'查看当前滤镜来源',self.show_filter_source)
        self.button(parent,'AI 分区调色（蒙版工作台）',self.open_filter_masks)
        self.button(parent,'删除当前个人滤镜',self.delete_personal_filter)
        note=f'{len(presets.BUILTINS)} 款普通风格，含日系参考与开源精选；本版不含富士风格。0%恢复套用前调色，切换不累积。'
        if presets.COLLECTION_ERROR:note+=' 开源精选未加载，请检查资源。'
        ttk.Label(parent,text=note,style='Muted.TLabel',wraplength=270).pack(fill='x',pady=5)
        self.rebuild_filter_cards();return section

    def schedule_filter_search(self):
        if self._filter_search_timer is not None:self.root.after_cancel(self._filter_search_timer)
        def run():self._filter_search_timer=None;self.rebuild_filter_cards()
        self._filter_search_timer=self.root.after(180,run)

    def rebuild_filter_cards(self,reset=True):
        if reset:self._filter_page=0
        items=self.filter_library.items(self.filter_group.get(),self.filter_query.get())
        pages=max(1,(len(items)+PAGE_SIZE-1)//PAGE_SIZE);self._filter_page=min(self._filter_page,pages-1)
        for button in self._filter_cards:
            if button in self.controls:self.controls.remove(button)
        for child in self.filter_grid.winfo_children():child.destroy()
        self._filter_cards=[];self._filter_photos=[]
        self._filter_visible=items[self._filter_page*PAGE_SIZE:self._filter_page*PAGE_SIZE+PAGE_SIZE]
        for i,item in enumerate(self._filter_visible):
            text=card_text(item,False,item['id'] in self.filter_library.favorites)
            button=ttk.Button(self.filter_grid,text=text,width=0,compound='top',command=lambda p=item:self.choose_color_filter(p))
            from tooltip_ui import tooltip
            tooltip(button,item['name']+'\n'+item['description'])
            button._aura_search_name='滤镜 '+item['name']+' '+item['group']
            button.grid(row=i//2,column=i%2,sticky='nsew',padx=(0,3) if i%2==0 else (3,0),pady=3)
            self._filter_cards.append(button);self.controls.append(button)
        if not items:ttk.Label(self.filter_grid,text='没有匹配滤镜，请换分类或搜索词。',style='Muted.TLabel',wraplength=260).grid(sticky='ew',columnspan=2)
        self.filter_page_label.set(f'{self._filter_page+1}/{pages} · {len(items)} 款')
        self.filter_previous.configure(state='normal' if self._filter_page else 'disabled')
        self.filter_next.configure(state='normal' if self._filter_page+1<pages else 'disabled')
        self._filter_thumbnail_key=None;self.filter_renderer.invalidate();self.sync_filter_ui()

    def change_filter_page(self,delta):
        self._filter_page=max(0,self._filter_page+delta);self.rebuild_filter_cards(False)

    def filter_edit_allowed(self):
        if not self.document or not self.session or self.busy:
            self.status.set('请先打开照片并等待处理完成。');return False
        return True

    def open_filter_masks(self):
        if not self.filter_edit_allowed():return
        if self.color_workbench.open():self.color_workbench.show_page('蒙版')

    def choose_color_filter(self,item,source_ready=False):
        if not self.filter_edit_allowed():return
        data,state=presets.apply_preset(self.workflow_extensions.get('color',{}),item,self.filter_amount.get(),self.workflow_extensions.get('color_filter'))
        from fuji_profiles import required_base
        required=required_base({'color':data,'color_filter':state})
        if not source_ready and not self.check_filter_raw_base({'raw_base':required},dict(kind='filter',item=item)):return
        self.commit_edit('套用滤镜前')
        self.workflow_extensions['color']=data;self.workflow_extensions['color_filter']=state
        from ai_region_filters import sync_linked
        sync_linked(self.region_layers,state['preset']['id'],state['amount'])
        self.sync_creative_color_ui();self.refresh_color();self.record('套用滤镜 '+item['name'])

    def change_filter_amount(self,source_ready=False,amount=None):
        if self.loading_creative or not self.filter_edit_allowed():return
        state=self.workflow_extensions.get('color_filter');current=self.workflow_extensions.get('color',{})
        if not state or presets.signature(current)!=state['signature']:
            self.sync_filter_ui();self.status.set('当前调色已微调，请重新选择滤镜后调整强度。');return
        amount=self.filter_amount.get() if amount is None else amount
        base=presets.restore_base(current,state);out=presets.blend(base,state['preset']['recipe'],amount)
        from fuji_profiles import required_base
        required=(state['preset'].get('raw_base') or required_base({'color':out})) if amount>0 else required_base({'color':out})
        if not source_ready and not self.check_filter_raw_base({'raw_base':required},dict(kind='amount',amount=amount)):return
        self.commit_edit('调整滤镜强度前')
        self.workflow_extensions['color']=out;state['amount']=amount;state['signature']=presets.signature(out)
        from ai_region_filters import sync_linked
        sync_linked(self.region_layers,state['preset']['id'],amount)
        self.sync_creative_color_ui();self.refresh_color();self.record('滤镜强度 '+f'{state["amount"]:.0f}%')

    def remove_color_filter(self,source_ready=False,restoration=None):
        if not self.filter_edit_allowed():return
        state=self.workflow_extensions.get('color_filter')
        if not state and restoration is None:self.status.set('当前没有可恢复的滤镜记录。');return
        if restoration is None:restoration=presets.restore_base(self.workflow_extensions.get('color',{}),state)
        if not source_ready:
            from fuji_profiles import required_base
            required=required_base({'color':restoration})
            if not self.check_filter_raw_base({'raw_base':required},dict(kind='remove',color=restoration)):return
        self.commit_edit('移除滤镜前')
        self.workflow_extensions['color']=restoration
        self.workflow_extensions.pop('color_filter',None)
        from ai_region_filters import sync_linked
        sync_linked(self.region_layers,None,0)
        self.sync_creative_color_ui();self.refresh_color();self.record('恢复套用前调色')

    def sync_filter_ui(self):
        if not hasattr(self,'filter_amount_control'):return
        state=self.workflow_extensions.get('color_filter');valid=bool(state and presets.signature(self.workflow_extensions.get('color',{}))==state['signature'])
        ready=self.document is not None and not self.busy
        self.filter_amount_control.configure(state='normal' if ready and valid else 'disabled')
        if state:
            item=state['preset'];self.filter_amount.set(state['amount'])
            self.filter_label.set(item['name']+f' · {state["amount"]:.0f}%'+(' · 已微调' if not valid else ''))
            self.filter_description.set(item['description'])
            from effect_controls import settings
            stages=[settings(self.workflow_extensions,k) for k in ('color','creative')]
            if any(not enabled or opacity==0 for enabled,opacity in stages):self.filter_description.set(item['description']+' 全局调色效果当前已关闭，请在效果管理中启用。')
            elif any(opacity<1 for enabled,opacity in stages):self.filter_description.set(item['description']+' 效果管理中的调色强度正在减弱滤镜。')
            self.filter_favorite_label.set('取消收藏当前滤镜' if item['id'] in self.filter_library.favorites else '收藏当前滤镜')
        else:
            self.filter_label.set('未套用滤镜');self.filter_amount.set(100)
            self.filter_description.set('基于当前照片预览。点击滤镜套用，再微调曲线、HSL 和影调。')
            self.filter_favorite_label.set('收藏当前滤镜')
        for button,item in zip(self._filter_cards,self._filter_visible):
            selected=bool(state and item['id']==state['preset']['id'])
            from fuji_profiles import filter_base_ready
            title=card_text(item,selected,item['id'] in self.filter_library.favorites)
            if item.get('raw_base') and not filter_base_ready(self.document):title=title.split('\n')[0]+'\n点击自动准备基底'
            button.configure(text=title,style='Accent.TButton' if selected else 'TButton',state='normal' if ready else 'disabled')

    def toggle_filter_favorite(self):
        state=self.workflow_extensions.get('color_filter')
        if not state:self.status.set('请先选择一个滤镜。');return
        key=state['preset']['id'];old=list(self.filter_library.favorites)
        if not any(x['id']==key for x in self.filter_library.items()):self.status.set('此个人滤镜已从库中删除，请先重新保存风格。');return
        if key in old:self.filter_library.favorites.remove(key)
        else:self.filter_library.favorites.append(key)
        try:self.filter_library.save()
        except (OSError,ValueError) as e:self.filter_library.favorites=old;messagebox.showerror('收藏未保存',str(e),parent=self.color_dialog_parent());return
        self.rebuild_filter_cards(False)

    def save_personal_filter(self):
        if not self.filter_edit_allowed():return
        name=simpledialog.askstring('保存个人滤镜','滤镜名称（最多 30 字）：',parent=self.color_dialog_parent())
        if name is None:return
        name=name.strip()
        if not 1<=len(name)<=30 or len(self.filter_library.custom)>=100:
            messagebox.showerror('滤镜未保存','名称须为 1–30 字，个人滤镜最多 100 款。',parent=self.color_dialog_parent());return
        state=self.workflow_extensions.get('color_filter',{})
        from fuji_profiles import required_base
        item=presets.capture_style(self.workflow_extensions.get('color',{}),name,required_base(self.workflow_extensions));old=list(self.filter_library.custom)
        self.filter_library.custom.append(item)
        try:self.filter_library.save()
        except (OSError,ValueError) as e:self.filter_library.custom=old;messagebox.showerror('滤镜未保存',str(e),parent=self.color_dialog_parent());return
        self.filter_group.set('我的');self.filter_query.set('');self.rebuild_filter_cards();self.status.set('个人滤镜已保存：'+name)

    def import_lightroom_filters(self):
        if self.busy:return
        paths=filedialog.askopenfilenames(title='导入Lightroom滤镜（可多选）',filetypes=[('Lightroom / Camera Raw XMP','*.xmp')],parent=self.color_dialog_parent())
        if not paths:return
        try:
            imported,report=self.import_lightroom_files(paths)
        except (OSError,ValueError) as error:
            messagebox.showerror('滤镜导入未保存',str(error),parent=self.color_dialog_parent());return
        if imported:
            self.filter_group.set('我的');self.filter_query.set('');self.rebuild_filter_cards()
        messagebox.showinfo('Lightroom滤镜导入',report,parent=self.color_dialog_parent())

    def import_lightroom_files(self,paths):
        """Import to the library, never modify the current photograph."""
        from lightroom_presets import converted
        old=list(self.filter_library.custom);ids={item['id'] for item in self.filter_library.items()}
        added=[];errors=[];partial=[];duplicates=0
        for path in paths:
            try:
                item,details=converted(path)
                if item['id'] in ids:duplicates+=1;continue
                if len(old)+len(added)>=100:raise ValueError('个人滤镜最多100款。')
                added.append(item);ids.add(item['id'])
                if details.get('profile_dependencies') or details['unsupported']:partial.append(item['name'])
            except (OSError,ValueError,TypeError,KeyError) as error:
                from pathlib import Path
                errors.append(Path(path).name+'：'+str(error))
        if added:
            self.filter_library.custom=old+added
            try:self.filter_library.save()
            except (OSError,ValueError):self.filter_library.custom=old;raise
        text=f'已导入 {len(added)} 款；重复 {duplicates} 款；跳过 {len(errors)} 款。'
        text+='\n导入后在「我的」点击套用；保留照片曝光、拍摄白平衡、光学校正和美颜。'
        if partial:text+='\n部分预设包含未迁移内容，无法保证Lr原效果：'+'、'.join(partial[:8])
        if errors:text+='\n'+'\n'.join(errors[:6])
        self.status.set(f'Lightroom滤镜库：新增 {len(added)} 款，当前照片未改变。')
        return len(added),text

    def show_filter_source(self):
        item=self.workflow_extensions.get('color_filter',{}).get('preset')
        if not item:self.status.set('请先选择一个滤镜。');return
        source=item.get('source')
        if source:
            text=item['name']+'\n'+source['label']+'\n许可：'+source['license']+'\n'+source['url']
            if source['label'].startswith('小红书参考'):
                text+='\n按帖子构思制作的AURA原创配方，并非作者预设。曝光、拍摄白平衡、天空蒙版及人像美颜需要按照片另行调整。'
            else:text+='\n这是AURA的参数适配版本，Adobe配置、AI蒙版和原生渲染没有迁移。'
        elif item.get('raw_base'):text=item['name']+'\n富士sRGB LUT风格。RAW使用匹配的线性DCP；普通照片直接套用，效果受原图调色影响。'
        else:text=item['name']+'\nAURA原创配方，可继续调整曲线、HSL与分级。'
        messagebox.showinfo('滤镜来源',text,parent=self.color_dialog_parent())

    def delete_personal_filter(self):
        state=self.workflow_extensions.get('color_filter')
        key=state['preset']['id'] if state else ''
        if not any(x['id']==key for x in self.filter_library.custom):self.status.set('请先套用要删除的个人滤镜。');return
        old=list(self.filter_library.custom);favorites=list(self.filter_library.favorites)
        self.filter_library.custom=[x for x in old if x['id']!=key];self.filter_library.favorites=[x for x in favorites if x!=key]
        try:self.filter_library.save()
        except (OSError,ValueError) as e:self.filter_library.custom=old;self.filter_library.favorites=favorites;messagebox.showerror('滤镜未删除',str(e),parent=self.color_dialog_parent());return
        self.rebuild_filter_cards(False);self.status.set('已从个人滤镜库删除；当前照片的调色仍保留。')

    def poll_color_filters(self):
        self.poll_pending_fuji()
        if not hasattr(self,'filter_section') or not self.filter_section.body.winfo_ismapped():return
        result=self.filter_renderer.take()
        if result:
            _,payload,error=result
            if error:self.filter_preview_note.set('预览未完成，可点击滤镜直接套用。')
            else:
                key,images=payload
                if key==self._filter_thumbnail_key:
                    self._filter_photos=[]
                    size=(dp(self.root,112),dp(self.root,78))
                    for button,array in zip(self._filter_cards,images):
                        photo=ImageTk.PhotoImage(ImageOps.fit(Image.fromarray(array),size,method=Image.Resampling.LANCZOS),master=self.root)
                        self._filter_photos.append(photo);button.configure(image=photo)
                    from fuji_profiles import filter_base_ready
                    if any(x.get('raw_base') and not filter_base_ready(self.document) for x in self._filter_visible):self.filter_preview_note.set('点击富士 RAW 风格会自动准备基底并套用；首次需要等待。')
                    else:self.filter_preview_note.set('当前照片 · 100% 风格预览 · 点击套用')
        now=time.monotonic()
        if now-self._filter_tick<.5:return
        self._filter_tick=now
        if self.filter_library.error:self.filter_preview_note.set('个人滤镜库读取失败，原文件已保留。')
        source=self.color_input
        if self.busy or source is None or not self._filter_visible:return
        current=self.workflow_extensions.get('color',{});state=self.workflow_extensions.get('color_filter')
        base=presets.restore_base(current,state) if state and presets.signature(current)==state['signature'] else presets.plain(current)
        from effect_controls import settings
        stages=[settings(self.workflow_extensions,k) for k in ('color','creative')];amount=np.prod([opacity if enabled else 0 for enabled,opacity in stages]).item()
        proof=copy.deepcopy(self.workflow_extensions.get('output',{}))
        key=(id(source),id(self.document),presets.signature(base),tuple(x['id'] for x in self._filter_visible),dp(self.root,112),str(proof),amount)
        if key==self._filter_thumbnail_key:return
        self._filter_thumbnail_key=key;self.filter_preview_note.set('正在生成当前照片的滤镜预览…')
        from creative_regions import regions
        skin=regions(self.session,self.region_layers)['skin'].astype(np.float32)
        scene=getattr(self.document,'scene',None)
        if scene is not None and scene.shape!=source.shape:scene=None
        from fuji_profiles import filter_base_ready
        original=self.document.rgb;unsupported=[bool(x.get('raw_base') and not filter_base_ready(self.document)) for x in self._filter_visible]
        recipes=[presets.blend(base,copy.deepcopy(x['recipe']),100) if not blocked else None for x,blocked in zip(self._filter_visible,unsupported)]
        def render():
            from color_workbench_render import filter_previews,thumbnail_inputs
            reduced=thumbnail_inputs(source,skin,original,scene)
            from ai_runtime import saved_mode
            if saved_mode()=='cpu':images=filter_previews(*reduced,recipes,proof,amount)
            else:
                try:
                    from gpu_render import execute_pixel
                    images=execute_pixel(filter_previews,*reduced,recipes,proof,amount,host_result=True)
                except Exception as error:
                    from gpu_render import record_cpu_recovery
                    record_cpu_recovery('滤镜预览',error);images=filter_previews(*reduced,recipes,proof,amount)
            return key,images
        self.filter_renderer.submit(render)
