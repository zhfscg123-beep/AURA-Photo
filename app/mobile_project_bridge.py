"""Read portable Android projects with deterministic semantic parameter translation."""
from pathlib import Path
import json,hashlib,io,zipfile,re,struct
import numpy as np,cv2
from PIL import Image
from core import ROOT
from beauty_settings import neutral_values
from photo_document import open_document,sha256_file

FACE={'low':'low_smooth','evenLight':'even_light','evenColor':'skin_even','oil':'oil','gloss':'gloss','clarity':'clarity','redness':'redness','warmth':'skin_temp','tint':'skin_tint','translucent':'skin_translucent','hydrate':'skin_hydrate','fill':'skin_fill','shadow':'skin_shadow','forehead':'wr_forehead','glabella':'wr_glabella','eyes':'wr_eyes','mouth':'wr_mouth','cheek':'wr_cheek','bags':'eye_bags'}
BODY={'smooth':'body_smooth','highFrequency':'body_hf','lowFrequency':'body_lf','hydrate':'body_hydrate','whiten':'body_whiten','translucent':'body_translucent','even':'body_even','toFace':'body_to_face','redness':'body_redness','warmth':'body_temp','tint':'body_tint','neckLines':'neck_wrinkles','fineLines':'stretch_marks','clavicle':'clavicle','sampleMatch':'sample_body','colorMatch':'color_body','brightMatch':'match_body_bright','spots':'body_spots','moles':'body_moles'}
EXTRA={'slimLeft':'rs_slim_left','slimRight':'rs_slim_right','jawLeft':'rs_jaw_left','jawRight':'rs_jaw_right','chinWidth':'rs_chin_width','eyeLeftSize':'fs_eye_left_size','eyeRightSize':'fs_eye_right_size','eyeLeftWidth':'fs_eye_left_width','eyeRightWidth':'fs_eye_right_width','eyeLeftHeight':'fs_eye_left_height','eyeRightHeight':'fs_eye_right_height','eyeLeftTilt':'fs_eye_left_tilt','eyeRightTilt':'fs_eye_right_tilt','upperLip':'fs_upper_lip','lowerLip':'fs_lower_lip','mouthHeight':'fs_mouth_height','sampleMatch':'sample_face','paletteMatch':'color_face','brightMatch':'match_face_bright','highFrequency':'face_hf','common':'skin_match','beardProtect':'beard_protect','makeupProtect':'makeup_protect','jawEnhance':'jaw_enhance','textureKeep':'texture_keep','features':'stereo_features','contour':'stereo_contour','foreheadVolume':'vol_forehead','midfaceVolume':'vol_midface','cheekVolume':'vol_cheek','nosebaseVolume':'vol_nosebase','eyeLeftVolume':'vol_eye_left','eyeRightVolume':'vol_eye_right','innerEyeVolume':'vol_eye_inner','browVolume':'vol_brow','chinVolume':'vol_chin','cornerVolume':'vol_corner','nasoLeft':'wr_naso_left','nasoRight':'wr_naso_right','noseWrinkle':'wr_nose','marionette':'wr_marionette','lipLines':'lip_lines','blemish':'blemish_all','moles':'moles','sweat':'sweat','noseDebris':'nose_debris','beardRemove':'beard_remove'}
for zone in ('forehead','midface','nosebase','chin'):
    for operation in ('Flat','Light'):EXTRA[zone+operation]='vol_'+zone+'_'+operation.lower()
def parameters(recipe):
    result=neutral_values()
    for key in ('smooth','whiten','texture'):result[key]=float(recipe.get(key,.5 if key=='texture'else 0))*100
    for field,mapping in [('face',FACE),('bodySkin',BODY)]:
        for key,target in mapping.items():result[target]=float(recipe.get(field,{}).get(key,0))*100
    result['rs_chin_length']=float(recipe.get('chin',0))*100
    for key,target in [('slimBody','body_slim'),('waist','waist_slim'),('slimLegs','leg_slim'),('longLegs','leg_length')]:result[target]=float(recipe.get(key,0))*50
    for key,target in [('width','fs_face_width'),('eyeSpacing','fs_eye_distance'),('noseWidth','fs_nose_width'),('noseLength','fs_nose_height'),('mouthWidth','fs_mouth_width'),('smile','fs_smile')]:result[target]=float(recipe.get('shape',{}).get(key,0))*100
    for key,value in recipe.get('desktop',{}).get('values',{}).items():
        short=key.split('.',1)[-1]
        if short in EXTRA:result[EXTRA[short]]=float(value)*100
    d=recipe.get('desktop',{});result['skin_choice']=int(d.get('paletteFace',0));rgb=int(d.get('sampleFace',0));result.update(sample_r=rgb>>16&255,sample_g=rgb>>8&255,sample_b=rgb&255)
    from beauty_settings import RANGES
    for key,(lo,hi)in RANGES.items():result[key]=float(np.clip(result[key],lo,hi))
    return result
