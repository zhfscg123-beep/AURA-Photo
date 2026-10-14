from tkinter import ttk
from dark_ui import Section
from feature_catalog import VOLUME
class VolumeUI:
 def build_volume_panel(self,panel):
  self.volume_panel=Section(panel,'光影立体与分区丰盈 · 当前人像',opened=False);body=self.volume_panel.body
  ttk.Label(body,text='基于 AI 皮肤和关键点的局部明暗塑形，保留纹理。光影丰盈不改变面部几何，也不生成新皮肤；全部默认0。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
  for k,label,lo,hi in VOLUME:self.slider(body,label,getattr(self,k),lo,hi,self.refresh,decimals=1 if hi==4 else 0)
  detail=Section(body,'眼袋与下颌光影',opened=False)
  for k,title in [('eye_bags','淡化眼袋光影'),('jaw_enhance','下颌线光影增强'),('double_chin_shadow','双下巴阴影淡化')]:self.slider(detail.body,title,getattr(self,k),0,100,self.refresh)
  ttk.Label(detail.body,text='这些参数只调整明暗，不移动五官、下颌或身体轮廓。几何收紧在“塑形”中。',style='Muted.TLabel',wraplength=270).pack(anchor='w',pady=5)
  ttk.Label(body,text='全脸0–4档；额头、面中、面颊、鼻基底、眼窝、眉弓、下巴、嘴角可单调。两侧眼窝分开，额头/面中/鼻基底/下巴另有平整与提亮。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
