"""Read-only cached-photo planning before any batch edits or exports."""
from pathlib import Path
import copy,shutil
import batch_workflow as batch
import liquify
from develop_output import checked as checked_output
from reshape_settings import KEYS as SHAPE_KEYS

def audit(library,task,cancel=None):
    rows=[];estimated=0
    for index in task['queue']:
        if cancel is not None and cancel.is_set():raise RuntimeError('预检已取消。')
        path=task['paths'][index];row=dict(index=index,source=str(path),errors=[])
        try:
            reader=getattr(library,'state_for_preflight',library.load)
            state=reader(library.key(path))
            document=state['document'];planned=copy.deepcopy(state.get('workflow_extensions',{}))
            if task['sync']:
                requirement=batch.raw_requirement(planned,task['source_extensions'],task['groups'],document.metadata)
                if '全局调色' in task['groups']:
                    for key in ('color','color_filter','reference'):
                        if key in task['source_extensions']:planned[key]=copy.deepcopy(task['source_extensions'][key])
                        else:planned.pop(key,None)
                selected=[g for g in task['groups'] if g in batch.COLOR_GROUPS]
                if selected:batch.sync_color_groups(planned,task['source_extensions'],selected,document.metadata)
                groups=[g for g in task['groups'] if g in batch.GROUPS]
                if groups:
                    if state.get('face_count',len(state['face_settings']))!=len(state['face_settings']):raise ValueError('照片的人物设置不完整，请重新导入后再同步。')
                    values=batch.merge_people(state['face_settings'],task['source'],groups,task['mapping'].get(index,task['person']),task['all_people'])
                    liquid=state.get('liquify_state')
                    locked=state.get('liquify_locked',False) or liquid is not None and (liquify.active(liquid) or liquid['freeze'].any())
                    if locked and any(any(a[k]!=b[k] for k in SHAPE_KEYS) for a,b in zip(values,state['face_settings'])):
                        raise ValueError('已有画笔液化，请先恢复形变与保护，再同步脸型参数。')
                if '打光与改色' in task['groups'] and not state.get('face_settings'):
                    raise ValueError('未识别到人物，无法同步人物打光与改色。')
                required=requirement and requirement.get('raw_base')
                if required and document.is_raw:
                    import camera_profiles
                    meta=document.metadata.get('camera_settings') or camera_profiles.metadata(path)
                    profile=camera_profiles.resolve(meta,required['profile'])[0]
                    if profile is None or not Path(profile['path']).is_file():raise ValueError('缺少此机型的滤镜显影配置，请先导入匹配配置。')
            output=checked_output(planned.get('output',{}))
            if task['export'] and output['hdr'] and task['extension']!='.tif':raise ValueError('此照片启用了 HDR，请使用 TIFF 导出。')
            if task['export']:
                h,w=document.rgb.shape[:2];factor=min(1,task['max_edge']/max(h,w)) if task['max_edge'] else 1
                # Conservative uncompressed bound; framing usually reduces it.
                row['estimated_bytes']=int(w*h*factor*factor*(12 if output['hdr'] else 6 if task['extension']=='.tif' else 3)*1.1)+1024**2
                estimated+=row['estimated_bytes']
            row.update(status='ready',source_precision=document.metadata.get('bit_depth',document.precision),profile=document.metadata.get('profile_name'))
        except (OSError,ValueError,KeyError,RuntimeError) as error:
            row.update(status='blocked',errors=[str(error)])
        rows.append(row)
    disk=None
    if task['export']:
        ancestor=Path(task['folder']).resolve()
        while not ancestor.exists() and ancestor.parent!=ancestor:ancestor=ancestor.parent
        try:
            disk=shutil.disk_usage(ancestor).free
            if disk<estimated:
                for row in rows:row['status']='blocked';row['errors'].append('输出磁盘可用空间低于保守估算（约 '+str(round(estimated/1024**2))+' MB），请调整尺寸或目录。')
        except OSError as error:
            for row in rows:row['status']='blocked';row['errors'].append('输出目录无法检查：'+str(error))
    return dict(passed=all(row['status']=='ready' for row in rows),rows=rows,estimated_bytes=estimated,free_bytes=disk)
