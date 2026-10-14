"""Image-coordinate viewport and reversible repair selections."""
import numpy as np
import cv2

class Viewport:
    def __init__(self):self.scale=1.;self.cx=0.;self.cy=0.
    def fit(self,box,size):
        a,b,c,d=box;cw,ch=size
        self.cx=(a+c)/2;self.cy=(b+d)/2
        self.scale=max(.01,min((cw-24)/max(1,c-a),(ch-24)/max(1,d-b)))
    def to_image(self,x,y,size):return self.cx+(x-size[0]/2)/self.scale,self.cy+(y-size[1]/2)/self.scale
    def to_canvas(self,x,y,size):return size[0]/2+(x-self.cx)*self.scale,size[1]/2+(y-self.cy)*self.scale
    def zoom(self,factor,x,y,size):
        px,py=self.to_image(x,y,size);self.scale=float(np.clip(self.scale*factor,.03,16))
        self.cx=px-(x-size[0]/2)/self.scale;self.cy=py-(y-size[1]/2)/self.scale
    def pan(self,dx,dy):self.cx-=dx/self.scale;self.cy-=dy/self.scale

class Selection:
    def __init__(self,auto):self.auto=auto>0;self.mask=self.auto.copy();self.undo_stack=[];self.redo_stack=[]
    def snapshot(self):return np.packbits(self.mask),np.packbits(self.auto)
    def restore(self,state):
        shape=self.mask.shape;size=self.mask.size
        self.mask=np.unpackbits(state[0],count=size).reshape(shape).astype(bool)
        self.auto=np.unpackbits(state[1],count=size).reshape(shape).astype(bool)
    def checkpoint(self):
        self.undo_stack.append(self.snapshot());self.redo_stack.clear()
        while len(self.undo_stack)>20 or (len(self.undo_stack)>1 and sum(a.nbytes+b.nbytes for a,b in self.undo_stack)>128*1024*1024):self.undo_stack.pop(0)
    def undo(self):
        if not self.undo_stack:return False
        self.redo_stack.append(self.snapshot());self.restore(self.undo_stack.pop());return True
    def redo(self):
        if not self.redo_stack:return False
        self.undo_stack.append(self.snapshot());self.restore(self.redo_stack.pop());return True
    def rescan(self,auto):
        self.checkpoint();manual=self.mask&~self.auto;excluded=self.auto&~self.mask
        self.auto=auto>0;self.mask=(self.auto|manual)&~excluded
    def reset(self):self.checkpoint();self.mask=self.auto.copy()
    def stroke(self,p0,p1,radius,erase=False,auto_only=False):
        h,w=self.mask.shape;r=max(1,int(radius));x0,y0=map(lambda v:int(round(v)),p0);x1,y1=map(lambda v:int(round(v)),p1)
        a,b=max(0,min(x0,x1)-r-2),max(0,min(y0,y1)-r-2);c,d=min(w,max(x0,x1)+r+3),min(h,max(y0,y1)+r+3)
        if a>=c or b>=d:return
        local=np.zeros((d-b,c-a),np.uint8);cv2.line(local,(x0-a,y0-b),(x1-a,y1-b),1,r*2+1)
        cv2.circle(local,(x0-a,y0-b),r,1,-1);cv2.circle(local,(x1-a,y1-b),r,1,-1)
        region=local>0
        if auto_only:region&=self.auto[b:d,a:c]
        self.mask[b:d,a:c][region]=not erase
    def set_auto_region(self,point,enabled):
        """Cancel/restore one connected automatic candidate without changing manual additions."""
        x,y=map(lambda v:int(round(v)),point);h,w=self.auto.shape
        if not (0<=x<w and 0<=y<h) or not self.auto[y,x]:return False
        region=self.auto.astype(np.uint8);cv2.floodFill(region,None,(x,y),2,flags=8)
        selected=region==2;changed=bool(np.any(self.mask[selected]!=enabled))
        self.mask[selected]=enabled;return changed
    def pending(self,done):return bool(np.any(self.mask)) if done is None else bool(np.any(self.mask&~(done>0)))
    def repair_alpha(self,accepted,feather=0,origin=(0,0)):
        """Inward feather on manual components; automatic repair keeps its old edge."""
        mask=np.asarray(accepted,bool)
        distance=cv2.distanceTransform(np.pad(mask.astype(np.uint8),1),cv2.DIST_L2,5)[1:-1,1:-1]
        alpha=np.clip(distance/1.5,0,1)
        amount=float(np.clip(feather,0,100))/100
        if amount:
            x,y=origin;h,w=mask.shape;manual=mask&~self.auto[y:y+h,x:x+w]
            count,labels,stats,_=cv2.connectedComponentsWithStats(manual.astype(np.uint8),8)
            for i in range(1,count):
                x,y,w,h,_=stats[i];local=labels[y:y+h,x:x+w]==i
                edge=distance[y:y+h,x:x+w];width=max(1.5,float(edge[local].max())*amount)
                view=alpha[y:y+h,x:x+w];view[local]=np.clip(edge[local]/width,0,1)
        return alpha
