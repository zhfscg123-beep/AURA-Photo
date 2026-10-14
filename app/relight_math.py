"""Independent 2.5D additive fill: Lambert + GGX + explicitly approximate hair.

RelightKit inspired the light types and linear additive light stack; this is
not its Nuke/BlinkScript implementation. No original-illumination removal,
albedo estimation, hidden-geometry shadows, full hair geometry or path tracing.
Visible-person depth can occlude the added lights through screen-space rays.
Coordinates: X right, Y up, Z toward viewer, scene units = long image side.
"""
import numpy as np,cv2

def unit(v):return v/np.maximum(np.linalg.norm(v,axis=-1,keepdims=True),1e-7)
def linear(rgb):
    s=np.clip(np.asarray(rgb,np.float32)/255,0,1)
    return np.where(s<=.04045,s/12.92,((s+.055)/1.055)**2.4)
def srgb(v):return np.where(v<=.0031308,v*12.92,1.055*np.maximum(v,0)**(1/2.4)-.055)*255

def light_rgb(light):
    """Artist light tint, not calibrated CCT. White-balance tint keeps energy Y.

    Existing RGB triples are unchanged when the new color controls are absent.
    A hex color is interpreted as sRGB; saturation/temperature/tint act only on
    the light, never on the source photograph or the display response curve.
    """
    if 'color_hex' in light:
        code=light['color_hex'].lstrip('#')
        c=linear(np.array([int(code[j:j+2],16) for j in [0,2,4]],np.float32))
        targetY=1.0 if np.max(c)>0 else 0.0
    else:c=np.array(light.get('color',[1,1,1]),np.float32);targetY=float(c@np.array([.2126,.7152,.0722]))
    weights=np.array([.2126,.7152,.0722],np.float32)
    modified='color_hex' in light or any(key in light for key in ['temperature','tint','saturation','color_mix'])
    if not modified:return c
    temperature=light.get('temperature',0)/100;tint=light.get('tint',0)/100
    c*=np.array([1+.25*temperature,1-.04*abs(temperature),1-.25*temperature],np.float32)
    c*=np.array([1+.08*tint,1-.20*tint,1+.08*tint],np.float32)
    y=float(c@weights);c=y+(c-y)*light.get('saturation',1)
    if y>1e-8:c*=targetY/max(1e-8,float(c@weights))
    mix=light.get('color_mix',1);c=targetY*(1-mix)+c*mix
    return np.clip(c,0,4).astype(np.float32)

def validate(config):
    lights=config.get('lights',[])
    if not isinstance(lights,list) or len(lights)>5:raise ValueError('Support zero to five lights')
    for light in lights:
        if light.get('type','point') not in ['point','directional','area','back']:raise ValueError('Unknown light type')
        if light.get('scope','all') not in ['all','skin','hair','person']:raise ValueError('Unknown scope')
        for key in ['position']+(['color'] if 'color' in light else []):
            a=np.asarray(light[key],float)
            if a.shape!=(3,) or not np.isfinite(a).all():raise ValueError('Invalid light '+key)
            if key=='color' and ((a<0).any() or (a>4).any()):raise ValueError('Color outside [0,4]')
        if 'color_hex' in light:
            text=light['color_hex']
            if not isinstance(text,str) or len(text)!=7 or text[0]!='#' or any(c not in '0123456789abcdefABCDEF' for c in text[1:]):raise ValueError('color_hex must be #RRGGBB')
            if 'color' in light:raise ValueError('Choose color or color_hex, not both')
        if 'color' not in light and 'color_hex' not in light:raise ValueError('Light color required')
        for key,lo,hi,default in [('power',0,20,1),('roughness',.12,1,.6),('range',.05,10,3),
            ('hair_gloss',0,5,.1),('hair_transmission',0,5,.1),('rim_width',.002,.2,.012),('size',.001,2,.15),('rim_gain',0,5,1.0),
            ('softness',0,100,0),('diffuse_wrap',0,.5,0),('specular_strength',0,1,.25),
            ('temperature',-100,100,0),('tint',-100,100,0),('saturation',0,1,1),('color_mix',0,1,1),
            ('lip_receive',0,1,.8),('brow_receive',0,1,.8)]:
            v=light.get(key,default)
            if type(v) not in [float,int] or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid '+key)
        if light.get('area_grid',2) not in [2,3,4,5]:raise ValueError('area_grid must be 2/3/4/5')
        if light.get('type')=='back' and light['position'][2]>=0:raise ValueError('Back light must have negative Z')
    render=config.get('render',{})
    for key,lo,hi,default in [('strength_scale',.1,10,3.0),('shadow_priority',0,1,.7),('highlight_protect',0,1,.8),
        ('color_strength',0,1,.25),('max_gain',1,16,8.0)]:
        v=render.get(key,default)
        if type(v) not in [float,int] or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid render '+key)
    return lights

