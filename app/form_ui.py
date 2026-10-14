import copy
from tkinter import ttk
from dark_ui import Section
from feature_catalog import FORM
from body_shape import prepare_forms
class FormUI:
 def build_form_panel(self,panel):
  self.form_panel=Section(panel,'双下巴 / 腋下局部形变 · 实验',opened=False);body=self.form_panel.body
  for k,label,lo,hi in FORM:
   if k!='double_chin_shadow':self.slider(body,label,getattr(self,k),lo,hi,self.refresh)
  self.button(body,'AI 补全空出区域并应用',self.prepare_form_controls,accent=True)
  ttk.Label(body,text='按人物独立，默认0。仅移动当前人物皮肤前景，背景不参与拉伸，空出区域用LaMa补全。腋下需有可信姿态及露出皮肤，否则不应用。暂无双下巴/腋下真实对应样片，质量待验证；先轻度尝试。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
 def prepare_form_controls(self):
  if not self.session or self.busy:return
  self.sync_person_values();self.commit_edit('形变参数');working=copy.copy(self.session);settings=copy.deepcopy(self.face_settings);layers=copy.deepcopy(self.region_layers);source=self.document.base_float()
  def job():
   cache=prepare_forms(source,working,settings,layers,self.progress,self.cancel)
   return cache,{k:getattr(working,k) for k in ('body_owner','body_region','person_owner','person_landmarks','body_assignment','form_notes','form_unavailable') if hasattr(working,k)}
  def ready(result):
   cache,attrs=result
   for k,v in attrs.items():setattr(self.session,k,v)
   self.form_cache=cache;self.refresh();self.record('AI 局部形变补全')
   if getattr(self.session,'form_notes',[]):self.status.set('；'.join(self.session.form_notes))
  self.work(job,ready)
