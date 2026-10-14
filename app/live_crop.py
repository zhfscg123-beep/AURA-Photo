"""Interactive crop handles in a rotated preview; stored edits remain original sized."""
import tkinter as tk
import cv2,numpy as np
from PIL import Image,ImageTk
from dpi_support import dp,ui_font
from dark_ui import COLORS
import composition

class LiveCropUI:
    def init_live_crop(self):self.crop_cache=None;self.crop_hits={};self.crop_drag=None;self.crop_straighten=False;self.crop_small_cache=None
    def draw_live_crop(self,pixels=None,data=None):
        if getattr(self,'active_category',None)!='构图' or self.output is None:return False
        pixels=self.output if pixels is None else pixels;data=composition.checked(self.workflow_extensions.get('composition',{}) if data is None else data)
        cw,ch=self.size();key=(id(pixels),data['quarter'],data['rotation'],cw,ch)
        if self.crop_cache is None or self.crop_cache[0]!=key:
            try:
                from gpu_render import crop_stage
                self.crop_cache=(key,crop_stage(pixels,data,(cw,ch)))
            except Exception as error:
                from gpu_render import record_cpu_recovery
                record_cpu_recovery('构图预览',error)
        if self.crop_cache is None or self.crop_cache[0]!=key:
            factor=min(1,1600/max(pixels.shape[:2]));small_key=id(pixels)
            if self.crop_small_cache is None or self.crop_small_cache[0]!=small_key:
                self.crop_small_cache=(small_key,cv2.resize(pixels,(max(2,round(pixels.shape[1]*factor)),max(2,round(pixels.shape[0]*factor))),interpolation=cv2.INTER_AREA))
            small=self.crop_small_cache[1]
            stage=composition.oriented(small,data,margin=max(1,round(4*factor)));h,w=stage.shape[:2];scale=min((cw-40)/w,(ch-50)/h)
            size=(max(1,round(w*scale)),max(1,round(h*scale)));stage=cv2.resize(stage,size,interpolation=cv2.INTER_AREA)
            self.crop_cache=(key,stage)
        image=self.crop_cache[1];h,w=image.shape[:2];x=(cw-w)/2;y=(ch-h)/2
        a,b,c,d=composition.rectangle(w,h,data,composition.original_aspect(pixels.shape,data))
        try:
            from gpu_render import crop_shade
            paint=crop_shade(image,(a,b,c,d))
        except Exception as error:
            from gpu_render import record_cpu_recovery
            record_cpu_recovery('构图选框遮罩',error);paint=image.copy();mask=np.ones((h,w),bool);mask[b:d,a:c]=False;paint[mask]=(paint[mask]*.35).astype(np.uint8)
        self.crop_photo=ImageTk.PhotoImage(Image.fromarray(paint),master=self.root);self.canvas.delete('all');self.canvas.create_image(x,y,anchor='nw',image=self.crop_photo)
        box=(x+a,y+b,x+c,y+d);self.crop_box=box;self.crop_image_box=(x,y,w,h);self.crop_hits={}
        self.canvas.create_rectangle(*box,outline='white',width=dp(self.root,2))
        for t in (1/3,2/3):
            self.canvas.create_line(box[0]+(box[2]-box[0])*t,box[1],box[0]+(box[2]-box[0])*t,box[3],fill='white',dash=(4,4))
            self.canvas.create_line(box[0],box[1]+(box[3]-box[1])*t,box[2],box[1]+(box[3]-box[1])*t,fill='white',dash=(4,4))
        for key,p in [('nw',box[:2]),('ne',(box[2],box[1])),('sw',(box[0],box[3])),('se',box[2:])]:
            r=dp(self.root,6);self.canvas.create_rectangle(p[0]-r,p[1]-r,p[0]+r,p[1]+r,fill='white',outline=COLORS['accent']);self.crop_hits[key]=p
        for key,p in [('n',((box[0]+box[2])/2,box[1])),('s',((box[0]+box[2])/2,box[3])),('w',(box[0],(box[1]+box[3])/2)),('e',(box[2],(box[1]+box[3])/2))]:
            r=dp(self.root,4);self.canvas.create_rectangle(p[0]-r,p[1]-r,p[0]+r,p[1]+r,fill='white',outline=COLORS['accent']);self.crop_hits[key]=p
        self.canvas.create_text(dp(self.root,12),dp(self.root,14),text='拖边角裁剪 · 框内移动 · 框外旋转',anchor='nw',fill=COLORS['text'],font=ui_font(self.root,10))
        return True
    def start_crop_drag(self,event):
        if self.busy or not self.crop_hits:return
        p=np.array([event.x,event.y]);hit=min(self.crop_hits,key=lambda k:np.linalg.norm(p-self.crop_hits[k]));inside=self.crop_box[0]<=p[0]<=self.crop_box[2] and self.crop_box[1]<=p[1]<=self.crop_box[3]
        rotate=np.linalg.norm(p-self.crop_hits[hit])>dp(self.root,12) and not inside
        self.commit_edit('构图拖动前');self.crop_drag=dict(mode='resize' if np.linalg.norm(p-self.crop_hits[hit])<=dp(self.root,12) else 'move',hit=hit,start=p,values={k:v.get() for k,v in self.crop_vars.items()},box=self.crop_box,locked=self.crop_lock.get())
        if self.crop_straighten:self.crop_drag['mode']='straighten'
        elif rotate:self.crop_drag['mode']='rotate'
        self.drag={'mode':'crop_edit'}
    def update_crop_drag(self,event):
        if self.crop_drag is None:return
        d=self.crop_drag;dx,dy=np.array([event.x,event.y])-d['start'];x,y,w,h=self.crop_image_box
        if d['mode']=='straighten':
            self.canvas.delete('crop_straighten');self.canvas.create_line(*d['start'],event.x,event.y,fill='#ffffff',width=2,tags='crop_straighten');return
        if d['mode']=='rotate':
            center=np.array([sum(d['box'][::2])/2,sum(d['box'][1::2])/2]);v0=d['start']-center;v1=np.array([event.x,event.y])-center
            delta=np.rad2deg(np.arctan2(v0[0]*v1[1]-v0[1]*v1[0],np.dot(v0,v1)))
            self.crop_vars['rotation'].set(float(np.clip(d['values']['rotation']-delta,-180,180)));self.store_composition();self.draw();return
        if d['mode']=='move':
            bx,by,cx,cy=d['box'];pw,ph=cx-bx,cy-by
            self.crop_vars['center_x'].set(float(np.clip(((bx+cx)/2-x+dx)/w*100,pw/w*50,100-pw/w*50)))
            self.crop_vars['center_y'].set(float(np.clip(((by+cy)/2-y+dy)/h*100,ph/h*50,100-ph/h*50)))
        else:
            bx,by,cx,cy=d['box'];hit=d['hit'];minimum=max(2,min(w,h)*.01)
            if not d['locked']:
                if 'w' in hit:bx=float(np.clip(bx+dx,x,cx-minimum))
                if 'e' in hit:cx=float(np.clip(cx+dx,bx+minimum,x+w))
                if 'n' in hit:by=float(np.clip(by+dy,y,cy-minimum))
                if 's' in hit:cy=float(np.clip(cy+dy,by+minimum,y+h))
                self.crop_vars['width'].set((cx-bx)/w*100);self.crop_vars['height'].set((cy-by)/h*100);self.crop_vars['size'].set(100.)
            else:
                # Keep the opposite corner (or opposite edge midpoint) fixed.
                ratio=(cx-bx)/(cy-by);horizontal=bool('e' in hit or 'w' in hit);vertical=bool('n' in hit or 's' in hit)
                anchor_x=cx if 'w' in hit else bx if 'e' in hit else (bx+cx)/2
                anchor_y=cy if 'n' in hit else by if 's' in hit else (by+cy)/2
                sx=-1 if 'w' in hit else 1;sy=-1 if 'n' in hit else 1
                desired_w=(cx-bx)+sx*dx if horizontal else ((cy-by)+sy*dy)*ratio
                if horizontal and vertical:
                    desired_h=(cy-by)+sy*dy;desired_w=(desired_w+desired_h*ratio)/2
                max_w=(anchor_x-x if sx<0 else x+w-anchor_x) if horizontal else 2*min(anchor_x-x,x+w-anchor_x)
                max_h=(anchor_y-y if sy<0 else y+h-anchor_y) if vertical else 2*min(anchor_y-y,y+h-anchor_y)
                pw=float(np.clip(desired_w,min(max_w,max_h*ratio,minimum),min(max_w,max_h*ratio)));ph=pw/ratio
                bx,cx=(anchor_x-pw,anchor_x) if horizontal and sx<0 else (anchor_x,anchor_x+pw) if horizontal else (anchor_x-pw/2,anchor_x+pw/2)
                by,cy=(anchor_y-ph,anchor_y) if vertical and sy<0 else (anchor_y,anchor_y+ph) if vertical else (anchor_y-ph/2,anchor_y+ph/2)
                mw,mh=(w,w/ratio) if w/h<ratio else (h*ratio,h)
                self.crop_vars['size'].set(float(np.clip(pw/mw*100,1,100)))
                if pw/mw*100<1:
                    pw=mw*.01;ph=mh*.01;bx=float(np.clip(bx,x,x+w-pw));by=float(np.clip(by,y,y+h-ph));cx=bx+pw;cy=by+ph
            self.crop_vars['center_x'].set(((bx+cx)/2-x)/w*100);self.crop_vars['center_y'].set(((by+cy)/2-y)/h*100)
        self.store_composition();self.draw()
    def finish_crop_drag(self,event):
        if self.crop_drag['mode']=='straighten':
            delta=np.array([event.x,event.y])-self.crop_drag['start']
            if np.linalg.norm(delta)>dp(self.root,12):
                angle=np.rad2deg(np.arctan2(delta[1],delta[0]));angle=(angle+90)%180-90
                self.crop_vars['rotation'].set(float(np.clip(self.crop_drag['values']['rotation']+angle,-180,180)));self.store_composition()
            self.crop_straighten=False;self.sync_tools();self.draw()
        else:self.update_crop_drag(event)
        self.crop_drag=None;self.drag=None;self.record('调整裁剪与角度')
    def rotate_crop(self,step):self.crop_quarter.set(str((int(self.crop_quarter.get()[:-1])//90+step)%4*90)+'°');self.composition_changed()