def controls(source,g,person=None):
    """Mask-only upgrade on cached geometry, with outward silhouette directions.

    Preserve original face/hair masks for audit. Fill internal feature holes only
    for the silhouette distance; feature openings remain excluded from skin fill.
    """
    h,w=g['skin'].shape;out=dict(g);scale=max(h,w)
    skin=g['skin'];support=(skin>.001).astype(np.uint8)
    distance=cv2.distanceTransform(np.pad(support,1),cv2.DIST_L2,5)[1:-1,1:-1]
    feather=np.clip(distance/max(1.5,scale*.003),0,1)
    smooth=cv2.GaussianBlur(skin,(0,0),max(.7,scale*.0015))
    out['skin_fill']=(np.minimum(skin,smooth)*feather).astype(np.float32)
    if person is None:person=np.maximum(skin,g['hair'])
    person=np.clip(person,0,1).astype(np.float32)
    binary=(person>.35).astype(np.uint8)
    n,labels,stats,_=cv2.connectedComponentsWithStats(binary,8)
    if n>1:binary=(labels==1+np.argmax(stats[1:,cv2.CC_STAT_AREA])).astype(np.uint8)
    # Exterior contour only, never rings around eyes/lips or internal hair seams.
    padded=np.pad(binary,1);outside=padded.copy();cv2.floodFill(outside,None,(0,0),2)
    solid=(outside!=2)[1:-1,1:-1].astype(np.uint8)
    dist=cv2.distanceTransform(np.pad(solid,1),cv2.DIST_L2,5)[1:-1,1:-1]/scale
    smooth_dist=cv2.GaussianBlur(dist,(0,0),1.5)
    dx=cv2.Sobel(smooth_dist,cv2.CV_32F,1,0,ksize=3);dy=cv2.Sobel(smooth_dist,cv2.CV_32F,0,1,ksize=3)
    person_fade=np.clip(dist*scale/max(2,scale*.0025),0,1)
    out.update(person=(person*solid*person_fade).astype(np.float32),person_distance=dist.astype(np.float32),
        person_outward=unit(np.stack([-dx,dy,np.zeros_like(dx)],2)).astype(np.float32))
    out['scope']=np.maximum(out['skin_fill'],g['hair'])
    # Full-image luminance field makes controls independent of render tile edges.
    image=cv2.resize(source,(w,h),interpolation=cv2.INTER_AREA).astype(np.float32)
    luminance=linear(image)@np.array([.2126,.7152,.0722],np.float32)
    out['coarse_luminance']=cv2.GaussianBlur(luminance,(0,0),max(1,scale*.004))
    return out

def prepare_geometry(depth,normals,hair,skin,source,depth_scale=.45):
    normals=unit(np.asarray(normals,np.float32))
    hair=np.clip(hair,0,1).astype(np.float32);skin=np.clip(skin,0,1).astype(np.float32)
    scope=np.maximum(hair,skin);valid=scope>.5
    q0,q1=np.percentile(depth[valid] if valid.any() else depth,[2,98])
    near=np.clip((depth-q0)/max(1e-6,q1-q0),0,1)
    z=(near-.5)*depth_scale  # DAv2 relative inverse depth: brighter -> nearer.
    gray=cv2.cvtColor(np.asarray(source,np.uint8),cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3);gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)
    sigma=max(1.5,max(gray.shape)*.003)
    jxx=cv2.GaussianBlur(gx*gx,(0,0),sigma);jyy=cv2.GaussianBlur(gy*gy,(0,0),sigma)
    jxy=cv2.GaussianBlur(gx*gy,(0,0),sigma);phi=.5*np.arctan2(2*jxy,jxx-jyy)
    tangent=np.stack([-np.sin(phi),-np.cos(phi),np.zeros_like(phi)],axis=2)
    tangent=unit(tangent-(tangent*normals).sum(2)[:,:,None]*normals)
    coherence=np.sqrt((jxx-jyy)**2+4*jxy*jxy)/np.maximum(jxx+jyy,1e-6)
    binary=(hair>.35).astype(np.uint8)
    distance=cv2.distanceTransform(np.pad(binary,1),cv2.DIST_L2,5)[1:-1,1:-1]/max(gray.shape)
    dx=cv2.Sobel(distance,cv2.CV_32F,1,0,ksize=3);dy=cv2.Sobel(distance,cv2.CV_32F,0,1,ksize=3)
    outward=unit(np.stack([-dx,dy,np.zeros_like(dx)],2))
    return dict(z=z.astype(np.float32),normals=normals,hair=hair,skin=skin,scope=scope,
        tangent=tangent.astype(np.float32),coherence=coherence.astype(np.float32),
        hair_distance=distance.astype(np.float32),outward=outward.astype(np.float32),
        depth_scale=float(depth_scale),depth_percentiles=[float(q0),float(q1)])

