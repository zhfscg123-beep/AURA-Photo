"""Continuous gradient/range masks with independently editable local develop."""
import copy,numpy as np,cv2
import color_science as cs
from develop_engine import smoothstep,point_weight
MAX_COMPONENTS=256

EXTRA=[('contrast','对比度',-100,100),('highlights','高光',-100,100),('shadows','阴影',-100,100),('whites','白色色阶',-100,100),('blacks','黑色色阶',-100,100),('vibrance','自然饱和度',-100,100),('clarity','清晰度',-100,100),('dehaze','去朦胧',-100,100),('denoise_luma','明度降噪',0,100),('denoise_chroma','颜色降噪',0,100),('sharpen','锐化',0,150)]
EXTRA+=[('shadow_hue','阴影色相',0,360),('shadow_color','阴影染色',0,100),('shadow_luma','阴影明度',-100,100),('highlight_hue','高光色相',0,360),('highlight_color','高光染色',0,100),('highlight_luma','高光明度',-100,100),('curve_saturation','曲线保色',0,100)]

def reset_section(layer,scope):
    from region_masks import LOCAL_DEFAULTS
    if scope=='mask_range':
        layer.pop('gradient',None);layer.pop('range',None)
        layer['components']=[c for c in layer.get('components',[]) if c['shape']['kind']=='brush']
        if not layer['components']:layer.pop('components',None);layer.pop('component_base',None)
    elif scope=='mask_detail':
        for key,*_ in EXTRA:layer['parameters'][key]=LOCAL_DEFAULTS[key]
    return layer

def checked(layer):
    process=layer.get('color_process',1)
    if type(process) is not int or process not in (1,2):raise ValueError('局部调色版本无效。')
    for name in ('color_recipe','color_preparation'):
        if name in layer:
            from color_presets import checked_recipe
            checked_recipe(layer[name])
            if process!=2:raise ValueError('完整局部配方需使用专业调色。')
    probability=layer.get('mask_alpha')
    if probability is not None:
        if probability.dtype!=np.uint8 or probability.ndim!=2 or min(probability.shape)<1 or max(probability.shape)>1600:raise ValueError('AI 柔边蒙版尺寸或精度无效。')
        if process!=2:raise ValueError('AI 柔边蒙版需使用专业调色。')
    link=layer.get('filter_link')
    if link is not None:
        if not isinstance(link,dict) or set(link)!={'id','amount'} or not isinstance(link['id'],str) or len(link['id'])>80 or type(link['amount']) not in (int,float) or not np.isfinite(link['amount']) or not 0<=link['amount']<=200:raise ValueError('蒙版滤镜联动无效。')
    region=layer.get('ai_region')
    if region is not None:
        if not isinstance(region,dict) or set(region)!={'kind','source','models'} or region['kind'] not in ('person','sky','background') or not isinstance(region['source'],str) or len(region['source'])!=64 or not isinstance(region['models'],list) or any(not isinstance(x,str) or len(x)>80 for x in region['models']):raise ValueError('AI 分区来源记录无效。')
    gradient=layer.get('gradient')
    if gradient is not None:
        if not isinstance(gradient,dict) or gradient.get('kind') not in ('linear','radial') or type(gradient.get('invert',False)) is not bool:raise ValueError('渐变蒙版无效。')
        for k in ('start','end'):
            p=np.asarray(gradient.get(k,[]))
            if p.shape!=(2,) or not np.isfinite(p).all() or np.max(np.abs(p))>4:raise ValueError('渐变位置无效。')
        if np.linalg.norm(np.array(gradient['end'])-gradient['start'])<.001:raise ValueError('渐变范围过小。')
    ranges=layer.get('range',{})
    if not isinstance(ranges,dict) or ranges.get('kind','none') not in ('none','luminance','color'):raise ValueError('范围蒙版类型无效。')
    if ranges.get('kind')=='luminance':
        low,high=ranges.get('low',0),ranges.get('high',1);soft=ranges.get('softness',.1)
        if any(type(x) not in (int,float) or not np.isfinite(x) for x in (low,high,soft)) or not 0<=low<high<=4 or not .001<=soft<=1:raise ValueError('亮度范围无效。')
    if ranges.get('kind')=='color':
        from develop_settings import checked_points
        checked_points([ranges.get('sample',{})])
    if ranges.get('operation','intersect') not in ('intersect','subtract'):raise ValueError('范围蒙版组合无效。')
    components=layer.get('components',[])
    if not isinstance(components,list) or len(components)>MAX_COMPONENTS or type(layer.get('component_base',True)) is not bool:raise ValueError('蒙版组件无效。')
    for component in components:
        if not isinstance(component,dict) or component.get('operation','add') not in ('add','subtract','intersect'):raise ValueError('蒙版组件运算无效。')
        if type(component.get('invert',False)) is not bool:raise ValueError('蒙版组件反转无效。')
        shape=component.get('shape',{});kind=shape.get('kind')
        if kind in ('linear','radial'):
            checked(dict(color_process=2,gradient=shape))
        elif kind in ('color','luminance'):
            checked(dict(color_process=2,range=shape))
        elif kind=='brush':
            points=np.asarray(shape.get('points',[]),float)
            if points.ndim!=2 or points.shape[1]!=2 or not 1<=len(points)<=4096 or not np.isfinite(points).all() or np.max(np.abs(points))>4:raise ValueError('软笔刷路径无效。')
            for key,lo,hi in [('radius',.000001,1),('feather',0,100),('flow',1,100),('density',1,100)]:
                v=shape.get(key,50 if key=='feather' else 100 if key in ('flow','density') else .02)
                if type(v) not in (float,int) or not np.isfinite(v) or not lo<=v<=hi:raise ValueError('软笔刷参数无效。')
        else:raise ValueError('未知蒙版组件。')
    return layer

