"""Per-feature neutral comparisons never mutate edit recipes or export buffers."""
import copy,tkinter as tk
from collections import OrderedDict
from PIL import Image,ImageTk
from dpi_support import dp,ui_font
from dark_ui import COLORS
from tkinter import ttk
import numpy as np
from dark_ui import Section,ParameterScale
from beauty_settings import NAMES,neutral_values
from creative_portrait import DEFAULTS as SCENE_DEFAULTS,COLORS as SCENE_COLORS
from creative_color import DEFAULTS as COLOR_DEFAULTS
from region_masks import LOCAL_DEFAULTS
from render_queue import LatestRenderer
from photo_document import to_uint8

def descendants(w):
    yield w
    for child in w.winfo_children():yield from descendants(child)

class FeatureActionsUI:
    def init_feature_actions(self):
        self.feature_renderer=LatestRenderer();self.feature_compare_output=None;self.feature_compare_id=None;self.feature_compare_button=None;self.feature_compare_crop=None
        self.feature_compare_pending=False;self.feature_actions=[]
        self.feature_cache=OrderedDict();self.feature_cache_version=0;self.feature_job=None;self.feature_hold=False;self.feature_prepare_timer=None
        self.feature_held_view=None
        self.feature_frame_cache={}
        self.feature_notice_key=None;self.feature_notice_text=None;self.feature_notice_before=None
    def compare_notice(self,key,message):
        if self.feature_notice_key is None:self.feature_notice_before=self.status.get()
        self.feature_notice_key=key;self.feature_notice_text=message;self.status.set(message)
    def clear_compare_notice(self):
        if self.feature_notice_text and self.status.get()==self.feature_notice_text:self.status.set(self.feature_notice_before or '当前效果已恢复。')
        self.feature_notice_key=None;self.feature_notice_text=None;self.feature_notice_before=None
    def install_feature_actions(self):
        for key,root in self.nav_sections.items():
            root._feature_id=key
            if key in ('histogram','color_entry'):continue
            for section in list(descendants(root)):
                if not isinstance(section,Section):continue
                if section is not root and not any(isinstance(w,ParameterScale) for w in descendants(section)):continue
                if section.title in ('使用说明','笔刷设置','取样变换','旧版五段曲线（项目兼容）','RGB数值（精确输入）'):continue
                if getattr(section,'_feature_tools',False):continue
                section._feature_tools=True;row=ttk.Frame(section.body);row.pack(fill='x',pady=(0,8),before=section.body.winfo_children()[0] if section.body.winfo_children() else None)
                button=ttk.Button(row,text='按住对比',width=0);button.pack(side='left',fill='x',expand=True,padx=(0,3))
                for event in ('<Enter>','<FocusIn>'):button.bind(event,lambda e,s=section:self.prepare_feature_compare(s))
                for event in ('<ButtonPress-1>','<KeyPress-space>','<KeyPress-Return>'):button.bind(event,lambda e,s=section:self.hold_feature_compare(s))
                for event in ('<ButtonRelease-1>','<KeyRelease-space>','<KeyRelease-Return>','<FocusOut>'):button.bind(event,lambda e:self.release_feature_compare())
                label={'relight':'重置所有光源','relight_position':'重置此灯灯位','relight_material':'重置此灯受光','relight_protection':'重置此灯保护','mask_range':'清除渐变与范围'}.get(getattr(section,'_feature_scope',None),'重置本功能')
                reset=ttk.Button(row,text=label,width=0,command=lambda s=section:self.reset_feature(s));reset.pack(side='right',fill='x',expand=True,padx=(3,0))
                self.feature_actions.append((section,button,reset));section._compare_button=button
                section._feature_root=root;section._feature_id=key
    def scope(self,section):
        variables={str(w.variable) for w in descendants(section) if isinstance(w,ParameterScale)}
        people={name for name in NAMES if str(getattr(self,name)) in variables}
        scene={k for k,v in self.scene_vars.items() if str(v) in variables}
        colors={k for k,vs in self.scene_rgb.items() if any(str(v) in variables for v in vs)}
        color={k for k,v in self.creative_vars.items() if str(v) in variables}
        bg={k for k,v in self.background_vars.items() if str(v) in variables}
        key=section._feature_id;special=getattr(section,'_feature_scope',None)
        if key=='skin_color' and section is section._feature_root:people.add('skin_choice')
        if section is section._feature_root:
            special={'global_color':'color','reference':'reference','parts':'mask','smart_mask':'mask','manual':'manual','repair':'repair','liquify':'liquify','composition':'crop','clean':'clean','effects':'effects','raw':'raw','detection':'detection'}.get(key,special)
        if any(str(v) in variables for v in self.curve_vars):special=special or 'curve'
        if any(str(v) in variables for v in self.hsl_vars):special=special or 'hsl'
        return dict(people=people,scene=scene,colors=colors,color=color,bg=bg,special=special,key=key)
    def neutral_context(self,context,scope):
        fi=self.active_face;neutral=neutral_values()
        if fi<len(context.face_settings):
            for k in scope['people']:context.face_settings[fi][k]=neutral[k]
        for k in scope['people']:
            if hasattr(context,k):getattr(context,k).set(neutral[k])
        item=context.workflow_extensions.setdefault('people',{}).setdefault(str(fi),{})
        for k in scope['scene']:item[k]=SCENE_DEFAULTS[k]
        for k in scope['colors']:item[k]=SCENE_COLORS[k].copy()
        bg=context.workflow_extensions.setdefault('background',{})
        for k in scope['bg']:bg[k]=0
        color=context.workflow_extensions.setdefault('color',{});values=color.setdefault('values',{})
        for k in scope['color']:values[k]=COLOR_DEFAULTS[k]
        special=scope['special']
        if special=='relight':
            from relight_settings import defaults
            item['relight']=defaults();item['light']=0
        if special in ('relight_position','relight_material','relight_protection'):
            from relight_settings import reset_section
            item['relight']=reset_section(item.get('relight'),special)
        if special=='color':
            context.workflow_extensions.pop('color',None);context.workflow_extensions.pop('color_filter',None)
        if special in ('mask_range','mask_detail') and 0<=self.active_layer<len(context.region_layers):
            from local_develop import reset_section
            reset_section(context.region_layers[self.active_layer],special)
        if special=='curve':color['curve']=[0]*5;color['points']={}
        if special=='hsl':color['hsl']={}
        if special=='point_colors':color['point_colors']=[]
        if special=='bw':color['bw_mix']={};values['bw']=0
        if special=='wb':color['wb_sample']=None;values['wb_kelvin']=6500;values['wb_tint']=0
        if special=='optics':context.workflow_extensions.pop('optics',None)
        if special in ('optics_lens','optics_transform'):
            from develop_optics import reset_scope
            context.workflow_extensions['optics']=reset_scope(context.workflow_extensions.get('optics',{}),special)
        if special=='output':context.workflow_extensions.pop('output',None)
        if special=='beauty_mask':context.workflow_extensions.get('masks',{}).pop('beauty-include-'+str(fi),None)
        if special=='body_beauty_mask':context.workflow_extensions.get('masks',{}).pop('body-beauty-include-'+str(fi),None)
        if special in ('beauty_mask','body_beauty_mask'):context.workflow_extensions.get('masks',{}).pop(('body-' if special=='body_beauty_mask' else '')+'beauty-exclude-'+str(fi),None)
        if special=='reference':context.workflow_extensions.pop('reference',None)
        if special=='mask' and 0<=self.active_layer<len(context.region_layers):context.region_layers[self.active_layer]['parameters']=dict(LOCAL_DEFAULTS)
        if special=='manual':context.manual_records=[]
        if special=='repair':context.patches=[];context.selection.mask&=context.selection.auto
        if special=='liquify':context.liquify_enabled.set(False)
        if special=='clean':
            if self.clean_target.get()=='背景':bg['clean']=0
            else:item['clothes_clean']=0
        if special=='effects':context.workflow_extensions.setdefault('effects',{})[self.effect_key()]=dict(enabled=False,opacity=0)
        if special=='detection':context.workflow_extensions.setdefault('effects',{})['repair']=dict(enabled=False,opacity=0)
        return context
    def feature_cache_key(self,section):return section,self.feature_cache_version,id(self.document),id(self.session)
    def invalidate_feature_cache(self):
        self.clear_compare_notice()
        self.feature_cache_version+=1;self.feature_cache.clear();self.feature_frame_cache.clear();self.feature_job=None;self.feature_renderer.invalidate()
        if self.feature_prepare_timer is not None:self.root.after_cancel(self.feature_prepare_timer);self.feature_prepare_timer=None
    def schedule_feature_compare(self,section=None):
        if self.feature_prepare_timer is not None:self.root.after_cancel(self.feature_prepare_timer)
        self.feature_prepare_timer=self.root.after(120,lambda:self.warm_feature_compare(section))
    def warm_feature_compare(self,section):
        self.feature_prepare_timer=None
        if self.feature_job is not None:return
        if section is None:
            opened=[s for s in self.category_sections.get(getattr(self,'active_category',None),[]) if s.opened and getattr(s,'_feature_tools',False) and s.winfo_ismapped()]
            section=self.feature_compare_id if self.feature_hold else opened[0] if opened else None
        if section is not None:
            from fuji_profiles import base_ready
            # A cross-source comparison needs fresh portrait analysis. Prepare
            # it on hover/press, not after every slider or RAW source change.
            if not self.feature_hold and self.scope(section)['special']=='color' and base_ready(self.document):return
            self.prepare_feature_compare(section)
    def prepare_feature_compare(self,section):
        if not self.document or self.busy or self.drag or self._render_pending or self._closing:return
        if any(getattr(c,'dragging',False) for c in self.controls):return
        if getattr(getattr(self,'point_curve_editor',None),'dragging',False):return
        key=self.feature_cache_key(section)
        if key in self.feature_cache or self.feature_job and self.feature_job['key']==key:return
        scope=self.scope(section)
        from fuji_profiles import base_ready,standard_settings
        restore_source=scope['special']=='color' and base_ready(self.document)
        source_settings=standard_settings(self.document,self.workflow_extensions) if restore_source else None
        threshold=self.threshold.get()
        color_only=not restore_source and scope['special'] in ('color','curve','hsl','point_colors','bw','wb','reference') and self.color_input is not None
        context=self.neutral_context(self.color_context() if color_only else self.render_context(),scope)
        cw,ch=self.size();height,width=self.output.shape[:2];scale=self.view.scale
        a=max(0,int(np.floor(self.view.cx-cw/(2*scale))));b=max(0,int(np.floor(self.view.cy-ch/(2*scale))))
        c=min(width,int(np.ceil(self.view.cx+cw/(2*scale))));d=min(height,int(np.ceil(self.view.cy+ch/(2*scale))))
        cut=int(np.clip(round(self.view.to_image(cw*self.split.get()/100,0,(cw,ch))[0])-a,0,max(0,c-a)))
        frame=dict(signature=self.compare_frame_key(),bounds=(a,b,c,d),size=(max(1,round((c-a)*scale)),max(1,round((d-b)*scale))),cut=cut,position=self.view.to_canvas(a,b,(cw,ch)))
        render=getattr(type(self),'_render_color_pixels_cpu',type(self)._render_color_pixels) if color_only else getattr(type(self),'_render_pixels_cpu',type(self)._render_pixels)
        self.feature_job=dict(key=key,section=section,frame=frame)
        def worker():
            if restore_source:
                from raw_compare_context import prepare
                prepare(context,source_settings,threshold)
            if scope['special']=='raw' and context.document.is_raw:
                from photo_document import open_document
                settings=dict(context.document.raw_settings,exposure=0,white_balance='camera');doc=open_document(context.document.path,settings)
                if doc.rgb.shape!=context.document.rgb.shape:raise ValueError('RAW中性显影尺寸不同，请先统一RAW来源。')
                context.document=doc
            from gpu_render import render_automatic
            render_automatic(context,render);pixels=context.output;image=None
            if a<c and b<d and frame['signature'][-1]!='构图':
                shown=pixels[b:d,a:c].copy();shown[:,:cut]=context.session.original[b:d,a:a+cut]
                image=Image.fromarray(shown).resize(frame['size'],Image.Resampling.LANCZOS)
            return pixels,image
        self.feature_renderer.submit(worker)
    def compare_feature(self,section):
        # Programmatic pinned comparison remains available to validation and
        # internal commands; the visible button uses the hold/release bindings.
        if self.feature_compare_id is section:self.end_feature_compare();self.draw();return
        return self.hold_feature_compare(section,grab=False)
    def compare_view_key(self):
        return (id(self.output),self.feature_cache_version,self.mode.get(),getattr(self,'active_category',None),self.view.cx,self.view.cy,self.view.scale,self.size(),self.root._ui_dpi)
    def compare_frame_key(self):return self.view.cx,self.view.cy,self.view.scale,self.size(),self.split.get(),getattr(self,'active_category',None)
    def draw_fast_feature_compare(self):
        if self.feature_compare_id is None:return False
        frame=self.feature_frame_cache.get(self.feature_cache_key(self.feature_compare_id))
        if frame is None or frame['signature']!=self.compare_frame_key():return False
        self.photo=frame['image'];self.canvas.delete('all');self.canvas.create_image(*frame['position'],anchor='nw',image=self.photo)
        if 0<self.split.get()<100:
            x=self.size()[0]*self.split.get()/100;self.canvas.create_line(x,0,x,self.size()[1],fill='white',width=1)
        self.canvas.create_text(dp(self.root,15),dp(self.root,15),text='本功能关闭对比 · '+self.feature_compare_id.title,anchor='nw',fill=COLORS['accent'],font=ui_font(self.root,11,'bold'))
        return True
    def capture_compare_view(self):
        items=[]
        for item in self.canvas.find_all():
            config={k:v[-1] for k,v in self.canvas.itemconfigure(item).items()}
            items.append((self.canvas.type(item),self.canvas.coords(item),config))
        return dict(key=self.compare_view_key(),items=items,photo=getattr(self,'photo',None),crop_photo=getattr(self,'crop_photo',None))
    def restore_compare_view(self,snapshot):
        if snapshot is None or snapshot['key']!=self.compare_view_key():return False
        self.photo=snapshot['photo']
        if snapshot['crop_photo'] is not None:self.crop_photo=snapshot['crop_photo']
        self.canvas.delete('all')
        for kind,coords,config in snapshot['items']:getattr(self.canvas,'create_'+kind)(*coords,**config)
        return True
    def hold_feature_compare(self,section,grab=True):
        if not self.document or self.busy or self.drag:return 'break'
        if self.feature_hold and self.feature_compare_id is section:return 'break'
        # Do not block the press waiting for a full-image parameter render.
        # An in-flight render warms this comparison when it finishes.
        if not self._render_pending:self.flush_parameters()
        if self.feature_compare_id is not None:self.end_feature_compare();self.draw()
        self.end_feature_compare()
        self.feature_held_view=self.capture_compare_view()
        self.feature_hold=True;self.feature_compare_id=section;self.feature_compare_button=section._compare_button
        self.feature_compare_button.state(['pressed'])
        if grab:
            self.feature_compare_button.focus_set();self.feature_compare_button.grab_set()
        self.feature_compare_crop={} if self.scope(section)['special']=='crop' else None
        pixels=self.feature_cache.get(self.feature_cache_key(section))
        if pixels is not None:
            self.feature_compare_output=pixels;self.feature_compare_pending=False;self.feature_compare_button.configure(text='关闭效果 · 松开恢复');self.draw()
        else:
            self.feature_compare_pending=True;self.feature_compare_button.configure(text='对比准备中…');self.prepare_feature_compare(section)
            self.compare_notice(self.feature_cache_key(section),'正在准备首次对比；松开立即恢复，完成后会提示。')
        return 'break'
    def release_feature_compare(self):
        if self.feature_hold:
            snapshot=self.feature_held_view;self.end_feature_compare()
            if not self.restore_compare_view(snapshot):self.draw()
        return 'break'
    def poll_feature_compare(self):
        result=self.feature_renderer.take()
        if result is None:return
        _,payload,error=result
        job=self.feature_job;self.feature_job=None
        if job is None or job['key']!=self.feature_cache_key(job['section']):return
        if error:
            notify=self.feature_notice_key==job['key'] or self.feature_compare_id is job['section']
            if self.feature_compare_id is job['section']:self.end_feature_compare()
            if notify:
                message='对比未生成：'+error.splitlines()[-1]
                self.clear_compare_notice();self.status.set(message)
            return
        pixels,image=payload
        self.feature_cache[job['key']]=pixels;self.feature_cache.move_to_end(job['key'])
        if image is not None:
            self.feature_frame_cache[job['key']]=dict(job['frame'],image=ImageTk.PhotoImage(image,master=self.root))
        while len(self.feature_cache)>2:
            expired,_=self.feature_cache.popitem(last=False);self.feature_frame_cache.pop(expired,None)
        if self.feature_notice_key==job['key']:
            notify=self.status.get()==self.feature_notice_text
            self.clear_compare_notice()
            if notify:self.status.set('对比已准备完成；按住查看，松开恢复当前效果。')
        if self.feature_hold and self.feature_compare_id is job['section']:
            self.feature_compare_output=pixels;self.feature_compare_pending=False;self.feature_compare_button.configure(text='关闭效果 · 松开恢复');self.draw()
    def end_feature_compare(self):
        if not hasattr(self,'feature_renderer'):return
        self.feature_compare_output=None;self.feature_compare_crop=None;self.feature_compare_id=None;self.feature_compare_pending=False;self.feature_hold=False
        if self.feature_compare_button and self.feature_compare_button.winfo_exists():
            if self.root.grab_current() is self.feature_compare_button:self.feature_compare_button.grab_release()
            self.feature_compare_button.state(['!pressed']);self.feature_compare_button.configure(text='按住对比')
        self.feature_compare_button=None
        self.feature_held_view=None
        if self.feature_notice_text and self.status.get()==self.feature_notice_text:
            if self.feature_job and self.feature_job['key']==self.feature_notice_key:
                self.feature_notice_text='当前效果已恢复；对比仍在准备，完成后会提示。';self.status.set(self.feature_notice_text)
            else:self.clear_compare_notice()
    def reset_feature(self,section):
        if self.busy or self.drag:return
        if self.scope(section)['special']=='color':self.reset_global_color();return
        self.flush_parameters()
        if self.busy:return
        self.end_feature_compare();self.commit_edit('重置功能前');scope=self.scope(section);neutral=neutral_values()
        self.loading_face=True;self.loading_scene=True;self.loading_creative=True
        try:
            for k in scope['people']:getattr(self,k).set(neutral[k])
            for k in scope['scene']:self.scene_vars[k].set(SCENE_DEFAULTS[k])
            for k in scope['colors']:
                for var,value in zip(self.scene_rgb[k],SCENE_COLORS[k]):var.set(value)
            for k in scope['color']:self.creative_vars[k].set(COLOR_DEFAULTS[k])
            for k in scope['bg']:self.background_vars[k].set(0)
        finally:self.loading_face=False;self.loading_scene=False;self.loading_creative=False
        self.sync_person_values()
        item=self.workflow_extensions.setdefault('people',{}).setdefault(str(self.active_face),{})
        for k in scope['scene']:item[k]=SCENE_DEFAULTS[k]
        for k in scope['colors']:item[k]=SCENE_COLORS[k].copy()
        bg=self.workflow_extensions.setdefault('background',{})
        for k in scope['bg']:bg[k]=0
        color=self.workflow_extensions.setdefault('color',{});values=color.setdefault('values',{})
        for k in scope['color']:values[k]=COLOR_DEFAULTS[k]
        special=scope['special']
        if special=='color':self.workflow_extensions.pop('color',None);self.workflow_extensions.pop('color_filter',None)
        if special=='relight':
            from relight_settings import defaults
            item['relight']=defaults();item['light']=0;self.sync_relight_ui()
        if special in ('relight_position','relight_material','relight_protection'):
            from relight_settings import reset_section
            item['relight']=reset_section(item.get('relight'),special);self.sync_relight_ui()
        if special in ('mask_range','mask_detail') and 0<=self.active_layer<len(self.region_layers):
            from local_develop import reset_section
            reset_section(self.region_layers[self.active_layer],special);self.sync_layers()
        if special=='curve':color['curve']=[0]*5;color['points']={}
        if special=='hsl':color['hsl']={}
        if special=='point_colors':color['point_colors']=[]
        if special=='bw':color['bw_mix']={};values['bw']=0
        if special=='wb':color['wb_sample']=None;values['wb_kelvin']=6500;values['wb_tint']=0
        if special=='optics':self.workflow_extensions.pop('optics',None)
        if special in ('optics_lens','optics_transform'):
            from develop_optics import reset_scope
            self.workflow_extensions['optics']=reset_scope(self.workflow_extensions.get('optics',{}),special)
        if special=='output':self.workflow_extensions.pop('output',None)
        if special=='beauty_mask':self.workflow_extensions.get('masks',{}).pop('beauty-include-'+str(self.active_face),None)
        if special=='body_beauty_mask':self.workflow_extensions.get('masks',{}).pop('body-beauty-include-'+str(self.active_face),None)
        if special in ('beauty_mask','body_beauty_mask'):self.workflow_extensions.get('masks',{}).pop(('body-' if special=='body_beauty_mask' else '')+'beauty-exclude-'+str(self.active_face),None)
        if special in ('beauty_mask','body_beauty_mask'):
            prefix=('body-' if special=='body_beauty_mask' else '')+'beauty-'
            for kind in ('include-','exclude-'):self.workflow_extensions.get('masks',{}).pop('draft-'+prefix+kind+str(self.active_face),None)
            self.sync_beauty_draft_ui()
        if special=='reference':self.workflow_extensions.pop('reference',None)
        if special=='mask' and 0<=self.active_layer<len(self.region_layers):self.region_layers[self.active_layer]['parameters']=dict(LOCAL_DEFAULTS);self.sync_layers()
        if special=='manual':self.manual_records=[];self.reset_manual_offset();self.load_manual_settings()
        if special=='repair':
            self.patches=[];self.selected_patch=None;self.selection.mask&=self.selection.auto;self.radius.set(8);self.feather.set(0);self.patch_opacity.set(100)
        if special=='liquify':
            self.liquify_state=None;self.liquify_enabled.set(False);self.sync_liquify_ui()
        if special=='crop':self.workflow_extensions.pop('composition',None);self.sync_composition_ui()
        if special=='clean':
            if self.clean_target.get()=='背景':bg['clean']=0
            else:item['clothes_clean']=0
        if special=='effects':self.workflow_extensions.get('effects',{}).pop(self.effect_key(),None);self.workflow_extensions.get('masks',{}).pop('erase-'+self.effect_key(),None);self.sync_effect_ui()
        if special=='raw':self.raw_ev.set(0);self.raw_wb.set('机内白平衡')
        if special=='detection':self.threshold.set(.35)
        if scope['key']=='skin_color':self.sync_color_ui()
        self.sync_scene_ui();self.sync_creative_color_ui()
        if special=='raw' and self.document and self.document.is_raw:self.redevelop()
        elif special in ('color','curve','hsl','reference'):self.refresh_color()
        else:self.parameter_apply(self.refresh)
        self.record('重置本功能 · '+section.title);self.draw()
