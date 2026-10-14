"""VIDEO mesh geometry, bounded native-coordinate smoothing and one remap.

Uses the existing AURA target/field code with MediaPipe controls, not SPIGA or
generated pixels. Skin correction deltas are stabilized BEFORE this warp.
"""
import numpy as np,cv2
from mesh_landmarks import controls
import face_reshape

class LiveShape:
    def __init__(self):
        self.canonical=None;self.confidence=None;self.frames=0;self.minimum_jacobian=1.;self.reduced_frames=0;self.pixel_preview=False
    def clear(self):self.canonical=None;self.confidence=None
    def apply(self,rgb,face,context,labels,values,reset=False):
        if not any(values.values()):self.clear();return rgb
        p=controls(face.points.astype(float));eyes=p[60:68].mean(0),p[68:76].mean(0)
        horizontal=eyes[1]-eyes[0];horizontal/=max(1e-8,np.linalg.norm(horizontal))
        vertical=np.array([-horizontal[1],horizontal[0]])
        pivot=(eyes[0]+eyes[1])/2
        if (p[16]-pivot)@vertical<0:vertical*=-1
        basis=np.column_stack([horizontal,vertical]);width=max(1.,float(np.linalg.norm(p[0]-p[32])))
        canonical=(p-pivot)@basis/width
        if not reset and self.canonical is not None:
            speed=np.linalg.norm(canonical-self.canonical,axis=1)
            weight=np.where(speed>.012,1.,.85)[:,None]
            canonical=self.canonical+(canonical-self.canonical)*weight
        self.canonical=canonical.copy();p=canonical@basis.T*width+pivot
        visible=(~np.isin(labels,[0,6,9,17,18])).astype(np.float32)
        support=np.clip(face_reshape._sample(visible,p,context),0,1)
        jaw=support[:33].copy()
        if not reset and self.confidence is not None:
            # Protect newly occluded points immediately; recover gradually.
            jaw=np.minimum(jaw,self.confidence+(jaw-self.confidence)*.35)
        self.confidence=jaw.copy()
        yaw_ratio=min(np.linalg.norm(p[54]-p[0]),np.linalg.norm(p[54]-p[32]))/max(1.,max(np.linalg.norm(p[54]-p[0]),np.linalg.norm(p[54]-p[32])))
        strength=float(np.clip((yaw_ratio-.15)/.5,0,1))
        settings={k:float(v)*strength for k,v in values.items()}
        for k in ('rs_slim_left','rs_slim_right','rs_jaw_left','rs_jaw_right'):
            settings[k]*=float(np.clip(jaw.mean()*2,0,1))
        for k in ('rs_chin_width','rs_chin_length'):
            settings[k]*=float(jaw[16])
        if not any(settings.values()):return rgb
        geometry={'points':p,'confidence':jaw,'fixed_anchors':np.empty((0,2)),
                  'feature_visibility':support,'shape':rgb.shape[:2],'pixel_preview':self.pixel_preview}
        field=face_reshape.build_field(geometry,settings,[face],0)
        output,changed=face_reshape.apply(rgb,[settings],{0:{'field':field}})
        if changed:self.frames+=1
        self.minimum_jacobian=min(self.minimum_jacobian,field['jacobian_min'])
        if strength<.9 or field['effective_scale']<1:self.reduced_frames+=1
        return output
