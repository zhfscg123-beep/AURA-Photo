"""Per-person light/makeup/recolor and explicitly selected background/fabric repair."""
import uuid,tkinter as tk
from tkinter import ttk,messagebox
import cv2,numpy as np
from dark_ui import Section
from creative_regions import regions
from region_masks import LOCAL_DEFAULTS,MAX_LAYERS
import creative_portrait as ops,effect_controls as effects
from relight_ui import RelightUI

class CreativeSceneUI(RelightUI):
    def init_creative_scene(self):
        self.scene_vars={k:tk.DoubleVar(value=default) for k,_,_,_,default in ops.CONTROLS}
        self.scene_rgb={k:[tk.DoubleVar(value=v) for v in default] for k,default in ops.COLORS.items()}
        self.background_vars={k:tk.DoubleVar(value=0) for k,_,_,_ in ops.BACKGROUND}
        self.clean_target=tk.StringVar(value='背景');self.clean_radius=tk.DoubleVar(value=18);self.clean_overlay=tk.BooleanVar(value=True)
        self.loading_scene=False;self.clean_note=tk.StringVar(value='涂抹选区后执行 AI 清理')
        self.init_relight_ui()
    def build_creative_scene_panel(self,panel):
        self.build_relight_panel(panel)
        fabric=Section(panel,'衣物整理 · 当前人物',opened=False);self.fabric_panel=fabric
        for k,label,lo,hi,_ in ops.CONTROLS[5:8]:self.slider(fabric.body,label,self.scene_vars[k],lo,hi,self.scene_changed)
        self.button(fabric.body,'当前蒙版作为衣物范围',lambda:self.bind_scene_mask('clothes_layer'))
        ttk.Label(fabric.body,text='细褶皱使用保留高频纹理的浅色差处理；复杂图案、大折痕请选区AI清理并检查。需要保留的地方可在效果管理中擦回衣物效果。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        makeup=Section(panel,'轻妆与发色 · 当前人物',opened=False);self.makeup_panel=makeup
        for strength,title,color in [('lip','唇色','lip_rgb'),('blush','腮红','blush_rgb'),('hair','发色','hair_rgb')]:
            sub=Section(makeup.body,title,opened=False);self.slider(sub.body,'强度',self.scene_vars[strength],0,100,self.scene_changed)
            self.build_scene_palette(sub.body,color,title)
            advanced=Section(sub.body,'RGB数值（精确输入）',opened=False)
            for var,channel in zip(self.scene_rgb[color],'RGB'):self.slider(advanced.body,'颜色 '+channel,var,0,255,self.scene_changed)
        ttk.Label(makeup.body,text='默认关闭，按人物独立；使用部位蒙版调整颜色与少量明亮度，保留原纹理，不生成发型或五官。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        clothing=Section(panel,'衣物改色 · 当前人物',opened=False);self.clothes_color_panel=clothing
        self.slider(clothing.body,'改色强度',self.scene_vars['clothes_color'],0,100,self.scene_changed)
        self.build_scene_palette(clothing.body,'clothes_rgb','衣物颜色')
        for var,channel in zip(self.scene_rgb['clothes_rgb'],'RGB'):self.slider(clothing.body,'衣物颜色 '+channel,var,0,255,self.scene_changed)
        ttk.Label(clothing.body,text='只改变当前人物衣物颜色；衣物褶皱整理在同一模块，选区AI清理在“修复”模块。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        bg=Section(panel,'背景精修',opened=False);self.background_panel=bg
        for k,title,lo,hi in ops.BACKGROUND:self.slider(bg.body,title,self.background_vars[k],lo,hi,self.background_changed,decimals=2 if k=='exposure' else 0)
        self.button(bg.body,'查看 / 编辑背景范围',self.show_background_mask)
        self.button(bg.body,'当前蒙版作为背景范围',lambda:self.bind_scene_mask('background_layer'))
        ttk.Label(bg.body,text='先查看背景范围并修正遗漏，再调整曝光、色温或均匀柔化。主体与背景分别处理。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        clean=Section(panel,'衣物与背景 · 选区AI清理',opened=False);self.clean_panel=clean
        c=ttk.Combobox(clean.body,textvariable=self.clean_target,values=['背景','衣物'],state='readonly');c.pack(fill='x');self.controls.append(c)
        self.controls.append(self.slider(clean.body,'选区画笔半径',self.clean_radius,1,300,self.draw_tool_cursor,mutating=False))
        self.mode_button(clean.body,'涂抹需要清理的区域','creative_clean')
        self.button(clean.body,'AI 清理所选区域',self.run_scene_clean)
        self.button(clean.body,'清除待处理选区',self.clear_clean_selection)
        ttk.Checkbutton(clean.body,text='显示待处理选区',variable=self.clean_overlay,command=self.draw).pack(anchor='w',pady=4)
        ttk.Label(clean.body,textvariable=self.clean_note,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
    def scene_person(self):return self.workflow_extensions.setdefault('people',{}).setdefault(str(self.active_face),{})
    def build_scene_palette(self,body,key,title):
        from color_widgets import rgb_hex
        row=ttk.Frame(body);row.pack(fill='x',pady=6)
        chip=tk.Button(row,text='颜色 '+rgb_hex([v.get() for v in self.scene_rgb[key]]),relief='flat',command=lambda:self.pick_scene_color(key,title));chip.pack(fill='x')
        def update(*_):
            rgb=[v.get() for v in self.scene_rgb[key]];chip.configure(bg=rgb_hex(rgb),fg='white' if sum(rgb)<420 else '#202b3c',text='选择颜色  '+rgb_hex(rgb))
        for var in self.scene_rgb[key]:var.trace_add('write',update)
        update()
    def pick_scene_color(self,key,title):
        if self.busy:return
        from color_widgets import ColorPalette
        def apply(rgb):
            self.commit_edit('选择颜色前')
            for var,value in zip(self.scene_rgb[key],rgb):var.set(value)
            self.parameter_apply(self.scene_changed)
        self.color_palette=ColorPalette(self.root,[v.get() for v in self.scene_rgb[key]],apply,title)
    def scene_changed(self):
        if self.loading_scene or self.busy or not self.session or not self.session.faces:return
        item=self.scene_person();item.update({k:v.get() for k,v in self.scene_vars.items()});item.update({k:[v.get() for v in variables] for k,variables in self.scene_rgb.items()})
        item['box']=list(self.session.faces[self.active_face].box);ops.person_values(item);self.refresh();self.record({'美颜':'人像补光参数','妆发':'妆发参数','衣物':'衣物参数'}.get(getattr(self,'active_category',None),'当前人物参数'))
    def background_changed(self):
        if self.loading_scene or self.busy:return
        self.workflow_extensions.setdefault('background',{}).update({k:v.get() for k,v in self.background_vars.items()});self.refresh();self.record('背景精修参数')
    def sync_scene_ui(self):
        if not hasattr(self,'scene_vars'):return
        self.loading_scene=True
        try:
            data=ops.person_values(self.workflow_extensions.get('people',{}).get(str(self.active_face),{}))
            for k,var in self.scene_vars.items():var.set(data[k])
            for k,variables in self.scene_rgb.items():
                for var,value in zip(variables,data[k]):var.set(value)
            bg=self.workflow_extensions.get('background',{})
            for k,var in self.background_vars.items():var.set(bg.get(k,0))
        finally:self.loading_scene=False
        self.sync_relight_ui()
    def bind_scene_mask(self,key):
        if not 0<=self.active_layer<len(self.region_layers):self.status.set('请先生成或选择部位蒙版。');return
        layer=self.region_layers[self.active_layer];layer.setdefault('id',uuid.uuid4().hex)
        if key=='clothes_layer':self.scene_person()[key]=layer['id']
        else:self.workflow_extensions.setdefault('background',{})[key]=layer['id']
        self.refresh();self.record('指定 '+layer['name']+' 为创作范围')
    def background_mask(self,data):return ops.scope(self.workflow_extensions.get('background',{}),'background_layer',self.region_layers,data['background'])
    def clothes_mask(self,data):
        if not self.session.faces:return np.zeros(self.session.original.shape[:2],bool)
        p=self.scene_person();mask=ops.scope(p,'clothes_layer',self.region_layers,data['people'][self.active_face]['clothes'])
        owner=getattr(self.session,'person_owner',None)
        if isinstance(owner,np.ndarray):mask=mask&((owner==0)|(owner==self.active_face+1))
        return mask
    def show_background_mask(self):
        if not self.session or self.busy:return
        if len(self.region_layers)>=MAX_LAYERS:self.status.set('蒙版数量已达上限。');return
        mask=self.background_mask(regions(self.session,self.region_layers));ident=uuid.uuid4().hex
        self.region_layers.append(dict(name='背景精修范围',id=ident,mask=mask.copy(),parameters=dict(LOCAL_DEFAULTS),enabled=True));self.active_layer=len(self.region_layers)-1
        self.workflow_extensions.setdefault('background',{})['background_layer']=ident;self.mask_overlay.set(True);self.overlay.set(False);self.sync_layers();self.select_category('蒙版');self.draw();self.record('检查背景范围')
    def clean_key(self):return 'clean-background' if self.clean_target.get()=='背景' else 'clean-clothes-'+str(self.active_face)
    def start_clean_paint(self,event,erase=False):
        if self.shape_pending() or self.form_changed is not None and self.form_changed.any():self.status.set('请完成面部形变并关闭实验身体形变后选区。');return
        key='select-'+self.clean_key();mask=self.workflow_extensions.setdefault('masks',{}).setdefault(key,np.zeros(self.document.rgb.shape[:2],bool));p=self.original_point(self.point(event))
        self.commit_edit('创作选区前');self.drag=dict(mode='clean_select',key=key,last=p,r=self.clean_radius.get(),erase=not erase)
        effects.paint(mask,p,p,self.drag['r'],not erase);self.draw()
    def update_clean_paint(self,p):
        d=self.drag;q=self.original_point(p);effects.paint(self.workflow_extensions['masks'][d['key']],d['last'],q,d['r'],d['erase']);d['last']=q;self.draw()
    def finish_clean_paint(self):self.drag=None;self.record('绘制创作清理选区');self.draw()
    def clear_clean_selection(self):
        self.workflow_extensions.setdefault('masks',{}).pop('select-'+self.clean_key(),None);self.draw();self.record('清除待处理清理选区')
    def run_scene_clean(self):
        if self.busy or self.creative_input is None:return
        key=self.clean_key();mask=self.workflow_extensions.get('masks',{}).get('select-'+key)
        if mask is None or not mask.any():self.status.set('请先涂抹需要清理的区域。');return
        data=regions(self.session,self.region_layers);allowed=self.background_mask(data) if key=='clean-background' else self.clothes_mask(data)
        selected=mask&allowed
        if not selected.any():self.status.set('所选区域不在已确认的目标范围。请先检查或指定背景/衣物蒙版。');return
        base=self.creative_input.copy();current,_=ops.apply_clean(base,self.workflow_extensions,key,100,allowed)
        old=self.workflow_extensions.get('masks',{}).get('apply-'+key,np.zeros_like(selected));combined=old|selected
        box=ops.roi(combined);a,b,c,d=box
        if (c-a)*(d-b)*12>512*1024**2:self.status.set('选区跨距过大，请缩小范围或分图清理。');return
        self.commit_edit('AI创作清理前')
        def job():
            from ai_engine import inpaint_selected
            output,info=inpaint_selected(np.clip(current,0,255).astype(np.uint8),selected,self.progress,self.cancel,precision=True)
            result=current.copy();result[selected]=output[selected];delta=(result[b:d,a:c]-base[b:d,a:c]).astype(np.float32)
            delta[~combined[b:d,a:c]]=0;return delta,ops.source_hash(base,combined,box),info
        def ready(result):
            delta,signature,info=result;self.workflow_extensions.setdefault('assets',{})[key]=delta
            self.workflow_extensions.setdefault('clean_records',{})[key]=dict(box=list(box),source_hash=signature)
            self.workflow_extensions.setdefault('masks',{})['apply-'+key]=combined;self.workflow_extensions['masks']['select-'+key]=np.zeros_like(selected)
            if key=='clean-background':self.workflow_extensions.setdefault('background',{})['clean']=100
            else:self.scene_person()['clothes_clean']=100
            self.sync_scene_ui();self.refresh();self.record('AI 清理 '+self.clean_target.get());self.clean_note.set('已清理；可调强度或在效果管理中擦回。')
        self.work(job,ready)
    def apply_scene(self,rgb):
        ext=self.workflow_extensions
        if not ext.get('people') and not ext.get('background'):return rgb
        data=regions(self.session,self.region_layers);out=rgb
        bg=ext.get('background',{});bmask=self.background_mask(data);before=self.effect_before('background',out)
        out,stale=ops.apply_clean(out,ext,'clean-background',bg.get('clean',0),bmask);out=ops.background(out,bmask,bg);out=self.effect_after('background',before,out)
        for fi,f in enumerate(self.session.faces):
            item=ext.get('people',{}).get(str(fi),{});values=ops.person_values(item);m=data['people'][fi]
            cloth=ops.scope(item,'clothes_layer',self.region_layers,m['clothes']).copy();owner=getattr(self.session,'person_owner',None)
            if isinstance(owner,np.ndarray):cloth&=(owner==0)|(owner==fi+1)
            before=self.effect_before('clothes',out);out,s=ops.apply_clean(out,ext,'clean-clothes-'+str(fi),values['clothes_clean'],cloth);stale|=s
            out=ops.fabric(out,cloth,values);out=ops.recolor(out,cloth,values['clothes_rgb'],values['clothes_color']);out=self.effect_after('clothes',before,out)
            before=self.effect_before('light',out)
            if values['relight'] is not None:
                import relight_engine
                out=relight_engine.apply(out,self.session,fi,m,values['relight'],getattr(self,'light_note',None).set if hasattr(self,'light_note') else None)
            elif values['light']:
                out=ops.legacy_light(out,m['light'],values)
            out=self.effect_after('light',before,out)
            before=self.effect_before('makeup',out);out=ops.recolor(out,m['lips'],values['lip_rgb'],values['lip']);out=ops.blush(out,f,m['face'],values['blush_rgb'],values['blush']);out=ops.recolor(out,m['hair'],values['hair_rgb'],values['hair'],True);out=self.effect_after('makeup',before,out)
        self.clean_note.set('修复来源已改变，请重新应用 AI 清理。' if stale else '涂抹选区后执行 AI 清理；已有结果可调强度与擦回。')
        return out
    def creative_render(self,rgb):
        self.creative_input=rgb;before=self.effect_before('creative',rgb)
        out=self.apply_scene(rgb);self.color_input=out;out=self.apply_creative_color(out)
        out=self.effect_after('creative',before,out);self.creative_output=out;return out
    def creative_is_active(self):
        import point_curves
        data=self.workflow_extensions
        color=data.get('color',{});values=color.get('values',{})
        from creative_color import DEFAULTS
        if any(v!=DEFAULTS.get(k,0) for k,v in values.items() if k not in ('skin_protect','shadow_hue','midtone_hue','highlight_hue','global_hue')) or color.get('point_colors') or color.get('wb_sample') or any(color.get('bw_mix',{}).values()) or any(color.get('curve',[])) or any(any(v) for v in color.get('hsl',{}).values()) or any(point_curves.active(p) for p in color.get('points',{}).values()):return True
        if any(data.get('background',{}).get(k,0) for k,_,_,_ in ops.BACKGROUND):return True
        if data.get('reference',{}).get('color') or data.get('reference',{}).get('tone'):return True
        from relight_settings import active
        return any(any(values.get(k,0) for k in ('light','fabric','clothes_clean','lip','blush','hair','clothes_color')) or values.get('relight') is not None and active(values['relight']) for values in data.get('people',{}).values())
    def decorate_display(self,rgb,bounds,localcut):
        super().decorate_display(rgb,bounds,localcut)
        if self.mode.get()=='creative_clean' and self.clean_overlay.get():
            mask=self.workflow_extensions.get('masks',{}).get('select-'+self.clean_key())
            if mask is not None:
                shown=self.mask_for_display(mask,bounds,localcut).copy();shown[:,:localcut]=False;rgb[shown]=np.rint(rgb[shown]*.65+np.array([235,100,80])*.35).astype(np.uint8)
    def place_light(self,event):
        return self.place_relight(event)
        p=self.original_point(self.point(event));h,w=self.document.rgb.shape[:2]
        self.scene_vars['light_x'].set(np.clip(p[0]/w*100,0,100));self.scene_vars['light_y'].set(np.clip(p[1]/h*100,0,100));self.parameter_apply(self.scene_changed);self.select_tool('pan');self.status.set('光源已放置，已返回浏览；可在本面板调节补光强度。')