def native_geometry(small,shape):
    h,w=shape;out={}
    for key,value in small.items():
        if not isinstance(value,np.ndarray):out[key]=value;continue
        if value.ndim<2:out[key]=value.tolist();continue
        out[key]=cv2.resize(value,(w,h),interpolation=cv2.INTER_LINEAR).astype(np.float32)
        if key in ['normals','tangent','outward','person_outward']:out[key]=unit(out[key])
    return out

def visible_depth_visibility(geometry,L,P,light):
    """Screen-space rays through the estimated visible height field only.

    No hidden geometry, cross-person/background shadows or original-light
    removal is inferred. Each area-light sample tests its own visibility.
    """
    if not light.get('occlusion',False) or light.get('type')=='back':return np.ones(P.shape[:2],np.float32)
    z=geometry.get('_occlusion_z');person=geometry.get('_occlusion_person')
    if z is None:return np.ones(P.shape[:2],np.float32)
    h,w=z.shape;span=max(h,w)
    delta=L*2 if light.get('type')=='directional' else np.asarray(light['position'],np.float32)-P
    visibility=np.ones(P.shape[:2],np.float32)
    for t in np.linspace(.04,.96,16):
        q=P+delta*np.float32(t)
        mx=(q[:,:,0]*span+(w-1)*.5).astype(np.float32);my=((h-1)*.5-q[:,:,1]*span).astype(np.float32)
        valid=(mx>=0)&(my>=0)&(mx<=w-1)&(my<=h-1)
        surface=cv2.remap(z,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=-100)
        occupied=cv2.remap(person,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0) if person is not None else valid
        blocked=valid&(occupied>.6)&(surface>q[:,:,2]+.015)
        visibility[blocked]=0
    return visibility

def _contribution(base,geometry,light,P):
    N=geometry['normals'];hair=geometry['hair'];skin=geometry['skin']
    kind=light.get('type','point');position=np.asarray(light['position'],np.float32)
    if kind=='directional':
        L=np.broadcast_to(unit(position),N.shape);attenuation=np.ones(N.shape[:2],np.float32)
    else:
        delta=position-P;distance=np.linalg.norm(delta,axis=2);L=unit(delta)
        # Finite emitter radius limits inverse-square singularities.
        attenuation=1/(1+distance*distance)
        cutoff=np.clip(1-(distance/light.get('range',3))**4,0,1);attenuation*=cutoff*cutoff
    signed_ndotl=(N*L).sum(2);ndotl=np.maximum(signed_ndotl,0);ndotv=np.maximum(N[:,:,2],1e-4)
    V=np.zeros_like(N);V[:,:,2]=1;H=unit(L+V)
    ndoth=np.maximum((N*H).sum(2),0);vdoth=np.maximum(H[:,:,2],0)
    roughness=float(light.get('roughness',.6));a2=roughness**4
    D=a2/(np.pi*np.maximum((ndoth*ndoth*(a2-1)+1)**2,1e-6))
    k=(roughness+1)**2/8
    Gv=ndotv/(ndotv*(1-k)+k);Gl=ndotl/(ndotl*(1-k)+k)
    F=.028+(1-.028)*(1-vdoth)**5
    spec=D*Gv*Gl*F/np.maximum(4*ndotl*ndotv,1e-5)*ndotl
    wrap=light.get('diffuse_wrap',0) if kind!='back' else 0
    diffuse_cos=np.maximum((signed_ndotl+wrap)/(1+wrap),0)
    diffuse=base*(diffuse_cos/np.pi)[:,:,None]
    # Source RGB is a reflectance proxy: this is additive fill, not de-lighting.
    specular=np.minimum(spec,.35)[:,:,None]*np.ones_like(base)
    T=geometry['tangent'];th=(T*H).sum(2);tl=(T*L).sum(2)
    lobe=np.maximum(1-th*th,0)**12
    hair_spec=lobe*ndotl*light.get('hair_gloss',.1)*(.25+.75*geometry['coherence'])
    back=np.maximum(-L[:,:,2],0)
    rim=np.exp(-geometry['hair_distance']/light.get('rim_width',.012))
    side=np.maximum((geometry['outward']*L).sum(2),0)
    transmission=back*np.sqrt(np.maximum(1-tl*tl,0))*rim*side*light.get('hair_transmission',.1)
    # Pigment/texture proxy attenuates light in dark fibers. A white scalar
    # emission over the coarse matte made a visible grey fog at the hairline.
    hair_light=(hair_spec*.2+transmission)[:,:,None]*hair[:,:,None]*np.maximum(base,0)**.55
    radiance=diffuse*.8+specular*light.get('specular_strength',.25)*(1-hair[:,:,None])+hair_light
    if kind=='back':
        if 'person_distance' not in geometry:raise ValueError('Back light needs upgraded silhouette geometry')
        edge=np.exp(-geometry['person_distance']/light.get('rim_width',.012))
        side=np.maximum((geometry['person_outward']*L).sum(2),0)
        # Visible silhouette approximation, not recovered hidden backside geometry.
        # Hair is excluded here; the earlier hair-scattering prototype is unchanged.
        nonhair=np.clip((.2-hair)/.2,0,1)
        rim=edge*side*back*light.get('rim_gain',1.0)*nonhair
        radiance=(diffuse*.8+specular*.15)*nonhair[:,:,None]+np.maximum(base,0)**.65*rim[:,:,None]
    scope_name=light.get('scope','all')
    if scope_name=='skin':scope=geometry.get('skin_fill',skin)
    elif scope_name=='all':scope=geometry['scope']
    else:scope=geometry[scope_name]
    if 'lip_mask' in geometry:scope=scope*(1-geometry['lip_mask']*(1-light.get('lip_receive',.8)))
    if 'brow_mask' in geometry:scope=scope*(1-geometry['brow_mask']*(1-light.get('brow_receive',.8)))
    if 'feature_guard' in geometry:scope=scope*(1-geometry['feature_guard'])
    visibility=visible_depth_visibility(geometry,L,P,light)
    return (radiance*attenuation[:,:,None]*visibility[:,:,None]*float(light.get('power',1))*light_rgb(light)*scope[:,:,None]).astype(np.float32)

