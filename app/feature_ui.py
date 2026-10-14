"""Face detail controls, candidate preview and explicit cached AI processing."""
import copy,tkinter as tk
from tkinter import ttk
import numpy as np
from dark_ui import Section
from feature_catalog import FACE_REPAIR,FACE_DETAILS,TYPE_LABELS,BODY
from region_masks import LOCAL_DEFAULTS,MAX_LAYERS
from face_details import feature_mask,prepare_face_repairs
from body_details import body_feature_mask,prepare_body

class FeatureUI:
    def init_features(self):
        self.detail_type=tk.StringVar(value=next(iter(TYPE_LABELS.values())))
        self.body_type=tk.StringVar(value=TYPE_LABELS['body_skin'])
    def build_features_panel(self,panel):
        section=Section(panel,'面部瑕疵细分 · 当前人像',opened=False);self.face_detail_panel=section
        ttk.Label(section.body,text='AI瑕疵候选按颜色与尺度细分，并非痣/斑/汗珠专用分类网络。先预览可擦回误选；新增强度默认0。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=4)
        for k,label,lo,hi in FACE_REPAIR:self.slider(section.body,label,getattr(self,k),lo,hi,self.refresh)
        protections=Section(section.body,'修复保护与质感',opened=False)
        for k,label,lo,hi in FACE_DETAILS:
            if k in ('texture_keep','beard_protect','makeup_protect'):self.slider(protections.body,label,getattr(self,k),lo,hi,self.refresh)
        combo=ttk.Combobox(section.body,textvariable=self.detail_type,values=[TYPE_LABELS[k] for k,_,_,_ in FACE_REPAIR],state='readonly');combo.pack(fill='x',pady=6);self.controls.append(combo)
        combo._aura_search_name='面部祛瑕类型'
        self.button(section.body,'重新生成该类型预览蒙版',self.preview_detail)
        self.button(section.body,'AI 应用面部细节修复',self.prepare_details,accent=True)
        ttk.Label(section.body,text='到“蒙版”选择对应范围，用添加/减去画笔修改。重新生成会覆盖该类型选区，可撤销。调整强度无需重跑AI；扩大选区后需再次应用。自然鼻孔暗部不自动修复。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
    def build_body_panel(self,panel):
        section=Section(panel,'身体皮肤与瑕疵 · 当前人像',opened=False);self.body_panel=section
        ttk.Label(section.body,text='身体专项在基础美颜之上追加，全部默认0；基础磨皮与美白仍覆盖身体皮肤。此处磨皮、美白与肤色参数直接应用；祛瑕、深色点及纹身需点击下方 AI 处理。自动范围排除衣服，补选保护其他人物。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=4)
        self.build_beauty_mask_controls(section.body,scope='body')
        for k,label,lo,hi in BODY:
            if k!='body_redness':self.slider(section.body,label,getattr(self,k),lo,hi,self.refresh)
        combo=ttk.Combobox(section.body,textvariable=self.body_type,values=[v for k,v in TYPE_LABELS.items() if k.startswith('body_')],state='readonly');combo.pack(fill='x',pady=6);self.controls.append(combo)
        combo._aura_search_name='身体美颜范围 / 瑕疵类型'
        self.button(section.body,'重新生成身体类型 / 范围蒙版',lambda:self.preview_detail(body=True))
        self.button(section.body,'AI 应用身体祛瑕 / 修复',self.prepare_body_controls,accent=True)
        ttk.Label(section.body,text='纹身候选使用颜色/对比规则，需预览与画笔确认，再由LaMa补全。妊娠纹、锁骨采用皮肤范围内细纹/姿态光影处理，暂无真实对应样片，标为实验。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
    def preview_detail(self,body=False):
        if not self.session or self.busy or not self.session.faces:return
        key=next((k for k,label in TYPE_LABELS.items() if label==(self.body_type.get() if body else self.detail_type.get())),None)
        if key is None:return
        fi=self.active_face;session=self.session
        found=next((i for i,l in enumerate(self.region_layers) if l.get('feature_key')==key and l.get('person_index')==fi),None)
        if found is None and len(self.region_layers)>=MAX_LAYERS:self.status.set('蒙版数量已达上限。');return
        self.commit_edit('生成细节蒙版前')
        def job():
            if key.startswith('body_'):return body_feature_mask(session,fi,key,[],self.progress,self.cancel)
            local=feature_mask(session,fi,key,[]);f=session.faces[fi];a,b,c,d=f.box
            mask=np.zeros(session.original.shape[:2],bool);mask[b:d,a:c]=local;return mask
        def ready(mask):
            layer=dict(name=f'人像 {fi+1} {TYPE_LABELS[key]}',mask=mask,parameters=dict(LOCAL_DEFAULTS),enabled=True,feature_key=key,person_index=fi)
            if found is None:self.region_layers.append(layer);self.active_layer=len(self.region_layers)-1
            else:self.region_layers[found]=layer;self.active_layer=found
            self.mask_overlay.set(True);self.overlay.set(False);self.sync_layers();self.refresh();self.record('生成细节候选蒙版')
            if not mask.any():self.status.set(self.status.get()+' / 此类型未找到候选，可手动补选。')
        self.work(job,ready)
    def prepare_details(self):
        if not self.session or self.busy:return
        self.sync_person_values();self.commit_edit('面部细节参数')
        session=self.session;settings=copy.deepcopy(self.face_settings);layers=copy.deepcopy(self.region_layers)
        def ready(cache):session.detail_cache=cache;self.refresh();self.record('AI 面部细节修复')
        self.work(lambda:prepare_face_repairs(session,settings,layers,self.progress,self.cancel),ready)
    def prepare_body_controls(self):
        if not self.session or self.busy:return
        self.sync_person_values();self.commit_edit('身体参数')
        working=copy.copy(self.session);working.body_parts=copy.deepcopy(getattr(self.session,'body_parts',{}))
        for name in ('body_owner','body_region','person_owner','person_semantics','person_landmarks','body_assignment'):
            if hasattr(working,name):setattr(working,name,copy.deepcopy(getattr(working,name)))
        settings=copy.deepcopy(self.face_settings);layers=copy.deepcopy(self.region_layers)
        def job():
            prepare_body(working,settings,layers,self.progress,self.cancel)
            return {k:getattr(working,k) for k in ('body_parts','body_owner','body_region','person_owner','person_semantics','person_landmarks','body_assignment','body_revision','ownership_revision','head_skin_revision') if hasattr(working,k)}
        def ready(data):
            for k,v in data.items():setattr(self.session,k,v)
            self.refresh();self.record('AI 身体处理')
        self.work(job,ready)