def alpha(layer,reference,rows=None,prepared=None):
    h,w=reference.shape[:2];a,b=(0,h) if rows is None else rows
    from smart_selection import refine
    from region_masks import soft_edge
    parameters=layer['parameters'];mask=refine(layer['mask'],parameters.get('expand',0)) if prepared is None else prepared
    # Edge feather must be evaluated with a halo rather than each tile edge.
    halo=max(4,int(parameters.get('feather',2))+2);lo=max(0,a-halo);hi=min(h,b+halo)
    weight=soft_edge(mask[lo:hi],parameters.get('feather',2))[a-lo:b-lo].astype(np.float32)
    if layer.get('mask_alpha') is not None:weight*=probability_alpha(layer,reference,a,b)
    gradient=layer.get('gradient')
    if gradient:
        yy,xx=np.mgrid[a:b,:w].astype(np.float32);p=np.stack([xx/max(1,w-1),yy/max(1,h-1)],axis=2)
        start=np.array(gradient['start'],np.float32);end=np.array(gradient['end'],np.float32);delta=end-start
        if gradient['kind']=='linear':g=1-smoothstep(((p-start)*delta).sum(2)/max(1e-8,float(delta@delta)))
        else:
            radius=np.maximum(np.abs(delta),.005);distance=np.linalg.norm((p-start)/radius,axis=2)
            g=1-smoothstep((distance-.4)/.6)
        weight*=1-g if gradient.get('invert',False) else g
    ranges=layer.get('range',{});kind=ranges.get('kind','none')
    if kind!='none':
        linear=cs.decode(reference[a:b]/255)
        if kind=='luminance':
            luminance=linear@np.array([.2126,.7152,.0722],np.float32);low=ranges['low'];high=ranges['high'];soft=ranges['softness']
            r=smoothstep((luminance-low+soft)/soft)*smoothstep((high+soft-luminance)/soft)
        else:r=point_weight(cs.oklab(linear),ranges['sample'])
        weight*=1-r if ranges.get('operation')=='subtract' else r
    if layer.get('components'):weight=components_alpha(weight,layer,reference,a,b)
    if parameters.get('edge_protect',0):weight=np.clip(weight,0,1)**(1+parameters['edge_protect']/100)
    return np.clip(weight*parameters.get('opacity',100)/100,0,1)

