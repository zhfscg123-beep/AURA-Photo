"""Compatibility for saved RAW recipes; no AURA-added exposure baseline.

Camera/DCP processing and user exposure remain in camera_profiles.render.
Historical calibration modes still load, but never add their old fixed offset.
"""
REVISION='profile-only-20261011'
MODE='adobe-v1'
CAMERA_MODE='camera-v1'
def correction(path,settings,profile,meta):
    return dict(mode=settings.get('baseline_mode','legacy'),ev=0.,verified=False,
                status='profile_only')
