"""Asynchronous numeric commits; fast global-color preview while dragging."""
import copy,time
import cv2,numpy as np
from render_queue import Value,LatestRenderer,detached
from creative_scene_ui import CreativeSceneUI
from creative_color_ui import CreativeColorUI
from effect_ui import EffectUI
from photo_document import to_uint8
from photo_body_ui import PhotoBodyUI
from live_body import BODY_KEYS

class RenderContext(PhotoBodyUI,CreativeSceneUI,CreativeColorUI,EffectUI):pass

class ResponsiveRenderUI:
    def init_responsive_render(self):
        self.renderer=LatestRenderer();self._render_pending=False;self._parameter_apply=False;self._render_identity=None;self._render_failed=False
        self._preview_rgb=None;self._preview_skin=None;self._preview_key=None;self._preview_frame=None;self._preview_at=0
        self._render_stage=None
    def parameter_apply(self,command):
        old=self._parameter_apply;self._parameter_apply=True
        try:command()
        finally:self._parameter_apply=old
    def render_context(self):
        context=RenderContext();memo={}
        for name in ('document','session','generated','done_mask','small_mask','face_settings','region_layers','patches','manual_records','workflow_extensions','form_cache','reshape_cache','photo_body_cache','liquify_state'):
            setattr(context,name,detached(getattr(self,name),memo))
        # Selections are edited in place by paint tools, unlike immutable analysis buffers.
        context.selection=copy.copy(self.selection)
        context.selection.mask=self.selection.mask.copy();context.selection.auto=self.selection.auto.copy()
        context.selection.undo_stack=[];context.selection.redo_stack=[]
        for name in ('repair','smooth','whiten','texture','wrinkles','dark_circles','feather','manual_enabled','liquify_enabled')+BODY_KEYS:
            setattr(context,name,Value(getattr(self,name).get()))
        context.clean_note=Value();context.light_note=Value();return context
    def queue_parameter_render(self):
        self.sync_person_values();context=self.render_context();identity=(id(self.document),id(self.session))
        self._light_progress=context.light_note
        self._render_identity=identity;self._render_pending=True
        self._render_failed=False
        self._render_stage='full'
        render=getattr(type(self),'_render_pixels_cpu',type(self)._render_pixels)
        from gpu_render import render_automatic
        self.renderer.submit(lambda:(context,render_automatic(context,render)))
        self.status.set('正在后台更新完整图像…可继续调整参数。');self.mark_draft()
    def color_context(self):
        context=self.render_context();memo={}
        for name in ('output','output_float','manual_input','creative_input','creative_output','color_input','liquify_input','slim_changed','form_changed','reshape_changed','photo_body_cache','photo_body_changed','photo_body_message'):
            setattr(context,name,detached(getattr(self,name,None),memo))
        return context
    def refresh_color(self):
        if hasattr(self,'filter_amount_control'):self.sync_filter_ui()
        if not self.document or not self.session:return
        if self.color_input is None or self._render_pending and self._render_stage!='color':self.parameter_apply(self.refresh);return
        self.end_feature_compare();self.invalidate_feature_cache();context=self.color_context();self._render_stage='color'
        self._render_identity=(id(self.document),id(self.session));self._render_pending=True;self._render_failed=False
        render=getattr(type(self),'_render_color_pixels_cpu',type(self)._render_color_pixels)
        from gpu_render import render_automatic
        self.renderer.submit(lambda:(context,render_automatic(context,render)))
        self.status.set('正在更新调色 · 复用已完成的美颜和识别');self.mark_draft()
    def consume_render(self,wait=False):
        result=self.renderer.take(wait)
        if result is None:
            progress=getattr(self,'_light_progress',None)
            if self._render_pending and progress is not None and progress.get() and hasattr(self,'light_note'):self.light_note.set(progress.get())
            return
        _,payload,error=result
        if self._render_identity!=(id(self.document),id(self.session)):return
        self._render_pending=False;self._render_stage=None;self._preview_frame=None;self._preview_key=None;self._preview_rgb=None;self._preview_skin=None
        if error:
            self._render_failed=True
            if hasattr(self,'light_note'):self.light_note.set('补光更新未完成，请查看底部状态与错误记录。')
            from core import ROOT
            (ROOT/'render-error.log').write_text(error,encoding='utf8');self.status.set('参数更新失败，保留上一结果；详情见 render-error.log');return
        context,_=payload
        if hasattr(context,'gpu_render_report'):self.gpu_render_report=context.gpu_render_report
        fresh=getattr(context.session,'relight_cache',None)
        if fresh is not None:
            existing=getattr(self.session,'relight_cache',{})
            if {k:v['key'] for k,v in existing.items()}!={k:v['key'] for k,v in fresh.items()}:self.session.relight_cache=fresh
        for name in ('output','output_float','manual_input','creative_input','creative_output','color_input','liquify_input','slim_changed','form_changed','reshape_changed','photo_body_cache','photo_body_changed','photo_body_message'):
            setattr(self,name,getattr(context,name))
        if context.clean_note.get():self.clean_note.set(context.clean_note.get())
        if getattr(context,'light_note',None) and context.light_note.get():self.light_note.set(context.light_note.get())
        self.finish_refresh()
    def wait_parameter_render(self):
        if self._render_pending:self.consume_render(wait=True)
        self._preview_frame=None
        if self._render_failed:raise ValueError('最新参数未成功生成，请重新调整参数或恢复上一编辑状态，暂不能保存旧结果。')
    def invalidate_parameter_render(self):
        self.renderer.invalidate();self._render_pending=False;self._preview_frame=None;self._render_failed=False
        self._preview_key=None;self._preview_rgb=None;self._preview_skin=None
    def preview_global_color(self):
        """Approximate drag feedback only; never saved/exported or used as a source."""
        if self.document is None or self._render_pending or self.creative_output is None:return
        from develop_optics import geometry_active
        if geometry_active(self.workflow_extensions.get('optics',{})):return
        import effect_controls
        if any(effect_controls.settings(self.workflow_extensions,k)!=(True,1.) for k in ('color','creative')) or any(self.workflow_extensions.get('reference',{}).get(k,0) for k in ('color','tone')):return
        # A preview uses the existing full render's scene output before global color.
        base=getattr(self,'color_input',None)
        if base is None:return
        # Geometry makes color spatially dependent; use the background full render instead.
        if self.form_changed is not None and self.form_changed.any():return
        key=(base.__array_interface__['data'][0],base.shape)
        h,w=base.shape[:2];factor=min(1,1400/max(h,w));size=(max(1,round(w*factor)),max(1,round(h*factor)))
        if key!=self._preview_key:
            from creative_regions import regions
            h,w=base.shape[:2];factor=min(1,1400/max(h,w));size=(max(1,round(w*factor)),max(1,round(h*factor)))
            self._preview_rgb=cv2.resize(base,size,interpolation=cv2.INTER_AREA)
            self._preview_skin=cv2.resize(regions(self.session,self.region_layers)['skin'].astype(np.float32),size,interpolation=cv2.INTER_AREA)
            from types import SimpleNamespace
            scene=getattr(self.document,'scene',None)
            self._preview_document=SimpleNamespace(rgb=cv2.resize(self.document.rgb,size,interpolation=cv2.INTER_AREA),scene=None if scene is None else cv2.resize(scene,size,interpolation=cv2.INTER_AREA))
            self._preview_key=key
        now=time.monotonic()
        if now-self._preview_at<.033:return
        self._preview_at=now
        import creative_color as color
        values=dict(self.workflow_extensions.get('color',{}),process=2 if self.color_process.get()=='专业浮点调色' else 1,values={k:v.get() for k,v in self.creative_vars.items()},curve=[v.get() for v in self.curve_vars])
        # Keep HSL current without persisting a provisional setting.
        values['hsl']=copy.deepcopy(values.get('hsl',{}));values['hsl'][self.hsl_name.get()]=[v.get() for v in self.hsl_vars]
        edited=color.apply(self._preview_rgb,values,self._preview_skin,self._preview_document)
        if any(layer.get('color_process',1)==2 for layer in self.region_layers):
            from local_develop import apply
            layers=[]
            for layer in self.region_layers:
                item=dict(layer,mask=cv2.resize(layer['mask'].astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0,parameters=dict(layer['parameters']))
                item['parameters']['feather']*=factor;item['parameters']['expand']*=factor;layers.append(item)
            edited=apply(edited,layers,self._preview_rgb)
        from develop_output import preview
        self._preview_frame=preview(edited,self.workflow_extensions.get('output',{}))
        self.status.set('调色预览 · 松开后后台更新完整图像');self.draw()
    def color_preview_display(self,bounds,size,localcut):
        from PIL import Image
        a,b,c,d=bounds;pw,ph=size;h,w=self.document.rgb.shape[:2];ph0,pw0=self._preview_frame.shape[:2]
        x,y=np.meshgrid(a+(np.arange(pw,dtype=np.float32)+.5)*(c-a)/pw-.5,b+(np.arange(ph,dtype=np.float32)+.5)*(d-b)/ph-.5)
        if self.reshape_changed or self.photo_body_changed or self.liquify_active():
            q=self.original_points(np.stack((x,y),axis=2).reshape(-1,2)).reshape(ph,pw,2);mx,my=q[:,:,0],q[:,:,1]
        else:mx,my=x,y
        rgb=cv2.remap(self._preview_frame,(mx+.5)*pw0/w-.5,(my+.5)*ph0/h-.5,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        cut=int(round(localcut*pw/(c-a)))
        if cut:rgb[:,:cut]=cv2.remap(self.session.original,x[:,:cut],y[:,:cut],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        return Image.fromarray(rgb)
