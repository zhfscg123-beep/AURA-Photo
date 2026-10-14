"""One-click RAW-base preparation and local LUT import inside presets."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from dark_ui import Section
import fuji_profiles as fuji


class FujiProfilesUI:
    def init_fuji_ui(self):
        self.fuji_note=tk.StringVar(value='富士风格支持RAW和普通照片；RAW自动准备线性基底。')
        self._pending_fuji_filter=None

    def build_fuji_controls(self,parent):
        ttk.Label(parent,text='独立照片版暂不提供富士风格。普通调色与开源精选仍可使用。',style='Muted.TLabel',wraplength=270).pack(fill='x',pady=5)

    def reload_fuji_library(self):
        items,error=fuji.presets();self.filter_library.external=items;self._fuji_library_error=error
        if hasattr(self,'filter_grid'):self.rebuild_filter_cards(False)
        self.sync_fuji_ui()

    def sync_fuji_ui(self):
        if not hasattr(self,'fuji_import_button'):return
        count=len(self.filter_library.external);raw=self.document is not None and self.document.is_raw
        self.fuji_import_button.configure(state='normal' if not self.busy else 'disabled')
        if getattr(self,'_fuji_library_error',''):message='富士LUT库未加载：'+self._fuji_library_error
        elif not count:message='尚未导入富士sRGB LUT，可选择包含11个_sRGB.cube的文件夹。'
        elif self.document is None:message=f'{count}种风格已准备；打开RAW、JPEG、PNG或TIFF即可使用。'
        elif not raw:message=f'{count}种风格可直接套用；使用当前照片的sRGB色彩，无需准备RAW基底。效果受原图已有调色影响。'
        elif fuji.base_ready(self.document):
            message=f'{count}种风格可套用；当前为机型匹配的Adobe Standard Linear基底。'
            message+=' 保留当前曝光，不额外添加固定亮度补偿。'
        else:message=f'{count}种风格已准备；点击风格卡片会自动准备RAW基底并套用。'
        self.fuji_note.set(message)

    def import_fuji_folder(self):
        if self.busy:return
        path=filedialog.askdirectory(title='选择包含11种富士 sRGB .cube 的文件夹',parent=self.color_dialog_parent())
        if not path:return
        try:count=fuji.import_folder(path)
        except (OSError,ValueError,KeyError,TypeError) as e:messagebox.showerror('富士LUT未导入',str(e),parent=self.color_dialog_parent());return
        self.reload_fuji_library();self.status.set(f'已导入{count}种富士风格。')

    def prepare_fuji_base(self,item=None,action=None):
        if not self.document or not self.document.is_raw or self.busy:
            self.status.set('请先打开RAW照片。');return
        import copy,camera_profiles
        try:
            profile,_=camera_profiles.resolve(camera_profiles.metadata(self.path),'Adobe Standard Linear')
            if profile is None:raise ValueError('此机型尚未安装Adobe Standard Linear DCP，请先导入对应机型的基础配置。')
        except (OSError,ValueError) as e:
            self.status.set(str(e))
            if not action or action.get('kind')!='batch':messagebox.showerror('无法准备富士RAW',str(e),parent=self.color_dialog_parent())
            return
        settings=copy.deepcopy(self.document.raw_settings)
        settings.update(process=1,camera_mode='profile',camera_profile=profile['name'],camera_look=True,
                        exposure=float(self.raw_ev.get()),white_balance={'机内白平衡':'camera','自动白平衡':'auto','日光白平衡':'daylight','自定义色温':'custom'}[self.raw_wb.get()],kelvin=self.raw_kelvin.get(),tint=self.raw_tint.get())
        settings['baseline_mode']=(item or {}).get('raw_base',fuji.RAW_BASE).get('baseline_mode','legacy')
        if fuji.base_ready(self.document) and settings==self.document.raw_settings:
            if action:self.complete_raw_action(action)
            elif item:self.choose_color_filter(item)
            else:self.show_fuji_filters()
            return
        source_before=copy.deepcopy(self.workflow_extensions.get('fuji_source'))
        baseline_changed=settings.get('baseline_mode')!=self.document.raw_settings.get('baseline_mode','legacy')
        if not fuji.base_ready(self.document) or (baseline_changed and source_before is None):
            self.commit_edit('准备富士来源前')
            self.workflow_extensions['fuji_source']={'version':1,'raw_settings':copy.deepcopy(self.document.raw_settings)}
        # Existing re-develop checks preserve coordinates, masks and edits, and
        # reject unsafe source changes instead of clearing user work.
        action=action or (dict(kind='filter',item=item) if item else dict(kind='browse'))
        self._pending_fuji_filter=dict(action=copy.deepcopy(action),path=self.path,before=self.document,mode='fuji',source_before=source_before)
        self.filter_preview_note.set('步骤 1/2：准备富士 RAW 基底；完成后自动套用风格。')
        self.open(self.path,settings,preserve=True)

    def poll_pending_fuji(self):
        pending=self._pending_fuji_filter
        if pending is None or self.busy or getattr(self,'_raw_recovery_pending',False):return
        if not self.document or self.path!=pending['path']:
            self.fail_raw_action(pending,'照片已切换，来源操作已停止。');return
        expected=fuji.base_ready(self.document) if pending.get('mode','fuji')=='fuji' else self.document.raw_settings==pending['settings']
        if self.document is pending['before'] or not expected:
            self.fail_raw_action(pending,'RAW 基底未准备完成，滤镜未套用。请检查处理提示。');return
        if self._render_pending:return
        if self._render_failed or self.color_input is None:
            self.fail_raw_action(pending,'基底渲染失败，滤镜未套用。');return
        self._pending_fuji_filter=None
        if pending.get('mode')=='standard':self.workflow_extensions.pop('fuji_source',None)
        self.filter_preview_note.set('步骤 2/2：正在套用风格…')
        # Source change plus its colour action is one undoable transaction.
        was_restoring=self.restoring_edit;self.restoring_edit=True
        try:self.complete_raw_action(pending.get('action',dict(kind='filter',item=pending.get('item'))))
        finally:self.restoring_edit=was_restoring
        self.commit_edit('应用RAW来源与调色')

    def fail_raw_action(self,pending,message):
        self._pending_fuji_filter=None;self.filter_preview_note.set(message);self.status.set(message)
        if pending.get('mode')=='fuji' and self.document is pending['before']:
            if pending.get('source_before') is None:self.workflow_extensions.pop('fuji_source',None)
            else:self.workflow_extensions['fuji_source']=pending['source_before']
        action=pending.get('action',{})
        if action.get('kind')=='batch' and self.raw_batch_matches(action):self._batch_failure(message)

    def raw_batch_matches(self,action):
        task=getattr(self,'_batch_task',None)
        return task and id(task)==action.get('task') and task.get('current')==action.get('current') and not task.get('cancelled')

    def complete_raw_action(self,action):
        kind=action['kind']
        if kind=='filter':self.choose_color_filter(action['item'],source_ready=True)
        elif kind=='style':self.apply_color_style(action['data'],action['name'],source_ready=True)
        elif kind=='xmp':self.apply_xmp_color(action['data'],action['report'],source_ready=True)
        elif kind=='amount':self.change_filter_amount(source_ready=True,amount=action['amount'])
        elif kind=='remove':self.remove_color_filter(source_ready=True,restoration=action['color'])
        elif kind=='reset':self.reset_global_color(source_ready=True)
        elif kind=='batch':
            if self.raw_batch_matches(action):self._batch_task['phase']='sync'
        elif kind=='browse':self.show_fuji_filters()

    def restore_standard_source(self,item,action=None):
        import copy
        settings=fuji.standard_settings(self.document,self.workflow_extensions)
        if settings==self.document.raw_settings:
            self.workflow_extensions.pop('fuji_source',None);return True
        action=action or dict(kind='filter',item=item)
        self.commit_edit('恢复普通RAW来源前')
        self._pending_fuji_filter=dict(action=copy.deepcopy(action),path=self.path,before=self.document,mode='standard',settings=settings)
        self.filter_preview_note.set('步骤 1/2：恢复普通 RAW 来源；完成后自动套用所选预设。')
        self.open(self.path,settings,preserve=True)
        return False

    def show_fuji_filters(self):
        self.color_workbench.open();self.color_workbench.show_page('预设')
        self.filter_group.set('富士');self.filter_query.set('');self.rebuild_filter_cards()

    def check_filter_raw_base(self,item,action=None):
        if item.get('recipe'):
            from color_presets import checked_preset
            item=checked_preset(item)
        # The LUT accepts display sRGB. Its DCP contract only applies to RAW
        # documents, including personal styles, XMP and batch continuations.
        if self.document is not None and not self.document.is_raw:return True
        if not item.get('raw_base'):
            if fuji.base_ready(self.document):return self.restore_standard_source(item,action)
            return True
        if fuji.base_ready(self.document):
            required_mode=item['raw_base'].get('baseline_mode','legacy')
            if self.document.raw_settings.get('baseline_mode','legacy')!=required_mode:
                self.prepare_fuji_base(item,action);return False
            return True
        if not self.document or not self.document.is_raw:
            self.status.set('富士 RAW 风格需要受支持机型的 RAW 照片。');return False
        self.prepare_fuji_base(item,action)
        return False