def _light(base,g,light,P):
    if light.get('enabled',True) is False or light.get('power',1)==0:return np.zeros_like(base)
    if light.get('type','point')!='area':return _contribution(base,g,light,P)
    total=np.zeros_like(base);size=light.get('size',.15)
    grid=int(light.get('area_grid',2));coordinates=(np.arange(grid,dtype=np.float32)+.5)/grid-.5
    for dx in coordinates:
        for dy in coordinates:
            sample=dict(light,type='point',position=(np.asarray(light['position'])+[dx*size,dy*size,0]).tolist())
            total+=_contribution(base,g,sample,P)/(grid*grid)
    return total

def contribution(source,geometry,config,tile=128):
    lights=validate(config);h,w=source.shape[:2];out=np.zeros(source.shape,np.float32)
    prepared=[]
    for light in lights:
        soft=light.get('softness',0)
        if soft>0 and light.get('type')!='back':
            alpha=geometry.get('skin_fill',geometry['scope']) if light.get('scope')=='skin' else geometry['scope']
            sigma=max(.5,max(h,w)*.006*soft/100)
            denom=cv2.GaussianBlur(alpha,(0,0),sigma)
            normal=cv2.GaussianBlur(geometry['normals']*alpha[:,:,None],(0,0),sigma)/np.maximum(denom[:,:,None],1e-6)
            normal[denom<.001]=geometry['normals'][denom<.001]
            prepared.append((light,unit(normal).astype(np.float32)))
        else:prepared.append((light,None))
    for y in range(0,h,tile):
        end=min(h,y+tile);g={key:(v[y:end] if isinstance(v,np.ndarray) and v.ndim>=2 else v) for key,v in geometry.items()}
        g['_occlusion_z']=geometry['z'];g['_occlusion_person']=geometry.get('person',geometry['scope'])
        yy,xx=np.mgrid[y:end,:w].astype(np.float32)
        P=np.stack([(xx-(w-1)/2)/max(h,w),((h-1)/2-yy)/max(h,w),g['z']],2)
        base=linear(source[y:end]);total=np.zeros_like(base)
        for light,normal in prepared:
            specific=dict(g,normals=normal[y:end]) if normal is not None else g
            total+=_light(base,specific,light,P)
        out[y:end]=total
    if not np.isfinite(out).all():raise ValueError('Non-finite light contribution')
    return out

def compose(source,added,config=None,geometry=None):
    """User-requested rollback: exact V1 intensity/display response.

    Config/geometry accepted for API compatibility; no V2 shadow boost,
    chromaticity/gain curve or strength rescaling is applied.
    """
    if not np.any(added):return source.astype(np.float32,copy=True)
    base=linear(source)
    result=srgb(base+(1-base)*(1-np.exp(-np.maximum(added,0))))
    unchanged=np.max(np.abs(added),axis=2)==0;result[unchanged]=source[unchanged]
    return np.clip(result,0,255).astype(np.float32)

def render(source,geometry,config):return compose(source,contribution(source,geometry,config),config,geometry)
