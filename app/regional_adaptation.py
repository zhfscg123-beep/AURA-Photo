"""Reduce fitted dark-photo compensation on already bright photographs."""
import copy
import cv2,numpy as np
import color_science as cs
import color_presets as presets

def lightness_sample(rgb,probability,kind,exposure=0):
    h,w=rgb.shape[:2];factor=min(1,320/max(h,w));size=(max(1,round(w*factor)),max(1,round(h*factor)))
    source=cv2.resize(np.asarray(rgb,np.float32),size,interpolation=cv2.INTER_AREA)/255
    weight=cv2.resize(probability,size,interpolation=cv2.INTER_LINEAR)>160
    linear=cs.decode(source)*np.exp2(float(exposure));L=cs.oklab(linear)[:,:,0]
    if kind=='person':
        warm=(source[:,:,0]>source[:,:,1]+.015)&(source[:,:,1]>source[:,:,2]+.005)&(L>.2)&(L<.96)
        if np.count_nonzero(weight&warm)>=12:weight&=warm
    # Median warmth can be dominated by dark brown hair. Use the brighter
    # middle tones for a person, while retaining median scene luminance.
    return float(np.percentile(L[weight],75 if kind=='person' else 50)) if np.count_nonzero(weight)>=8 else None

def adapted(recipe,reference,rgb,probability,kind,exposure=0):
    current=lightness_sample(rgb,probability,kind,exposure)
    if reference is None or current is None or reference['goal']<=reference['source']+.025:return copy.deepcopy(recipe),1.
    # Reference input gets its full calibrated controls. Existing brightness
    # removes the need for the same extra correction; no full-image WB changes.
    amount=float(np.clip((reference['goal']-current)/(reference['goal']-reference['source']),0,1))
    if amount>.985:amount=1.
    neutral=presets.plain(__import__('creative_color').validate({}))
    value=presets.blend(neutral,recipe,amount*100)
    # Reducing all controls also weakens the fitted negative highlight/white
    # protection. Retain that protection and strengthen it on bright inputs.
    if amount<1:
        settings=value['values'];original=recipe.get('values',{})
        settings['highlights']=min(settings.get('highlights',0),max(-100,original.get('highlights',0)-35*(1-amount)))
        settings['whites']=min(settings.get('whites',0),max(-100,min(0,original.get('whites',0))-20*(1-amount)))
    return presets.checked_recipe({key:value[key] for key in recipe}),amount
