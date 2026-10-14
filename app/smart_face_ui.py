"""Per-person face-aware controls; native numeric input, cached calibration."""
import tkinter as tk
from tkinter import ttk
from dark_ui import Section
from reshape_settings import SMART,SMART_KEYS,RESHAPE

class SmartFaceUI:
    def init_smart_face(self):self.smart_eye_link=tk.BooleanVar(value=True)
    def build_smart_face_controls(self,body):
        section=Section(body,'脸部智能 · 当前人物',opened=False);self.smart_face_panel=section
        content=section.body
        self.smart_face_controls=[]
        label=ttk.Label(content,text='先选上方人物。参数按人物独立；默认 0。眼睛左右按人物自身区分。可输入数值，Enter 应用。\n先调整智能参数，再用画笔细修与冻结保护。',style='Muted.TLabel',wraplength=270)
        label.pack(anchor='w',pady=5)
        eyes=Section(content,'眼睛',opened=True)
        linked=ttk.Checkbutton(eyes.body,text='左右眼联动',variable=self.smart_eye_link)
        linked.pack(anchor='w',pady=4);self.controls.append(linked);self.smart_face_controls.append(linked)
        groups=[(eyes,SMART[:9]),(Section(content,'鼻子',opened=False),SMART[9:11]),
                (Section(content,'嘴唇与嘴角',opened=False),SMART[11:16]),
                (Section(content,'脸型与下颌',opened=False),SMART[16:]+RESHAPE[2:])]
        self.smart_face_groups=[s for s,_ in groups]
        for group,items in groups:
            for key,title,lo,hi in items:
                control=self.slider(group.body,title,getattr(self,key),lo,hi,
                    lambda key=key:self.change_smart_face_parameter(key))
                self.smart_face_controls.append(control)
        self.smart_face_controls.append(self.button(content,'恢复智能五官参数',self.reset_smart_face))
        self.smart_face_controls.append(self.button(content,'重新识别 / 校准人物',lambda:self.prepare_reshape_controls(force=True)))
        self.sync_smart_face_ui()
    def sync_smart_face_ui(self):
        if not hasattr(self,'smart_face_controls'):return
        enabled=self.session is not None and bool(self.face_settings) and not self.busy
        # Smart parameters precede manual geometry. Avoid moving an already
        # frozen boundary or rebasing existing manual strokes unexpectedly.
        blocked=self.liquify_state is not None and (self.liquify_state['freeze'].any() or self.liquify_state['flow'].any())
        for control in self.smart_face_controls:control.configure(state='normal' if enabled and not blocked else 'disabled')
        for control in getattr(self,'reshape_controls',[]):control.configure(state='normal' if enabled and not blocked else 'disabled')
        for card in getattr(self,'reshape_cards',{}).values():card.configure(state='normal' if enabled and not blocked else 'disabled')
    def change_smart_face_parameter(self,key):
        if self.loading_face:return
        if self.liquify_state is not None and (self.liquify_state['flow'].any() or self.liquify_state['freeze'].any()):
            self.load_person_controls();self.status.set('请先恢复画笔形变并清除冻结保护，再调整智能参数。');return
        if self.smart_eye_link.get() and key.startswith('fs_eye_'):
            if '_left_' in key:partner=key.replace('_left_','_right_')
            elif '_right_' in key:partner=key.replace('_right_','_left_')
            else:partner=None
            if partner:getattr(self,partner).set(getattr(self,key).get())
        if key.startswith('rs_'):self.change_shape_parameter(key);return
        self.sync_reshape_ui();self.refresh();self.record('脸部智能参数')
    def reset_smart_face(self):
        if self.busy or not self.face_settings:return
        if self.liquify_state is not None and (self.liquify_state['flow'].any() or self.liquify_state['freeze'].any()):
            self.status.set('已有画笔形变或冻结保护。请先恢复画笔形变并清除保护，再调整智能参数。');return
        self.commit_edit('智能五官恢复前')
        for key in SMART_KEYS:getattr(self,key).set(0)
        self.sync_reshape_ui();self.refresh();self.record('恢复智能五官参数')