def probability_alpha(layer,reference,start,end):
    h,w=reference.shape[:2];prob=layer['mask_alpha'].astype(np.float32)/255;ph,pw=prob.shape
    expand=int(round(layer['parameters'].get('expand',0)));halo=abs(expand)+2;lo=max(0,start-halo);hi=min(h,end+halo)
    xx,yy=np.meshgrid((np.arange(w,dtype=np.float32)+.5)*pw/w-.5,(np.arange(lo,hi,dtype=np.float32)+.5)*ph/h-.5)
    result=cv2.remap(prob,xx,yy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    if expand:
        kernel=np.ones((2*abs(expand)+1,2*abs(expand)+1),np.uint8)
        result=cv2.dilate(result,kernel) if expand>0 else cv2.erode(result,kernel)
    return result[start-lo:end-lo]

def brush_alpha(shape,height,width,start,end):
    points=shape['points'];radius=shape.get('radius',.02)*max(height,width);feather=max(.001,shape.get('feather',50)/100)
    flow=shape.get('flow',100)/100;density=shape.get('density',100)/100
    result=np.zeros((end-start,width),np.float32)
    segments=list(zip(points,points[1:])) if len(points)>1 else [(points[0],points[0])]
    for p,q in segments:
        x0,y0=p[0]*(width-1),p[1]*(height-1);x1,y1=q[0]*(width-1),q[1]*(height-1)
        left=max(0,int(min(x0,x1)-radius-1));right=min(width,int(max(x0,x1)+radius+2))
        top=max(start,int(min(y0,y1)-radius-1));bottom=min(end,int(max(y0,y1)+radius+2))
        if left>=right or top>=bottom:continue
        yy,xx=np.mgrid[top:bottom,left:right].astype(np.float32);dx=x1-x0;dy=y1-y0
        t=np.clip(((xx-x0)*dx+(yy-y0)*dy)/max(1e-8,dx*dx+dy*dy),0,1)
        distance=np.sqrt((xx-x0-dx*t)**2+(yy-y0-dy*t)**2)
        dab=smoothstep((1-distance/max(1,radius))/feather)*flow
        view=result[top-start:bottom-start,left:right];view[:]=np.minimum(density,1-(1-view)*(1-dab))
    return result

def component_alpha(shape,reference,start,end):
    h,w=reference.shape[:2];kind=shape['kind']
    if kind=='brush':return brush_alpha(shape,h,w,start,end)
    if kind in ('linear','radial'):
        yy,xx=np.mgrid[start:end,:w].astype(np.float32);p=np.stack([xx/max(1,w-1),yy/max(1,h-1)],axis=2)
        origin=np.array(shape['start'],np.float32);delta=np.array(shape['end'],np.float32)-origin
        if kind=='linear':weight=1-smoothstep(((p-origin)*delta).sum(2)/max(1e-8,float(delta@delta)))
        else:weight=1-smoothstep((np.linalg.norm((p-origin)/np.maximum(np.abs(delta),.005),axis=2)-.4)/.6)
        return 1-weight if shape.get('invert',False) else weight
    linear=cs.decode(reference[start:end]/255)
    if kind=='color':return point_weight(cs.oklab(linear),shape['sample'])
    lum=linear@np.array([.2126,.7152,.0722],np.float32);soft=shape['softness']
    return smoothstep((lum-shape['low']+soft)/soft)*smoothstep((shape['high']+soft-lum)/soft)

def components_alpha(base,layer,reference,start,end):
    out=base if layer.get('component_base',True) else np.zeros_like(base)
    for item in layer['components']:
        value=component_alpha(item['shape'],reference,start,end);operation=item.get('operation','add')
        if item.get('invert',False):value=1-value
        if operation=='add':out=1-(1-out)*(1-value)
        elif operation=='subtract':out*=1-value
        else:out*=value
    return out

def apply(rgb,layers,reference=None):
    out=rgb;reference=rgb if reference is None else reference
    import creative_color as color
    for layer in layers:
        if layer.get('color_process',1)!=2 or not layer.get('enabled',True) or layer.get('filter_link',{}).get('amount',layer['parameters'].get('strength',100))==0 or layer['parameters'].get('opacity',100)==0:continue
        checked(layer);v=layer['parameters'];data=color.validate(dict(layer.get('color_recipe',{}),process=2));values=data['values']
        values.update({k:value for k,value in v.items() if k in color.DEFAULTS})
        values['texture']=v.get('texture',0);values['clarity']=v.get('clarity',0)
        values['denoise_luma']=max(values['denoise_luma'],v.get('smooth',0)*.75)
        data=color.validate(dict(data,process=2,values=values));source=out
        if layer.get('color_preparation'):source=color.apply(source,color.validate(dict(layer['color_preparation'],process=2)))
        edited=color.apply(source,data)
        result=out.copy()
        from smart_selection import refine
        prepared=refine(layer['mask'],v.get('expand',0))
        for a in range(0,len(out),192):
            b=min(len(out),a+192);weight=alpha(layer,reference,(a,b),prepared)[:,:,None]
            base=cs.decode(out[a:b]/255);changed=cs.decode(edited[a:b]/255)
            result[a:b]=cs.encode(base+(changed-base)*weight*layer.get('filter_link',{}).get('amount',v.get('strength',100))/100)*255
        out=result
    return out
