"""Photo-first body geometry with existing undo, compare and recipe controls."""
import tkinter as tk
from tkinter import ttk
from dark_ui import Section
from live_body import BODY_KEYS
import photo_body

class PhotoBodyUI:
    def init_photo_body(self):
        self.photo_body_cache={};self.photo_body_changed=False;self.photo_body_message='身体美型已关闭。';self.photo_body_note=tk.StringVar(value='照片模式：首次调整识别人体，后续复用缓存。')
    def build_photo_body_panel(self,panel):
        section=Section(panel,'自动身体美型 · 照片',opened=True);self.photo_body_panel=section
        ttk.Label(section.body,text='单人照片 · 人物与衣物共同调整；脚部不完整时跳过瘦腿/拉腿。',style='Muted.TLabel',wraplength=275).pack(fill='x',pady=4)
        from feature_catalog import BODY_SHAPE
        for key,label,lo,hi in BODY_SHAPE:self.slider(section.body,label,getattr(self,key),lo,hi,self.refresh)
        self.button(section.body,'重新识别人体',lambda:self.prepare_photo_body(force=True))
        ttk.Label(section.body,textvariable=self.photo_body_note,style='Muted.TLabel',wraplength=275).pack(fill='x',pady=6)
        ttk.Label(section.body,text='自动保护头脸和背景线条，强度过大时会减弱。附近背景仍可能弯曲；不使用AI补画。',style='Muted.TLabel',wraplength=275).pack(fill='x',pady=4)
    def photo_body_values(self):return {k:getattr(self,k).get() for k in BODY_KEYS}
    def photo_body_requested(self):return self.session is not None and photo_body.active(self.face_settings,self.photo_body_values())
    def prepare_photo_body(self,force=False):
        if not self.session or self.busy:return
        session=self.session;self.sync_person_values();self.commit_edit('身体美型参数')
        def job():
            self.progress('AI 正在识别人体关键点和衣物轮廓…')
            return photo_body.analyze(session,self.cancel)
        def ready(analysis):
            if self.session is not session:return
            self.photo_body_cache={'analysis':analysis,'fields':{}}
            self.parameter_apply(self.refresh);self.record('照片人体识别');self.update_recent()
        self.work(job,ready)
    def mask_for_display(self,mask,bounds,localcut=0):
        if not getattr(self,'photo_body_changed',False):return super().mask_for_display(mask,bounds,localcut)
        import face_reshape,liquify,cv2,numpy as np
        h,w=mask.shape;a,b,c,d=bounds
        source=face_reshape.display_mask(mask,self.reshape_cache,self.face_settings,(0,0,w,h))
        source=photo_body.display_mask(source,self.photo_body_cache)
        if self.liquify_active():
            x,y,_=liquify.maps(self.liquify_state,bounds)
            result=cv2.remap(source.astype(np.uint8),x,y,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)>0
        else:result=source[b:d,a:c]
        if localcut:result=result.copy();result[:,:localcut]=mask[b:d,a:a+localcut]
        return result
