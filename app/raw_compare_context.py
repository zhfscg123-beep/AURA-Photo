"""Prepare a detached source comparison without changing the live edit state."""
import threading
import numpy as np

def prepare(context,settings,threshold):
    from photo_document import open_document
    from damo_engine import PortraitAISession,inpaint_portrait
    from complexion import small_blemishes
    from editing import Selection
    from person_masks import ensure_body_owners
    from batch_workflow import prepare as prepare_edits
    document=open_document(context.document.path,settings)
    if document.rgb.shape!=context.document.rgb.shape:raise ValueError('来源尺寸不同，无法生成保持局部编辑的对比。')
    old=context.selection
    session=PortraitAISession(document.preview(),threshold)
    if len(session.faces)!=len(context.face_settings):raise ValueError('来源切换后人物数量不同，无法可靠生成调色对比。')
    if session.faces:ensure_body_owners(session)
    selection=Selection(session.ai_auto_mask)
    selection.mask=(selection.mask|(old.mask&~old.auto))&~(old.auto&~old.mask)
    context.document=document;context.session=session;context.selection=selection
    context.small_mask,_=small_blemishes(session)
    context.progress=lambda *_:None;context.cancel=threading.Event()
    context.done_mask=selection.mask.copy()
    context.generated,_=inpaint_portrait(session.original,context.done_mask&~(context.small_mask>0),context.progress,context.cancel,precision=True)
    context.reshape_cache={};context.form_cache=None;context.photo_body_cache={}
    context.generated,context.done_mask,context.form_cache,context.reshape_cache=prepare_edits(context,context.face_settings)
    context.workflow_extensions.pop('fuji_source',None)
    return context