def read_mobile_project(path):
    from damo_engine import MODEL_HASH
    with zipfile.ZipFile(path)as archive:
        info=archive.getinfo('recipe.json');assert info.file_size<=32*1024**2
        data=json.loads(archive.read(info));assert data['kind']=='aura-mobile-photo'and data['schema']in(1,2,3,4)
        ident=data['sourceHash'];assert re.fullmatch('[0-9a-f]{64}',ident)
        folder=(ROOT/'outputs/android-projects'/ident).resolve();assert folder.is_relative_to(ROOT.resolve());folder.mkdir(parents=True,exist_ok=True)
        suffix=Path(data.get('sourceName','source.jpg')).suffix.lower()
        if suffix not in ('.jpg','.jpeg','.png','.webp','.tif','.tiff','.arw','.raf','.nef','.cr2','.cr3','.dng'):suffix='.jpg'
        source=folder/('source'+suffix);entry=archive.getinfo('source.image');assert entry.file_size<=150*1024**2
        if not source.exists():
            temporary=folder/'source.new'
            with archive.open(entry)as incoming,temporary.open('wb')as out:
                for block in iter(lambda:incoming.read(65536),b''):out.write(block)
            assert sha256_file(temporary)==ident;temporary.replace(source)
        assert sha256_file(source)==ident
        origin=None
        if data.get('hasDesktopOrigin'):
            item=archive.getinfo('desktop-origin.beauty');assert item.file_size<=170*1024**2
            original=folder/'desktop-origin.beauty'
            with archive.open(item)as incoming,original.open('wb')as out:
                for block in iter(lambda:incoming.read(65536),b''):out.write(block)
            from project_io import read_project
            origin=read_project(original)
            assert origin[0]['source_sha256']==ident and origin[0]['shape']==list(open_document(source,origin[0]['raw_settings']).rgb.shape[:2])
        recipe=data['recipe'];d=recipe.get('desktop',{});profile=d.get('rawProfile','')
        if profile:
            assert re.fullmatch('[0-9a-f]{64}',profile);raw_profile=archive.read('profile.dcp');assert len(raw_profile)<=20_000_000 and hashlib.sha256(raw_profile).hexdigest()==profile;(folder/'camera.dcp').write_bytes(raw_profile)
        settings=dict(white_balance=('camera','auto','daylight')[d.get('rawWhiteBalance',0)],exposure=d.get('rawExposure',0),camera_look=False)
        document=open_document(source,settings);h,w=document.rgb.shape[:2]
        def image(name):
            info=archive.getinfo(name);assert info.file_size<=2*1024**2
            with Image.open(io.BytesIO(archive.read(info)))as picture:assert picture.size==(512,512);return np.asarray(picture.convert('RGBA'))
        def mask(name,channel=0):
            rgba=image(name);value=rgba[:,:,channel].astype(np.float32)/255*rgba[:,:,3]/255
            return cv2.resize(value,(w,h),interpolation=cv2.INTER_LINEAR)>.05
        masks=dict(selected=mask('face.png')|mask('body.png'),automatic=np.zeros((h,w),bool),processed=np.zeros((h,w),bool),small=np.zeros((h,w),bool),region_layers=[],liquify=None)
        extensions=dict(masks={},people={},effects={},color={},composition={})
        for index in range(max(1,len(data.get('people',{})))):
            for scope,target in [('face','beauty'),('body','body-beauty')]:
                name=f'mask-person-{index}-{scope}.png'
                if name not in archive.namelist():name=scope+'.png'
                extensions['masks'][f'{target}-include-{index}']=mask(name,0);extensions['masks'][f'{target}-exclude-{index}']=mask(name,1)
        values={key:float(recipe.get('color',{}).get(key,0))*100 for key in ('contrast','highlights','shadows','whites','blacks','vibrance')};values.update(exposure=recipe.get('exposure',0),temperature=recipe.get('warmth',0)*100,saturation=recipe.get('saturation',0)*100)
        curve=d.get('curves',{});extensions['color']=dict(values=values,points={key:[[point['x'],point['y']]for point in points]for key,points in curve.items()})
        extensions['color']['values'].update(tint=d.get('globalTint',0)*100,skin_protect=d.get('skinProtect',0)*100,lut_strength=d.get('lutStrength',0)*100)
        extensions['color']['hsl']={name:[row.get(k,0)*100 for k in ('hue','saturation','light')]for name,row in zip(('红','橙','黄','绿','青','蓝','紫','洋红'),recipe.get('color',{}).get('hsl',[]))}
        cube=d.get('lut')or data.get('luts',{}).get(d.get('lutKey',''))
        if cube:
            n=cube['size'];assert 2<=n<=33
            table=np.asarray(cube['values'],np.float32).reshape(n,n,n,3)
            extensions['color']['lut']=dict(size=n,cube=table.tolist(),min=[0,0,0],max=[1,1,1],name=cube.get('title','移动端 LUT'))
        crop=recipe.get('crop',{});left=crop.get('left',0);right=crop.get('right',1);top=crop.get('top',0);bottom=crop.get('bottom',1);extensions['composition']=dict(ratio='自定义',center_x=(left+right)*50,center_y=(top+bottom)*50,size=100,rotation=crop.get('angle',0),quarter=0,locked=False,width=(right-left)*100,height=(bottom-top)*100,custom_ratio=crop.get('ratio',1)or 1)
        style=recipe.get('style',{})
        for index in range(max(1,len(data.get('people',{})))):
            p=data.get('people',{}).get(str(index),recipe);s=p.get('style',style);record={key:float(s.get(value,0))*100 for key,value in [('lip','lipStrength'),('blush','blushStrength'),('hair','hairStrength'),('clothes_color','clothStrength')]}
            for key,value in [('lip_rgb','lipRgb'),('blush_rgb','blushRgb'),('hair_rgb','hairRgb'),('clothes_rgb','clothRgb')]:rgb=int(s.get(value,0));record[key]=[rgb>>16&255,rgb>>8&255,rgb&255]
            extensions['people'][str(index)]=record
        extensions['assets']={};extensions['mobile_cached_patches']=[]
        total_cache=0;cache_base=document.base_float()
        for i,patch in enumerate(data.get('patches',[])):
            if patch['kind']=='clone':continue
            a,b,c,e=map(int,patch['rect']);assert 0<=a<c<=w and 0<=b<e<=h and c-a<=512 and e-b<=512
            entry=archive.getinfo(patch['file']);assert entry.file_size<=2*1024**2
            with Image.open(io.BytesIO(archive.read(entry)))as picture:
                assert picture.size==(c-a,e-b);rgba=np.asarray(picture.convert('RGBA')).astype(np.float32)
            delta=(rgba[:,:,:3]-cache_base[b:e,a:c])*rgba[:,:,3:4]/255
            total_cache+=delta.nbytes;assert total_cache<=512*1024**2
            key=f'mobile-cache-{i}';extensions['assets'][key]=delta
            person=data.get('people',{}).get(str(patch.get('owner',-1)),recipe);desktop=person.get('desktop',{});kind=patch['kind'];extra=desktop.get('values',{})
            strength={'face':max(desktop.get('faceRepair',0),extra.get('face.blemish',0),extra.get('face.moles',0)),'body':max(desktop.get('bodyRepair',0),person.get('bodySkin',{}).get('spots',0),person.get('bodySkin',{}).get('moles',0)),'wrinkle':desktop.get('wrinkleRepair',0),'beard':extra.get('face.beardRemove',0),'nose':extra.get('face.noseDebris',0),'sweat':extra.get('face.sweat',0),'clean':extra.get('retouch.neural',0),'tattoo':extra.get('retouch.neural',0)}.get(kind,0)
            extensions['mobile_cached_patches'].append(dict(asset=key,box=[a,b,c,e],strength=float(strength),kind=kind,owner=patch.get('owner',-1)))
        layers=[]
        for item in d.get('layers',[]):
            key='mask-layer-'+item['id']+'.png';assert key in archive.namelist()
            matte=mask(key);parameters_local={name:item.get(field,default)*scale for name,field,scale,default in [('exposure','exposure',1,0),('temperature','warmth',100,0),('tint','tint',100,0),('saturation','saturation',100,0),('texture','texture',100,0),('smooth','smooth',100,0),('opacity','opacity',100,1)]}
            parameters_local.update(expand=item.get('expand',0)*16*max(w,h)/512,feather=item.get('feather',.2)*12*max(w,h)/512)
            parameters_local['expand']=float(np.clip(parameters_local['expand'],-100,100));parameters_local['feather']=float(np.clip(parameters_local['feather'],0,100))
            layers.append(dict(id=item['id'],name=item['name'],enabled=item.get('enabled',True),mask=matte,parameters=parameters_local))
        masks['region_layers']=layers
        manual=[]
        import manual_retouch
        stroke_ids=[]
        for stroke in d.get('clones',[]):
            stroke_ids.append(stroke.get('stroke',0))
            manual.append(dict(manual_retouch.DEFAULT_TOOLS,mode='heal'if stroke.get('heal')else'clone',enabled=stroke.get('enabled',True),points=[[stroke['x']*w,stroke['y']*h]],source=[stroke['sx']*w,stroke['sy']*h],radius=stroke['radius']*w,opacity=stroke.get('opacity',1)*100,flow=stroke.get('flow',1)*100,hardness=stroke.get('hardness',.35)*100,scale=stroke.get('scale',1)*100,angle=stroke.get('angle',0),flip_x=stroke.get('flipX',False),flip_y=stroke.get('flipY',False)))
        # A saved .beauty uses stroke records, so group dabs rather than dropping them.
        if any(stroke_ids) or len(manual)>300:
            grouped=[];last_id=None
            for record,stroke_id in zip(manual,stroke_ids):
                key={k:v for k,v in record.items()if k not in ('points','source')};offset=np.array(record['source'])-np.array(record['points'][0]);last=grouped[-1]if grouped else None
                if last and len(last['points'])<2000 and all(last[k]==v for k,v in key.items()) and stroke_id==last_id and np.allclose(manual_retouch.source_point(last,record['points'][0]),record['source'],atol=.05):last['points']+=record['points']
                else:grouped.append(record)
                last_id=stroke_id
            manual=grouped
        manual_retouch.validate_records(manual,(h,w))
        if 'liquid.bin'in archive.namelist():
            raw=archive.read('liquid.bin');n=struct.unpack('>i',raw[:4])[0];assert n==129 and len(raw)==4+n*n*12;flow=np.frombuffer(raw[4:4+n*n*8],'>f4').reshape(n,n,2).astype(np.float32);frozen=np.frombuffer(raw[4+n*n*8:],'>f4').reshape(n,n).astype(np.float32);assert np.isfinite(flow).all()and np.isfinite(frozen).all()
            import liquify
            state=liquify.create((h,w));gh,gw=state['freeze'].shape;state['flow']=cv2.resize(flow,(gw,gh),interpolation=cv2.INTER_LINEAR);state['flow'][:,:,0]*=w;state['flow'][:,:,1]*=h;state['freeze']=cv2.resize(frozen,(gw,gh));masks['liquify']=state
        meta=dict(schema=9,app_version='0.30.0-android.5',source=str(source),source_sha256=ident,shape=[h,w],parameters=parameters(recipe),threshold=.35,defaults=neutral_values(),repair_model_sha256=MODEL_HASH,raw_settings=settings,face_settings=[],patches=[],manual_records=manual,manual_enabled=True,extensions=extensions)
        if origin is not None:
            old_meta,old_masks=origin
            supported=set(FACE.values())|set(BODY.values())|set(EXTRA.values())|{'smooth','whiten','texture','rs_chin_length','body_slim','waist_slim','leg_slim','leg_length','fs_face_width','fs_eye_distance','fs_nose_width','fs_nose_height','fs_mouth_width','fs_smile','skin_choice','sample_r','sample_g','sample_b'}
            translated=meta['parameters'];merged=dict(old_meta['parameters']);merged.update({k:translated[k]for k in supported if k in translated});meta={**old_meta,**meta,'parameters':merged}
            # Keep original records outside the phone's current editable parameter set.
            old_extensions=old_meta.get('extensions',{})
            new_extensions=meta['extensions'];combined={**old_extensions,**new_extensions}
            for key in ('assets','masks','people','effects','clean_records'):
                combined[key]={**old_extensions.get(key,{}),**new_extensions.get(key,{})}
            meta['extensions']=combined
            previous=old_meta.get('manual_records',[])
            if previous:
                merged_manual=previous+meta.get('manual_records',[])
                if len(merged_manual)>300:raise ValueError('桌面与手机合计超过300笔，需分项目保存；原项目已保留。')
                meta['manual_records']=merged_manual
            for layer in masks['region_layers']:
                match=re.fullmatch('Mdesktop([0-9]+)',layer.get('id',''))
                if not match:continue
                index=int(match.group(1));original_layers=old_masks.get('region_layers',[])
                if index>=len(original_layers):continue
                original=original_layers[index];thumbnail=cv2.resize(original['mask'].astype(np.uint8),(512,512),interpolation=cv2.INTER_NEAREST)
                mobile_name='mask-layer-'+layer['id']+'.png'
                if np.array_equal(image(mobile_name)[:,:,0]>127,thumbnail>0):layer['mask']=original['mask']
                for key in ('id','feature_key','person_index'):
                    if key in original:layer[key]=original[key]
                if layer['name']==original['name'][:60]:layer['name']=original['name']
            meta['desktop_origin_preserved']=True
        # Preserve mobile-only data for a later round trip; it is not silently reinterpreted.
        meta['mobile_origin']=data
        return meta,masks
