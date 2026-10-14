"""Registration at the shared CUDA extension point, without altering its owner."""
PIXEL_FUNCTIONS={
 'develop_advanced':['ramp','parametric_curve','point_variance','vignette','grain','denoise_detail','shadow_calibration'],
 'color_workbench_render':['preview','source_coordinates','mapped_source','compose_mapped','drag_preview','drag_display','filter_previews'],
 'local_develop':['component_alpha','brush_alpha','components_alpha','probability_alpha'],
 'develop_optics':['inverse_points'],
 'develop_engine':['point_mask'],
 'liquify_guides':['sample_grid'],
 'photo_body':['inverse_points'],
}

def register():
    from gpu_render import register_pixel_functions
    for module,names in PIXEL_FUNCTIONS.items():register_pixel_functions(module,names)
