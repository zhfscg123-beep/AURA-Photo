"""Manual additions to continuous face beauty, separate from acne selections."""
import copy,tkinter as tk
from tkinter import ttk
import numpy as np
from dark_ui import Section
import effect_controls
from workflow_extensions import MAX_MASKS
from PIL import Image
import cv2

class BeautyMaskUI:
    def init_beauty_mask(self):
        self.beauty_range_overlay=tk.BooleanVar(value=True);self.beauty_auto_overlay=tk.BooleanVar(value=False);self.beauty_auto_cache=None
        self.beauty_view_cache=None;self.beauty_draw_timer=None;self.beauty_draft_notes={}
    def build_beauty_mask_controls(self,body,scope='face'):
        is_body=scope=='body';section=Section(body,'身体皮肤范围补选' if is_body else '美颜范围补选',opened=False)
        section._feature_scope='body_beauty_mask' if is_body else 'beauty_mask'
        if is_body:self.body_beauty_range_panel=section
        else:self.beauty_range_panel=section
        row=ttk.Frame(section.body);row.pack(fill='x',pady=4)
        for label,mode in [('画笔补选','beauty_add'),('擦除范围','beauty_subtract')]:
            mode=mode.replace('beauty_','beauty_body_') if is_body else mode
            b=ttk.Button(row,text=label,command=lambda m=mode:self.toggle_tool(m));b.pack(side='left',fill='x',expand=True,padx=2);self.controls.append(b);self.register_mode_button(b,mode)
        self.controls.append(self.slider(section.body,'画笔半径 / 原图像素',self.radius,1,250,self.draw_tool_cursor,mutating=False))
        ttk.Checkbutton(section.body,text='显示当前人物补选范围',variable=self.beauty_range_overlay,command=self.draw).pack(anchor='w',pady=5)
        check=ttk.Checkbutton(section.body,text='显示 AI 自动皮肤范围（绿色）',variable=self.beauty_auto_overlay,command=self.draw)
        if is_body:self.body_beauty_auto_check=check
        else:self.beauty_auto_check=check
        check.pack(anchor='w',pady=5)
        self.mode_button(section.body,'画笔恢复自动范围','beauty_body_restore' if is_body else 'beauty_restore')
        self.button(section.body,'更新当前范围',lambda:self.apply_beauty_range(scope),accent=True)
        note=tk.StringVar(value='范围已更新');self.beauty_draft_notes[scope]=note
        ttk.Label(section.body,textvariable=note,style='Muted.TLabel',wraplength=260).pack(anchor='w',pady=4)
        self.button(section.body,'恢复自动范围 · 清除手动编辑',lambda:self.clear_beauty_include(scope))
        self.button(section.body,'返回浏览',lambda:self.select_tool('pan'))
        text='补画脖颈、手臂等漏识别皮肤，再点击更新应用身体参数。面部与其他已确认人物保持保护。' if is_body else '补画刘海、发丝附近漏识别的可见皮肤，再点击更新应用面部参数。眼球保持保护；只作用于当前人物面部范围，不会自动去除头发。'
        ttk.Label(section.body,text='绿色为自动范围，青色为补选，红色为已擦除。'+text+'擦除可排除AI自动范围；恢复画笔局部恢复原自动范围。边缘自动渐淡。右键临时擦除，Ctrl＋滚轮调大小，空格平移，Esc返回浏览。',style='Muted.TLabel',wraplength=260).pack(anchor='w',pady=5)
    def beauty_include_key(self,scope=None):
        if scope is None:scope='body' if self.mode.get().startswith('beauty_body_') or getattr(self,'active_category',None)=='身体' else 'face'
        return ('body-beauty-include-' if scope=='body' else 'beauty-include-')+str(self.active_face)
    def sync_beauty_draft_ui(self):
        for scope,note in self.beauty_draft_notes.items():
            key=self.beauty_include_key(scope);pending='draft-'+key in self.workflow_extensions.get('masks',{})
            note.set('范围有未应用修改 · 点击“更新当前范围”' if pending else '范围已更新')
    def staged_beauty_keys(self,scope=None):
        key=self.beauty_include_key(scope);return 'draft-'+key,'draft-'+key.replace('include','exclude')
    def stage_beauty_range(self,scope=None):
        keys=self.staged_beauty_keys(scope);masks=self.workflow_extensions.setdefault('masks',{})
        if len(masks)+sum(k not in masks for k in keys)>MAX_MASKS:return None
        for k in keys:
            if k not in masks:masks[k]=masks[k[6:]].copy() if k[6:] in masks else np.zeros(self.document.rgb.shape[:2],bool)
        return keys
    def shown_beauty_mask(self,key):
        masks=self.workflow_extensions.get('masks',{});return masks.get('draft-'+key,masks.get(key))
    def apply_beauty_range(self,scope=None):
        if self.busy or self.drag or self.document is None:return
        self.commit_edit('更新美颜范围前');masks=self.workflow_extensions.setdefault('masks',{});keys=self.staged_beauty_keys(scope)
        if not any(k in masks for k in keys):self.status.set('当前范围没有待更新的修改。');return
        for k in keys:
            if k in masks:masks[k[6:]]=masks.pop(k)
        self.sync_beauty_draft_ui();self.parameter_apply(self.refresh);self.record('手动更新'+('身体' if self.beauty_include_key(scope).startswith('body-') else '面部')+'范围')
    def start_beauty_paint(self,event,erase=False):
        if not self.session.faces:self.status.set('请先导入并识别人物。');return
        if self.shape_pending():self.status.set('请等待人物形变完成后补选。');return
        self.commit_edit('美颜范围编辑前');keys=self.stage_beauty_range()
        if keys is None:self.status.set('蒙版数量已达上限，请清理不需要的效果蒙版。');return
        key,exclude_key=keys
        action='erase' if erase else 'add' if self.mode.get().endswith('_add') else 'restore' if self.mode.get().endswith('_restore') else 'erase'
        p=self.original_point(self.point(event));self.drag=dict(mode='beauty_paint',key=key,exclude_key=exclude_key,last=p,r=self.brushradius(),action=action,person=self.active_face,body=key.startswith('draft-body-'))
        self.update_beauty_paint(self.point(event))
    def update_beauty_paint(self,p):
        d=self.drag;q=self.original_point(p);masks=self.workflow_extensions['masks']
        include=masks[d['key']];exclude=masks[d['exclude_key']];start=d['last'];end=q
        if not d['body']:
            a,b,c,e=self.session.faces[d['person']].box;include=include[b:e,a:c];exclude=exclude[b:e,a:c];start=np.asarray(start)-[a,b];end=np.asarray(end)-[a,b]
        if d['action']!='restore':effect_controls.paint(include,start,end,d['r'],d['action']=='add')
        effect_controls.paint(exclude,start,end,d['r'],d['action']=='erase')
        d['last']=q
        if self.beauty_draw_timer is None:self.beauty_draw_timer=self.root.after(25,self.flush_beauty_draw)
    def flush_beauty_draw(self):
        self.beauty_draw_timer=None;self.draw()
    def finish_beauty_paint(self):
        body=self.drag['body'];action=self.drag['action'];self.drag=None
        if self.beauty_draw_timer is not None:self.root.after_cancel(self.beauty_draw_timer);self.beauty_draw_timer=None
        self.sync_beauty_draft_ui();self.draw()
        self.record(('身体' if body else '面部')+'范围 · '+{'add':'手动补选','erase':'擦除识别范围','restore':'恢复自动范围'}[action])
        self.status.set('范围已绘制，尚未应用。完成后点击“更新当前范围”。')
    def clear_beauty_include(self,scope=None):
        if self.busy or self.drag:return
        if self.document is None:return
        self.commit_edit('清除美颜补选前');keys=self.stage_beauty_range(scope)
        if keys is None:self.status.set('蒙版数量已达上限。');return
        for key in keys:self.workflow_extensions['masks'][key][:]=False
        self.sync_beauty_draft_ui();self.draw();self.record(('身体' if self.beauty_include_key(scope).startswith('body-') else '面部')+'范围 · 恢复自动范围')
    def automatic_beauty_preview(self):
        fi=self.active_face;labels=self.session.part_labels[fi];skin=self.session.part_regions[fi]['skin'];is_body=self.active_category=='身体'
        signature=(id(self.session),fi,id(labels),id(skin),is_body,id(getattr(self.session,'body_owner',None)))
        if self.beauty_auto_cache is None or self.beauty_auto_cache[0]!=signature:
            from region_masks import face_beauty_mask,part_mask
            if is_body:automatic=part_mask(self.session,fi,'body').copy()
            else:
                probe=copy.copy(self.session);probe.faces=self.session.faces.copy();probe.faces[fi]=copy.copy(probe.faces[fi]);probe.beauty_include={};probe.beauty_exclude={}
                f=probe.faces[fi];a,b,c,d=f.box;local=face_beauty_mask(probe,fi)>0
                automatic=np.zeros(self.session.original.shape[:2],bool);automatic[b:d,a:c]=local
            self.beauty_auto_cache=(signature,automatic)
        return self.beauty_auto_cache[1]
    def fast_beauty_display(self,bounds,size,localcut):
        a,b,c,d=bounds;key=(id(self.output),bounds,size,localcut,self.view.scale,id(self.liquify_state),self.reshape_changed,getattr(self,'photo_body_changed',False))
        if self.beauty_view_cache is None or self.beauty_view_cache[0]!=key:
            rgb=self.display_rgb(bounds);rgb[:,:localcut]=self.session.original[b:d,a:a+localcut]
            self.beauty_view_cache=(key,np.array(Image.fromarray(rgb).resize(size,Image.Resampling.LANCZOS)))
        rgb=self.beauty_view_cache[1].copy()
        def project(mask):
            if mask is None:return np.zeros(rgb.shape[:2],bool)
            local=self.mask_for_display(mask,bounds,localcut);shown=cv2.resize(local.view(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0
            shown[:,:round(localcut*size[0]/max(1,c-a))]=False;return shown
        def tint(shown,color,opacity):
            if not shown.any():return
            solid=np.empty_like(rgb);solid[:]=color
            blended=cv2.addWeighted(rgb,1-opacity,solid,opacity,0);rgb[shown]=blended[shown]
        include=self.shown_beauty_mask(self.beauty_include_key());exclude=self.shown_beauty_mask(self.beauty_include_key().replace('include','exclude'))
        if self.beauty_auto_overlay.get() and self.session.faces:
            shown=project(self.automatic_beauty_preview())&~project(exclude);tint(shown,[70,200,90],.22)
        if self.beauty_range_overlay.get():
            for mask,color,opacity in ((include,[45,205,185],.35),(exclude,[235,90,95],.30)):
                tint(project(mask),color,opacity)
        return Image.fromarray(rgb)
    def decorate_display(self,rgb,bounds,localcut):
        super().decorate_display(rgb,bounds,localcut)
        if getattr(self,'feature_compare_output',None) is not None:return
        scope='body' if getattr(self,'active_category',None)=='身体' else 'face'
        key=self.beauty_include_key(scope);exclude=self.shown_beauty_mask(key.replace('include','exclude'))
        if self.beauty_auto_overlay.get() and self.session.faces and getattr(self,'active_category',None) in ('美颜','身体'):
            shown=self.mask_for_display(self.automatic_beauty_preview(),bounds,localcut).copy()
            if exclude is not None:shown&=~self.mask_for_display(exclude,bounds,localcut)
            shown[:,:localcut]=False;rgb[shown]=np.rint(rgb[shown]*.78+np.array([70,200,90])*.22).astype(np.uint8)
        if not self.mode.get().startswith('beauty_') or not self.beauty_range_overlay.get():return
        for mask,color,opacity in ((self.shown_beauty_mask(key),[45,205,185],.35),(exclude,[235,90,95],.30)):
            if mask is not None:
                shown=self.mask_for_display(mask,bounds,localcut).copy();shown[:,:localcut]=False
                rgb[shown]=np.rint(rgb[shown]*(1-opacity)+np.array(color)*opacity).astype(np.uint8)
