"""Editable reference shapes, per-person controls, native keyboard/DPI support."""
import copy,tkinter as tk
from tkinter import ttk
import numpy as np
from dark_ui import Section,COLORS,ParameterScale
from dpi_support import dp,ui_font,scale_canvas_art
from reshape_settings import RESHAPE,KEYS,CLASSIC_KEYS,SMART_KEYS,PRESETS,preset_name,active
import face_reshape

class FacePresetButton(tk.Canvas):
    def __init__(self,parent,label,command):
        super().__init__(parent,height=100,width=66,bg=COLORS['panel'],highlightthickness=0,takefocus=1,cursor='hand2')
        self.label=label;self.command=command;self.selected=False;self.state='normal';self.hovered=False
        self.bind('<Button-1>',self.activate);self.bind('<Return>',self.activate);self.bind('<space>',self.activate)
        self.bind('<Enter>',lambda e:self.hover(True));self.bind('<Leave>',lambda e:self.hover(False))
        for event in ('<Configure>','<FocusIn>','<FocusOut>'):self.bind(event,lambda e:self.paint())
    def hover(self,value):self.hovered=value;self.paint()
    def activate(self,event=None):
        if self.state!='disabled':self.focus_set();self.command()
        return 'break'
    def configure(self,cnf=None,**kw):
        if 'state' in kw:self.state=kw.pop('state')
        result=super().configure(cnf,**kw)
        if hasattr(self,'selected'):self.paint()
        return result
    config=configure
    def paint(self):
        if not self.winfo_exists():return
        self.delete('all');scale=getattr(self.winfo_toplevel(),'_ui_scale',1)
        w=max(1,self.winfo_width())/scale;h=int(self.cget('height'))/scale
        color=COLORS['accent'] if self.selected else COLORS['muted']
        if self.state=='disabled':color='#a7b0bf'
        fill=COLORS['selected'] if self.selected or self.hovered else COLORS['raised']
        self.create_polygon(9,2,w-9,2,w-2,9,w-2,h-9,w-9,h-2,9,h-2,2,h-9,2,9,
            smooth=True,fill=fill,outline=color if self.selected else COLORS['border'],width=1.5 if self.selected else 1)
        self.create_line(3,h-27,w-3,h-27,fill=COLORS['border'])
        cx=w/2;cy=28
        if self.label=='无':
            self.create_oval(cx-11,cy-11,cx+11,cy+11,outline=color,width=1.5)
            self.create_line(cx-8,cy+8,cx+8,cy-8,fill=color,width=1.5)
        else:
            values=PRESETS[self.label];narrow=(values[0]+values[1])/200;length=values[5]/100
            jaw=values[2]/100;chin=values[4]/100
            self.create_line(cx-18,cy-15,cx-18,cy+2,cx-13,cy+14,cx,cy+25,cx+13,cy+14,cx+18,cy+2,cx+18,cy-15,smooth=True,fill='#c3cbd8',dash=(2,2),width=1)
            side=18*(1-narrow*1.2);jaww=13*(1+jaw*1.5);chinw=6*(1+chin*1.6)
            points=[cx-18,cy-15,cx-side,cy+2,cx-jaww,cy+14,cx-chinw,cy+21+length*26,cx,cy+25+length*26,
                cx+chinw,cy+21+length*26,cx+jaww,cy+14,cx+side,cy+2,cx+18,cy-15]
            self.create_line(*points,smooth=True,fill=color,width=1.8,tags='preset_contour')
            self.create_arc(cx-4,cy+11,cx+4,cy+16,start=200,extent=140,style='arc',outline=color,width=1)
            # Direction cues correspond to the actual six preset parameters.
            if self.label in ('自然','圆脸参考'):
                for sign in (-1,1):self.create_line(cx+sign*25,cy+3,cx+sign*(side+3),cy+3,fill=color,arrow='last',arrowshape=(3,4,2),width=1)
            elif self.label in ('利落','方脸参考','V形参考'):
                for sign in (-1,1):self.create_line(cx+sign*22,cy+18,cx+sign*(jaww+3),cy+16,fill=color,arrow='last',arrowshape=(3,4,2),width=1)
            elif self.label=='长脸参考':
                self.create_line(cx,cy+31,cx,cy+25+length*26+4,fill=color,arrow='last',arrowshape=(3,4,2),width=1)
        display={'圆脸参考':'圆脸适用','长脸参考':'长脸适用','方脸参考':'方脸适用','V形参考':'V形参考'}.get(self.label,self.label)
        self.create_text(cx,h-15,text=display,fill=color,font=ui_font(self,9,'bold' if self.selected else 'normal'),tags='preset_label')
        if self.focus_get() is self:self.create_rectangle(3,3,w-3,h-3,outline=COLORS['accent'],dash=(2,2))
        scale_canvas_art(self)

