"""LR-style gradient creation in the main image and range-mask refinements."""
import tkinter as tk
from tkinter import ttk,messagebox
import numpy as np
from dark_ui import Section
from region_masks import LOCAL_DEFAULTS,MAX_LAYERS
import color_science as cs

class LocalDevelopUI:
    def init_local_develop(self):
        self.local_range_kind=tk.StringVar(value='无范围限制');self.local_range_operation=tk.StringVar(value='交集')
        self.local_low=tk.DoubleVar(value=0);self.local_high=tk.DoubleVar(value=1);self.local_soft=tk.DoubleVar(value=.1)
        self.local_hue_range=tk.DoubleVar(value=30);self.local_range_note=tk.StringVar(value='选中蒙版后可进一步按颜色或亮度限定范围。')
        self._local_alpha_cache=None
    def fast_local_display(self,bounds,size,localcut):
        import hashlib,json,copy,cv2
        from PIL import Image
        from local_develop import alpha
        layer=self.region_layers[self.active_layer];reference=self.color_input if self.color_input is not None else self.session.original
        key=(id(reference),hashlib.blake2b(layer['mask'].tobytes(),digest_size=12).hexdigest(),hashlib.blake2b(layer['mask_alpha'].tobytes(),digest_size=12).hexdigest() if 'mask_alpha' in layer else None,json.dumps({k:layer.get(k) for k in ('parameters','gradient','range','components','component_base')},sort_keys=True))
        h,w=reference.shape[:2];factor=min(1,1200/max(h,w));pw,ph=max(2,round(w*factor)),max(2,round(h*factor))
        a,b,c,d=bounds;sw,sh=size
        image=np.array(Image.fromarray(self.output[b:d,a:c]).resize(size,Image.Resampling.LANCZOS))
        yy,xx=np.meshgrid(b+(np.arange(sh,dtype=np.float32)+.5)*(d-b)/sh-.5,a+(np.arange(sw,dtype=np.float32)+.5)*(c-a)/sw-.5,indexing='ij')
        points=np.stack([xx,yy],2);q=self.original_points(points.reshape(-1,2)).reshape(sh,sw,2)
        if factor<1 and max((c-a)/sw,(d-b)/sh)<=1:
            # A downsampled 1200px matte cannot display native 1px repairs at
            # high zoom. Evaluate only visible native rows, including the
            # alpha function's tile halo, and sample original coordinates.
            lo=max(0,min(h-1,int(np.floor(q[:,:,1].min()))-2));hi=max(lo+1,min(h,int(np.ceil(q[:,:,1].max()))+3))
            native_key=(key,'native',lo,hi)
            if self._local_alpha_cache is None or self._local_alpha_cache[0]!=native_key:self._local_alpha_cache=(native_key,alpha(layer,reference,(lo,hi)))
            weights=cv2.remap(self._local_alpha_cache[1],q[:,:,0].astype(np.float32),(q[:,:,1]-lo).astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)*.6
        else:
            preview_key=(key,'overview')
            if self._local_alpha_cache is None or self._local_alpha_cache[0]!=preview_key:
                sample=copy.copy(layer);sample['mask']=cv2.resize(layer['mask'].astype(np.uint8),(pw,ph),interpolation=cv2.INTER_NEAREST)>0;sample['parameters']=dict(layer['parameters'])
                sample['parameters']['feather']*=factor;sample['parameters']['expand']*=factor
                small=cv2.resize(reference,(pw,ph),interpolation=cv2.INTER_AREA);self._local_alpha_cache=(preview_key,alpha(sample,small))
            weights=cv2.remap(self._local_alpha_cache[1],(q[:,:,0]+.5)*pw/w-.5,(q[:,:,1]+.5)*ph/h-.5,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)*.6
        cut=int(round(localcut*sw/max(1,c-a)))
        if cut:
            before=Image.fromarray(self.session.original[b:d,a:c]).resize(size,Image.Resampling.LANCZOS);image[:,:cut]=np.asarray(before)[:,:cut];weights[:,:cut]=0
        if getattr(self,'_local_mask_view','彩色叠加')=='黑白蒙版':
            image=np.repeat(np.rint(weights[:,:,None]/.6*255).clip(0,255).astype(np.uint8),3,axis=2)
        else:image=np.rint(image*(1-weights[:,:,None])+np.array([155,110,235])*weights[:,:,None]).clip(0,255).astype(np.uint8)
        return Image.fromarray(image)
    def build_local_develop(self,body):
        self._local_develop_combos=[]
        sub=Section(body,'线性 / 径向渐变与范围蒙版',opened=False);sub._feature_scope='mask_range'
        self.mode_button(sub.body,'拖动创建线性渐变','develop_linear')
        self.mode_button(sub.body,'拖动创建径向渐变','develop_radial')
        self.button(sub.body,'反转当前渐变',self.invert_local_gradient)
        for var,values in [(self.local_range_kind,['无范围限制','亮度范围','颜色范围']),(self.local_range_operation,['交集','减去'])]:
            combo=ttk.Combobox(sub.body,textvariable=var,values=values,state='readonly');combo.pack(fill='x',pady=3);combo.bind('<<ComboboxSelected>>',lambda e:self.local_range_changed());self.controls.append(combo)
            self._local_develop_combos.append(combo)
        for var,title,lo,hi in [(self.local_low,'亮度下界',0,4),(self.local_high,'亮度上界',0,4),(self.local_soft,'亮度过渡',.001,1),(self.local_hue_range,'颜色色相范围',1,180)]:self.slider(sub.body,title,var,lo,hi,self.local_range_changed,decimals=2 if hi<=4 else 0)
        self.mode_button(sub.body,'在照片上取范围颜色','develop_range')
        ttk.Label(sub.body,textvariable=self.local_range_note,style='Muted.TLabel',wraplength=270).pack(fill='x')
        detail=Section(body,'局部影调与细节',opened=False);detail._feature_scope='mask_detail'
        self.button(detail.body,'将旧蒙版转换为专业调色…',self.convert_local_process)
        from local_develop import EXTRA
        for key,title,lo,hi in EXTRA:self.layer_sliders.append(self.slider(detail.body,title,self.layer_vars[key],lo,hi,self.layer_values_changed))
        ttk.Label(detail.body,text='范围依据调色前图像；白色为保留，局部参数保持独立，可按住对比。',style='Muted.TLabel',wraplength=270).pack(fill='x')
    def sync_local_develop(self):
        if not hasattr(self,'local_range_kind'):return
        layer=self.region_layers[self.active_layer] if 0<=self.active_layer<len(self.region_layers) else {}
        ranges=layer.get('range',{});self.local_range_kind.set({'none':'无范围限制','luminance':'亮度范围','color':'颜色范围'}[ranges.get('kind','none')])
        self.local_range_operation.set('减去' if ranges.get('operation')=='subtract' else '交集')
        self.local_low.set(ranges.get('low',0));self.local_high.set(ranges.get('high',1));self.local_soft.set(ranges.get('softness',.1))
        self.local_hue_range.set(ranges.get('sample',{}).get('hue_range',30))
    def local_range_changed(self):
        if self.loading_layer or self.busy or not 0<=self.active_layer<len(self.region_layers):return
        layer=self.region_layers[self.active_layer];kind={'无范围限制':'none','亮度范围':'luminance','颜色范围':'color'}[self.local_range_kind.get()]
        if kind=='luminance' and self.local_low.get()>=self.local_high.get():self.local_range_note.set('亮度下界需小于上界。');return
        sample=layer.get('range',{}).get('sample')
        if kind=='color' and not sample:self.local_range_note.set('请先在照片上取范围颜色。');return
        self.commit_edit('范围蒙版调整前');record=dict(kind=kind,operation='subtract' if self.local_range_operation.get()=='减去' else 'intersect')
        if kind=='luminance':record.update(low=self.local_low.get(),high=self.local_high.get(),softness=self.local_soft.get())
        if kind=='color':record['sample']=dict(sample,hue_range=self.local_hue_range.get())
        layer['range']=record;self.parameter_apply(self.refresh);self.record('调整局部范围蒙版')
    def convert_local_process(self):
        if self.busy or not 0<=self.active_layer<len(self.region_layers):return
        layer=self.region_layers[self.active_layer]
        if layer.get('color_process',1)==2:self.status.set('当前蒙版已使用专业调色。');return
        if not messagebox.askyesno('转换局部调色','专业调色支持更多参数，但已有曝光、色彩和处理顺序可能改变。转换可撤销，是否继续？',parent=self.root):return
        self.commit_edit('转换局部调色前');layer['color_process']=2;self.parameter_apply(self.refresh);self.record('转换为专业局部调色')
    def begin_develop_gradient(self,event):
        if self.busy or self._render_pending or not self.document:return
        self.commit_edit('渐变蒙版前');p=self.original_point(self.point(event))
        self.drag=dict(mode='develop_gradient',start=p,screen=(event.x,event.y),kind='linear' if self.mode.get()=='develop_linear' else 'radial')
    def update_develop_gradient(self,event):
        d=self.drag
        if not d or d.get('mode')!='develop_gradient':return
        self.canvas.delete('develop_gradient')
        x,y=d['screen']
        if d['kind']=='linear':self.canvas.create_line(x,y,event.x,event.y,fill='#3169ec',width=2,tags='develop_gradient')
        else:self.canvas.create_oval(x-abs(event.x-x),y-abs(event.y-y),x+abs(event.x-x),y+abs(event.y-y),outline='#3169ec',width=2,tags='develop_gradient')
    def finish_develop_gradient(self,event):
        d=self.drag;self.drag=None;self.canvas.delete('develop_gradient')
        if not d or d.get('mode')!='develop_gradient':return
        if len(self.region_layers)>=MAX_LAYERS:self.status.set('蒙版数量已到上限。');return
        end=self.original_point(self.point(event));h,w=self.document.rgb.shape[:2];scale=np.array([max(1,w-1),max(1,h-1)])
        start=d['start']/scale;end=end/scale
        if np.linalg.norm(end-start)<.001:return
        self.region_layers.append(dict(name='线性渐变' if d['kind']=='linear' else '径向渐变',enabled=True,mask=np.ones((h,w),bool),parameters=dict(LOCAL_DEFAULTS),color_process=2,gradient=dict(kind=d['kind'],start=start.tolist(),end=end.tolist(),invert=False)))
        self.active_layer=len(self.region_layers)-1;self.mask_overlay.set(True);self.sync_layers();self.select_tool('pan');self.parameter_apply(self.refresh);self.record('创建渐变蒙版')
    def invert_local_gradient(self):
        if not 0<=self.active_layer<len(self.region_layers):return
        gradient=self.region_layers[self.active_layer].get('gradient')
        if not gradient:self.status.set('当前蒙版没有渐变。');return
        self.commit_edit('反转渐变前');gradient['invert']=not gradient.get('invert',False);self.parameter_apply(self.refresh);self.record('反转渐变')
    def sample_local_range(self,event):
        if not 0<=self.active_layer<len(self.region_layers) or self.color_input is None:return
        x,y=np.rint(self.original_point(self.point(event))).astype(int);h,w=self.color_input.shape[:2]
        if not 0<=x<w or not 0<=y<h:return
        lab=cs.oklab(cs.decode(self.color_input[y,x]/255));hue=float((np.rad2deg(np.arctan2(lab[2],lab[1]))+360)%360)
        from develop_settings import checked_points
        sample=checked_points([dict(hue=hue,chroma=float(np.linalg.norm(lab[1:])),lightness=float(max(0,lab[0])),hue_range=self.local_hue_range.get())])[0]
        self.commit_edit('颜色范围取样前');layer=self.region_layers[self.active_layer];layer['range']=dict(kind='color',operation='intersect',sample=sample)
        self.local_range_kind.set('颜色范围');self.parameter_apply(self.refresh);self.record('局部颜色范围取样');self.select_tool('pan')
