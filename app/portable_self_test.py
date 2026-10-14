"""Current isolated-runtime smoke and optional real-photo model/export checks."""
import hashlib,json,sys,time,os
from pathlib import Path
from aura_version import VERSION
import numpy as np,cv2,torch,onnxruntime

def main(argv):
    from core import ROOT
    def arg(name):return argv[argv.index(name)+1] if name in argv else None
    report=Path(arg('--report') or ROOT/'install-self-test.json')
    assert Path(sys.base_prefix).resolve()==(ROOT/'runtime').resolve()
    assert all(Path(p).resolve().is_relative_to(ROOT) for p in sys.path if p)
    metadata=json.loads((ROOT/'models-manifest.json').read_text(encoding='utf8'))
    for model in metadata['active_models']:
        assert hashlib.sha256((ROOT/'models'/model['file']).read_bytes()).hexdigest()==model['sha256']
    import camera_profiles,composition
    assert not list((ROOT/'profiles').rglob('*.dcp'))
    import camera_profiles,fuji_profiles
    assert not (ROOT/'assets/fuji-linear-profiles').exists()
    assert not (ROOT/'assets/fujifilm-srgb').exists()
    assert fuji_profiles.presets()[0]==[]
    assert camera_profiles.ROOTS==[ROOT/'profiles']
    rgb=np.arange(90*120*3,dtype=np.float32).reshape(90,120,3)%255
    for angle in (-180,-90,0,90,180):
        assert np.array_equal(composition.apply(rgb,dict(rotation=angle)),np.rot90(rgb,round(angle/90)))
    for angle in (-179,-135,-89,-45,-1,1,45,89,135,179):
        assert np.min(composition.apply(np.ones((240,320,3),np.float32)*100,dict(rotation=angle)))>99.9
    os.environ.setdefault('AURA_DATA_DIR',str(report.parent/'self-test-data'));os.environ['AURA_AUTOSAVE']='0'
    import tkinter as tk
    from app_v3 import App
    root=tk.Tk();root.geometry('1280x850');app=App(root);root.update()
    assert not app.task_progress.winfo_manager()
    app.busy=True;app.enable();root.update();assert app.task_progress.winfo_manager()=='pack'
    app.busy=False;app.enable();root.update();assert not app.task_progress.winfo_manager()
    assert app.crop_angle_control.cget('from')==-180 and app.crop_angle_control.cget('to')==180
    assert len(app.filter_library.items('全部'))>=20 and hasattr(app,'filter_amount_control')
    app.renderer.close();app.feature_renderer.close();app.filter_renderer.close();app.library.close()
    if hasattr(app,'color_workbench'):
        app.color_workbench.display_renderer.close();app.color_workbench.drag_renderer.close()
    # Tcl cancellation leaves each widget's registered-command bookkeeping
    # intact; root.after_cancel would delete child-owned commands twice.
    for timer in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',timer)
    root.destroy()
    result=dict(version=VERSION,edition='AURA Photo standalone GPU + CPU',isolated_runtime=True,python=sys.version,torch=torch.__version__,onnxruntime=onnxruntime.__version__,model_hashes_passed=True,bundled_linear_DCP=0,bundled_film_luts=0,rotation_180=True,idle_progress_hidden=True,explicit_task_progress_visible=True,tk_ui_created=True)
    import color_presets
    for preset in color_presets.BUILTINS:
        adjusted,state=color_presets.apply_preset({},preset)
        color_presets.checked_state(state)
        assert color_presets.restore_base(adjusted,state)==color_presets.plain({})
    result['builtin_filters_and_restore']=len(color_presets.BUILTINS)
    import relight_models,relight_engine,relight_settings
    relight_models.verify()
    import moge_assets
    moge_assets.verify()
    result['geometric_light_imports_and_model_hashes']=True
    result['geometric_light_backend']='MoGe-2 Small'
    import creative_color,color_science,icc_runtime,develop_optics,local_develop
    sample=np.full((30,40,3),100,np.float32)
    changed=creative_color.apply(sample,{'process':2,'values':{'exposure':1}})
    assert changed.mean()>130 and np.isfinite(changed).all()
    working=icc_runtime.working_from_input(sample/255,color_science.icc_profile('sRGB'))
    assert np.max(abs(color_science.to_srgb(working)-sample))<.1
    from lens_profiles import registry,field
    lenses=registry()[0];key=next(k for k in lenses if k=='Sony | FE 35mm f/1.8')
    delta,gain,flags=field(key,1,35,5.6,60,40);assert flags&8 and np.isfinite(delta).all()
    result['professional_color_ICC_Lensfun_offline']=True
    if arg('--input'):
        from photo_document import open_document,export_document,sha256_file
        from damo_engine import PortraitAISession,inpaint_portrait
        from complexion import render_skin
        from person_masks import ensure_body_owners
        from ai_engine import inpaint_selected
        from beauty_settings import neutral_values
        import face_reshape,tifffile
        source=Path(arg('--input'));before=sha256_file(source);doc=open_document(source)
        s=PortraitAISession(doc.preview(),progress=lambda text:print(text,flush=True));assert s.faces
        ensure_body_owners(s)
        repaired,info=inpaint_portrait(s.original,s.ai_auto_mask,precision=True)
        assert np.isfinite(repaired).all() and np.array_equal(repaired[s.ai_auto_mask==0],s.original[s.ai_auto_mask==0])
        base=doc.base_float();output=render_skin(base,s,18,12,50);assert np.isfinite(output).all() and np.any(output!=base)
        if '--relight' in argv:
            from creative_regions import regions
            rig=relight_settings.defaults();rig['enabled']=True
            for lamp in rig['lights'][1:]:lamp['enabled']=False
            masks=regions(s)['people'][0];started=time.perf_counter()
            lighted=relight_engine.apply(base,s,0,masks,rig,lambda text:print(text,flush=True))
            assert lighted.dtype==np.float32 and np.isfinite(lighted).all() and np.any(lighted!=base)
            assert np.array_equal(lighted[~masks['light']],base[~masks['light']])
            result['geometric_light_actual']=dict(passed=True,seconds=time.perf_counter()-started,cache=relight_engine.cache_info())
        g=face_reshape.prepare_geometry(s,0);v=dict(neutral_values(),rs_slim_left=15,rs_slim_right=15)
        field=face_reshape.build_field(g,v,s.faces,0);cache={0:dict(geometry=g,field=field,signature=face_reshape.signature(v))}
        settings=[v]+[neutral_values() for _ in s.faces[1:]];shaped,changed=face_reshape.apply(output,settings,cache);assert changed and np.isfinite(shaped).all()
        patch=cv2.resize(s.original,(256,256));mask=np.zeros((256,256),np.uint8);cv2.circle(mask,(128,128),4,1,-1)
        completed,lama=inpaint_selected(patch,mask,precision=True);assert np.array_equal(completed[mask==0],patch[mask==0]) and np.isfinite(completed).all()
        target=report.with_suffix('.tif');target.unlink(missing_ok=True);export_document(target,shaped,16)
        with tifffile.TiffFile(target) as tif:assert tif.asarray().dtype==np.uint16 and tif.pages[0].tags.get(34675)
        assert before==sha256_file(source)
        result.update(source=str(source),source_unchanged=True,faces=len(s.faces),dimensions=doc.preview().shape[:2],DAMO=info,LaMa=lama,locator=g['locator'],mesh_reshape=True,TIFF16_ICC_export=True)
    if arg('--raw-input'):
        from photo_document import open_document,sha256_file
        path=Path(arg('--raw-input'));digest=sha256_file(path)
        raw=open_document(path)
        assert raw.metadata['raw_engine']=='RawTherapee' and raw.precision==16
        assert raw.raw_settings['exposure']==0 and raw.metadata['raw_baseline']['ev']==0
        assert digest==sha256_file(path)
        result['raw_actual']=dict(engine='RawTherapee',shape=list(raw.rgb.shape),input_profile=raw.metadata['input_profile'],unchanged=True)
    from ai_runtime import RUNTIME
    result['runtime']=RUNTIME.report()
    if torch.cuda.is_available() and os.environ.get('AURA_RENDER_BACKEND','cuda')!='cpu':
        assert not any('GPU 运算回退' in value for value in result['runtime']['fallback_reasons'].values()),result['runtime']['fallback_reasons']
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False),flush=True)
