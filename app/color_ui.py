import tkinter as tk
from tkinter import ttk
import numpy as np
from dark_ui import Section
from skin_color import COLORS
from feature_catalog import COLOR_FACE
class ColorUI:
 def init_color(self):self.sample_label=tk.StringVar(value='尚未取样 · 强度默认0')
 def build_color_panel(self,panel):
  self.color_panel=Section(panel,'肤色取样 / 八种肤色 · 当前人像',opened=False);body=self.color_panel.body
  grid=ttk.Frame(body);grid.pack(fill='x',pady=5)
  for i,(label,color) in enumerate(COLORS):
   b=tk.Button(grid,text=label,bg=color,fg='#20242a',width=7,relief='flat',command=lambda n=i+1:self.choose_color(n));b.grid(row=i//4,column=i%4,padx=2,pady=2);self.controls.append(b)
  self.button(body,'取消肤色方案',lambda:self.choose_color(0))
  for k,label,lo,hi in COLOR_FACE:self.slider(body,label,getattr(self,k),lo,hi,self.refresh)
  self.mode_button(body,'吸管取样 · 点击照片','sample')
  section=Section(body,'取样色 RGB · 可手动输入',opened=False)
  for channel in 'rgb':self.slider(section.body,'取样 '+channel.upper(),getattr(self,'sample_'+channel),0,255,self.refresh)
  ttk.Label(body,textvariable=self.sample_label,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
  ttk.Label(body,text='取样读取原显影图附近像素的中位色，分别调面部/身体强度。选颜色和取样均不自动增加强度。身体参数在身体组，调整后直接应用于当前人像已确认的身体皮肤。匹配只作有限度的色调及亮度平移，保留明暗纹理。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
 def choose_color(self,n):
  if not self.session or self.busy:return
  self.commit_edit('选择肤色前');self.skin_choice.set(n);self.refresh();self.record('选择肤色方案');self.sync_color_ui()
 def sync_color_ui(self):
  if not hasattr(self,'sample_label'):return
  n=int(round(self.skin_choice.get()));color=COLORS[n-1][0] if 1<=n<=8 else '未选择'
  rgb=[round(getattr(self,'sample_'+c).get()) for c in 'rgb']
  self.sample_label.set(f'方案：{color} / 取样 RGB {rgb}\n面部 {self.sample_face.get():.0f} · 身体 {self.sample_body.get():.0f}')
 def take_skin_sample(self,event):
  x,y=self.point(event);h,w=self.output.shape[:2];x,y=round(x),round(y)
  if not (0<=x<w and 0<=y<h):return
  self.commit_edit('取样前');src=self.document.base_float();value=np.median(src[max(0,y-2):min(h,y+3),max(0,x-2):min(w,x+3)].reshape(-1,3),axis=0)
  for c,v in zip('rgb',value):getattr(self,'sample_'+c).set(float(v))
  self.refresh();self.record('原显影肤色取样');self.sync_color_ui();self.select_tool('pan')
