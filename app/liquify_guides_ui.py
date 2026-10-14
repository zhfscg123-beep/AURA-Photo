"""Visible anatomy guides and direct local handle edits, separate from photo pixels."""
import tkinter as tk
from tkinter import ttk
import cv2,numpy as np
from dpi_support import dp,ui_font
import liquify,liquify_guides as guides,face_reshape

class LiquifyGuidesUI:
    def init_liquify_guides(self):
        self.liquify_guide_face=tk.BooleanVar(value=True);self.liquify_guide_body=tk.BooleanVar(value=True)
        self.liquify_fix_nodes=tk.BooleanVar(value=True);self.liquify_guide_hint=tk.StringVar(value='蓝：五官 · 绿：人物外缘（含衣服）')
        self.liquify_guide_cache={};self.liquify_guide_session=None;self.liquify_guide_handles=[];self.liquify_all_guide_handles=[]
    def build_guide_controls(self,body):
        self.liquify_fix_control=ttk.Checkbutton(body,text='节点调整时固定其他节点',variable=self.liquify_fix_nodes)
        self.liquify_fix_control.pack(anchor='w',pady=3);self.controls.append(self.liquify_fix_control)
        ttk.Label(body,textvariable=self.liquify_guide_hint,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=4)
    def sync_guide_controls(self):
        if hasattr(self,'liquify_fix_control'):
            self.liquify_fix_control.configure(state='normal' if self.document is not None and not self.busy and self.mode.get() in ('liquify_nodes','liquify_face') else 'disabled')
    def _guide_bundle(self):
        if self.liquify_guide_session is not self.session:
            self.liquify_guide_cache={};self.liquify_guide_session=self.session
        key=(self.active_face,id(getattr(self.session,'person_owner',None)))
        if key not in self.liquify_guide_cache:self.liquify_guide_cache[key]=guides.build(self.session,self.active_face)
        return self.liquify_guide_cache[key]
    def _guide_message(self,text):
        if self.liquify_guide_hint.get()!=text:self.liquify_guide_hint.set(text)
    def draw_liquify_guides(self):
        self.liquify_guide_handles=[];self.liquify_all_guide_handles=[];self.canvas.delete('liquify_guides')
        if not self.session or self.output is None or self.mode.get()!='liquify_nodes':return
        bundle=self._guide_bundle();cw,ch=self.size();split=cw*self.split.get()/100;shape=self.output.shape[:2]
        state=self.liquify_state if self.liquify_enabled.get() else None
        available=[n for n in bundle['nodes'] if self.mode.get()!='liquify_face' or n['kind']=='face']
        if not available:return
        original=np.asarray([n['point'] for n in available],np.float32)
        references,ok0=guides.project(original,shape,self.reshape_cache,self.face_settings,None)
        displayed,ok1=guides.project(original,shape,self.reshape_cache,self.face_settings,state)
        active_group=None;paths={};distance=float('inf')
        for name,lines in bundle.get('groups',{}).items():
            if self.mode.get()=='liquify_face' and name.startswith('body-'):continue
            for line in lines:
                projected,valid=guides.project(line,shape,self.reshape_cache,self.face_settings,state)
                for run in guides.finite_runs(projected,valid):
                    screen=np.asarray([self.view.to_canvas(*p,(cw,ch)) for p in run]);paths.setdefault(name,[]).append(screen)
                    if self.pointer is not None and self.pointer[0]>=split:
                        value=float(np.linalg.norm(screen-self.pointer,axis=1).min())
                        if value<distance and value<=dp(self.root,18):active_group=name;distance=value
        for node,reference,p,valid in zip(available,references,displayed,ok0&ok1):
            if not valid:continue
            self.liquify_all_guide_handles.append(dict(node,reference=reference,display=p))
            if self.pointer is not None and self.pointer[0]>=split:
                value=np.linalg.norm(np.asarray(self.view.to_canvas(*p,(cw,ch)))-self.pointer)
                if value<distance and value<=dp(self.root,24):active_group=node['group'];distance=value
            if self.drag and self.drag.get('node_key')==node['key']:active_group=node['group']
        if self.drag and self.drag.get('node_key'):
            active=next((n for n in available if n['key']==self.drag['node_key']),None)
            if active:active_group=active['group']
        self._guide_message('悬停部位显示轮廓和全部节点；移开隐藏。拖动节点微调，身体轮廓包含衣物边缘。')
        if active_group is None:return
        color='#71d9a6' if active_group.startswith('body-') else '#55c9f4'
        for line in paths.get(active_group,[]):
            for clipped in guides.clipped_lines(line,(round(split),0,cw,ch)):
                self.canvas.create_line(*np.asarray(clipped).ravel().tolist(),fill=color,width=dp(self.root,1.5),tags='liquify_guides')
        radius=dp(self.root,5)
        for node in self.liquify_all_guide_handles:
            if node['group']!=active_group:continue
            x,y=self.view.to_canvas(*node['display'],(cw,ch))
            if not split<=x<cw or not 0<=y<ch:continue
            active=self.drag and self.drag.get('node_key')==node['key']
            self.canvas.create_oval(x-radius,y-radius,x+radius,y+radius,fill='white',outline='#f0b951' if active else color,width=dp(self.root,1.5),tags='liquify_guides')
            self.liquify_guide_handles.append(node)
    def liquify_node_hit(self,point):
        if self.mode.get() not in ('liquify_nodes','liquify_face'):return None
        hits=[(np.linalg.norm(np.asarray(point)-n['display'])*self.view.scale,n) for n in self.liquify_guide_handles]
        if not hits:return None
        distance,node=min(hits,key=lambda pair:pair[0])
        return node if distance<=dp(self.root,9) else None
    def start_liquify_node(self,event):
        if self.shape_pending():self.status.set('请等待面部重塑完成后调整节点。');return
        p=np.asarray(self.point(event),np.float32);node=self.liquify_node_hit(p)
        if node is None:self.status.set('右侧可调整智能五官；需要拖动轮廓节点时请选择“节点”工具。');return
        if not self.liquify_enabled.get() and liquify.active(self.liquify_state):
            self.status.set('请先开启“显示画笔液化”，显示已保存的形变后再拖动节点。');return
        if self.liquify_state is None:self.liquify_state=liquify.create(self.document.rgb.shape[:2])
        sx,sy=liquify.spacing(self.liquify_state)
        frozen=cv2.remap(self.liquify_state['freeze'],np.array([[node['display'][0]/sx]],np.float32),np.array([[node['display'][1]/sy]],np.float32),cv2.INTER_LINEAR)[0,0]
        if frozen>=.95:self.status.set('该节点位于冻结保护中，请先解除保护。');return
        self.commit_edit('节点调整前');self.liquify_enabled.set(True)
        h,w=self.liquify_input.shape[:2];self.liquify_preview_factor=min(1,max(.05,self.view.scale))
        factor=self.liquify_preview_factor
        from photo_document import to_uint8
        self.liquify_preview=to_uint8(cv2.resize(self.liquify_input,(max(1,round(w*factor)),max(1,round(h*factor))),interpolation=cv2.INTER_AREA) if factor<1 else self.liquify_input)
        protection=self.liquify_state['freeze'].copy()
        radius=min(float(self.liquify_radius.get()),node['radius'])
        if self.liquify_fix_nodes.get():
            temporary=dict(self.liquify_state,freeze=protection)
            distances=[np.linalg.norm(n['display']-node['display']) for n in self.liquify_all_guide_handles if n['key']!=node['key']]
            distances=[distance for distance in distances if distance>2]
            if distances:radius=max(5,min(radius,min(distances)*.65))
            for other in self.liquify_all_guide_handles:
                if other['key']==node['key']:continue
                distance=np.linalg.norm(other['display']-node['display'])
                r=max(2*max(sx,sy),min(24,float(getattr(self.session.faces[self.active_face],'width',100))*.06,distance*.35))
                if np.linalg.norm(other['display']-node['display'])<r*1.5:continue
                liquify.stamp(temporary,other['display'],np.zeros(2,np.float32),r,1,'freeze',density=50)
            self._protect_other_people(protection)
        self.drag=dict(mode='liquify_node',node_key=node['key'],label=node['name'],reference=node['reference'].copy(),
                       actual=node['display'].copy(),offset=node['display']-p,r=radius,
                       density=float(self.liquify_density.get()),strength=100.,changed=False,protection=protection)
        self.draw()
    def _protect_other_people(self,protection):
        owner=getattr(self.session,'person_owner',None)
        if len(self.session.faces)<2 or not isinstance(owner,np.ndarray):return
        state=self.liquify_state;sx,sy=liquify.spacing(state);gh,gw=protection.shape
        yy,xx=np.mgrid[:gh,:gw].astype(np.float32)
        qx=xx*sx+state['flow'][:,:,0];qy=yy*sy+state['flow'][:,:,1]
        dx=np.zeros_like(qx);dy=np.zeros_like(qy)
        for field in face_reshape._fields(self.reshape_cache,self.face_settings):
            a,b,c,d=field['roi'];grid=field['grid'];h,w=grid.shape[:2]
            delta=cv2.remap(grid,(qx-a)*(w-1)/max(1,c-a-1),(qy-b)*(h-1)/max(1,d-b-1),cv2.INTER_LINEAR)
            inside=(qx>=a)&(qx<=c-1)&(qy>=b)&(qy<=d-1)
            dx+=delta[:,:,0]*inside;dy+=delta[:,:,1]*inside
        assigned=cv2.remap(owner,qx+dx,qy+dy,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)
        protection[(assigned>0)&(assigned!=self.active_face+1)]=1
    def update_liquify_node(self,p):
        d=self.drag;h,w=self.document.rgb.shape[:2]
        desired=np.clip(np.asarray(p,np.float32)+d['offset'],[0,0],[w-1,h-1]).astype(np.float32)
        if np.linalg.norm(desired-d['actual'])<.15:self.draw_tool_cursor();return
        saved=self.liquify_state['freeze'];self.liquify_state['freeze']=d['protection']
        try:changed=liquify.stroke(self.liquify_state,d['actual'],desired,d['r'],100,'push',density=d['density'])
        finally:self.liquify_state['freeze']=saved
        reference=d['reference'][None].astype(np.float32)
        mapped,valid=guides.project(reference,self.document.rgb.shape[:2],{},[],self.liquify_state)
        if valid[0]:d['actual']=mapped[0]
        d['changed']|=changed
        if np.linalg.norm(d['actual']-desired)>2:self.status.set('已限制节点位移以保护冻结区域与相邻节点，可分步微调。')
        self.draw()