class ReshapeUI:
    def init_reshape(self):
        self.reshape_cache={};self.reshape_changed=False
        self.reshape_link=tk.BooleanVar(value=True);self.reshape_overlay=tk.BooleanVar(value=False)
        self.reshape_choice=tk.StringVar(value='无')
        self.reshape_note=tk.StringVar(value='无 · 保持原有脸型')
    def build_reshape_panel(self,panel):
        section=Section(panel,'面部重塑',opened=True);self.reshape_panel=section;body=section.body
        row=ttk.Frame(body);row.pack(fill='x',pady=(0,6))
        ttk.Label(row,text='参考脸型',style='Muted.TLabel').pack(side='left')
        ttk.Label(row,textvariable=self.reshape_choice,style='Muted.TLabel').pack(side='right')
        self.reshape_cards={}
        names=list(PRESETS)
        for start in (0,4):
            row=ttk.Frame(body);row.pack(fill='x',pady=3)
            for name in names[start:start+4]:
                card=FacePresetButton(row,name,lambda name=name:self.apply_shape_reference(name))
                card.pack(side='left',fill='x',expand=True,padx=3);self.reshape_cards[name]=card;self.controls.append(card)
        for index,card in enumerate(self.reshape_cards.values()):
            for event,step in (('<Left>',-1),('<Right>',1),('<Up>',-4),('<Down>',4)):
                card.bind(event,lambda e,index=index,step=step:self.focus_shape_card(index,step))
        ttk.Label(body,textvariable=self.reshape_note,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(7,4))
        self.reshape_zone_buttons={}
        for zones in (('脸型','光影塑颜','眉弓','眼睛'),('鼻子','嘴唇')):
            row=ttk.Frame(body);row.pack(fill='x',pady=3)
            for zone in zones:
                button=ttk.Button(row,text=zone,width=5,command=lambda zone=zone:self.open_shape_zone(zone))
                button.pack(side='left',padx=3);self.reshape_zone_buttons[zone]=button
        ttk.Label(body,text='虚线是原始轮廓，箭头表示调整方向；示意差异已放大。下方标签快速定位已有控件。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(5,6))
        link=ttk.Checkbutton(body,text='左右联动',variable=self.reshape_link);link.pack(anchor='w',pady=(0,5));self.controls.append(link)
        self.reshape_controls=[]
        for key,title,lo,hi in RESHAPE:
            self.reshape_controls.append(self.slider(body,title,getattr(self,key),lo,hi,lambda key=key:self.change_shape_parameter(key)))
        self.button(body,'重新校准轮廓',lambda:self.prepare_reshape_controls(force=True))
        ttk.Label(body,text='首次使用会定位并复核可见边缘；遮挡处保守处理。调整数值时复用定位，松开滑块或按 Enter 后应用。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=4)
        self.sync_reshape_ui()
    def focus_shape_card(self,index,step):
        cards=list(self.reshape_cards.values());cards[max(0,min(len(cards)-1,index+step))].focus_set();return 'break'
    def open_shape_zone(self,zone):
        if zone=='脸型':
            self.focus_section(self.reshape_panel);target=self.reshape_controls[0].entry
        elif zone in ('光影塑颜','眉弓'):
            self.focus_section(self.volume_panel)
            key='vol_brow' if zone=='眉弓' else 'stereo_features'
            target=next(c.entry for c in self.controls if isinstance(c,ParameterScale) and c.variable is getattr(self,key))
        else:
            section=self.smart_face_groups[{'眼睛':0,'鼻子':1,'嘴唇':2}[zone]]
            self.focus_section(section);target=section.header
        self.root.update_idletasks()
        offset=target.winfo_rooty()-self.settings_panel.winfo_rooty()-dp(self.root,24)
        self.settings_scroll.yview_moveto(max(0,offset)/max(1,self.settings_panel.winfo_height()))
        target.focus_set();self.status.set('已定位：'+zone+(' · 仅调整局部明暗' if zone in ('光影塑颜','眉弓') else ''))
    def sync_reshape_ui(self):
        if not hasattr(self,'reshape_cards'):return
        name=preset_name({k:getattr(self,k).get() for k in KEYS});self.reshape_choice.set(name)
        notes={'无':'保持原有脸型','自然':'轻收脸缘','柔和':'柔化下颌，轻缩脸长','利落':'收窄下颌，轻拉长下巴','圆脸参考':'收窄两侧，轻拉长下巴','长脸参考':'缩短脸长','方脸参考':'收窄下颌','V形参考':'收窄下巴'}
        self.reshape_note.set(name+' · '+notes.get(name,'自定义参数'))
        for label,card in self.reshape_cards.items():card.selected=label==name;card.paint()
    def change_shape_parameter(self,key):
        if self.loading_face:return
        if self.liquify_state is not None and (self.liquify_state['flow'].any() or self.liquify_state['freeze'].any()):
            self.load_person_controls();self.status.set('请先恢复画笔形变并清除冻结保护，再调整脸型。');return
        if self.reshape_link.get():
            partner={'rs_slim_left':'rs_slim_right','rs_slim_right':'rs_slim_left','rs_jaw_left':'rs_jaw_right','rs_jaw_right':'rs_jaw_left'}.get(key)
            if partner:getattr(self,partner).set(getattr(self,key).get())
        self.sync_reshape_ui();self.refresh();self.record('面部重塑参数')
    def apply_shape_reference(self,name):
        if not self.session or not self.face_settings or self.busy:return
        if self.liquify_state is not None and (self.liquify_state['flow'].any() or self.liquify_state['freeze'].any()):
            self.status.set('已有画笔形变或冻结保护，请先恢复画笔形变并清除保护，再调整脸型。');return
        self.commit_edit('面部重塑前')
        for key,value in zip(CLASSIC_KEYS,PRESETS[name]):getattr(self,key).set(value)
        if name=='无':
            for key in SMART_KEYS:getattr(self,key).set(0)
        self.sync_reshape_ui();self.refresh();self.record('参考脸型 · '+name)
    def show_reshape_contour(self):
        if self.reshape_overlay.get() and self.session and self.active_face not in self.reshape_cache:self.prepare_reshape_controls(force=True)
        else:self.draw()
    def prepare_reshape_controls(self,force=False):
        if not self.session or not self.face_settings or self.busy:return
        if force and self.liquify_state is not None and (self.liquify_state['flow'].any() or self.liquify_state['freeze'].any()):
            self.status.set('请先恢复画笔形变并清除冻结保护，再重新校准。');return
        self.sync_person_values();self.commit_edit('面部重塑参数')
        session=self.session;values=copy.deepcopy(self.face_settings);cache=self.reshape_cache;person=self.active_face if force else None
        def ready(result):
            if self.session is session:
                self.reshape_cache=result;self.refresh();self.update_recent()
                if force:self.record('校准面部轮廓')
        self.work(lambda:face_reshape.prepare(session,values,cache,self.progress,self.cancel,person),ready)
    def draw_reshape_contour(self):
        return  # Contours are now shown only for the hovered node-tool group.
        if not self.reshape_overlay.get() or self.active_face not in self.reshape_cache:return
        entry=self.reshape_cache[self.active_face];geometry=entry['geometry'];points=geometry['points']
        if self.active_face<len(self.face_settings) and active(self.face_settings[self.active_face]) and face_reshape.ready(self.reshape_cache,self.face_settings):
            points=entry.get('field',{}).get('target_points',points)
        uncertain=set(geometry['calibration']['occluded_or_uncertain_points'])
        cut=self.size()[0]*self.split.get()/100
        for i in range(32):
            a=self.view.to_canvas(*points[i],self.size());b=self.view.to_canvas(*points[i+1],self.size())
            if a[0]<cut or b[0]<cut:continue
            doubtful=i in uncertain or i+1 in uncertain
            self.canvas.create_line(*a,*b,fill='#cf7a12' if doubtful else COLORS['accent'],width=dp(self.root,1.5),dash=(3,3) if doubtful else (),tags='reshape_contour')
    def mask_for_display(self,mask,bounds,localcut=0):
        a,b,c,d=bounds
        result=face_reshape.display_mask(mask,self.reshape_cache,self.face_settings,bounds)
        if localcut:
            result=result.copy();result[:,:localcut]=mask[b:d,a:a+localcut]
        return result
