"""Scene-oriented RAW decode, retaining two stops of floating headroom."""
import numpy as np,rawpy
import color_science as cs

def render_scene(path,raw,settings,progress=None):
    if progress:progress('正在解码宽色域浮点RAW…')
    from raw_white_balance import options,provenance
    selected=options(raw,settings)
    xyz=raw.postprocess(output_bps=16,output_color=rawpy.ColorSpace.XYZ,gamma=(1,1),
        **selected,
        no_auto_bright=True,exp_shift=.25,exp_preserve_highlights=0,highlight_mode=5)
    # LibRaw XYZ output is D65. Scaling after underexposed 16-bit decode avoids
    # display clipping, although sensor-clipped channels cannot be invented.
    matrix=(np.linalg.inv(cs.SPACES['ProPhoto'][0])@cs.adaptation(cs.D65,cs.D50)).astype(np.float32)
    scene=(xyz.astype(np.float32)/65535*4)@matrix.T
    scene*=np.exp2(settings['exposure'])
    metadata=dict(camera_source='raw_scene',camera_look_applied=False,bit_depth=16,
        camera_note='线性宽色域RAW · 保留浮点高光余量；相机风格可用兼容显影模式。',
        source_precision='16-bit linear XYZ decode with 2-stop headroom, then FP32',scene_headroom_stops=2,
        **provenance(raw,settings,selected))
    return scene.astype(np.float32),metadata
