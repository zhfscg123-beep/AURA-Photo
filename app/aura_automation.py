"""AURA's local automation facade. All document mutations run on the Tk thread.

Canonical document parameters and the live control registry share the existing
validators, render pipeline, undo history and project format with the GUI.
"""
import base64
import copy
import io
import json
import math
from pathlib import Path
import queue
import time
import tkinter as tk

from aura_bridge import HostBridge

RETIRED = {'wrinkles', 'dark_circles', 'slim', 'double_chin', 'armpit_left', 'armpit_right'}
READ_ONLY = {'filename', 'fileinfo', 'summary', 'status', 'person', 'layer_name', 'device_summary',
             'device_details', 'zoomlabel', 'dpi_summary', 'mode'}


def plain(value):
    import numpy as np
    if isinstance(value, np.ndarray):
        return {'array': True, 'shape': list(value.shape), 'dtype': str(value.dtype)}
    if isinstance(value, np.generic): return value.item()
    if isinstance(value, Path): return str(value)
    if isinstance(value, dict): return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [plain(v) for v in value]
    if value is None or type(value) in (str, int, float, bool): return value
    return str(value)


def merge(base, patch):
    if not isinstance(patch, dict): return copy.deepcopy(patch)
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in patch.items(): out[key] = merge(out.get(key), value)
    return out


def put_path(root, path, value):
    if not isinstance(path, str) or len(path) > 300: raise ValueError('Invalid parameter path.')
    parts = path.split('.')
    node = root
    for part in parts[:-1]:
        if isinstance(node, list): node = node[int(part)]
        else:
            if part not in node: node[part] = {}
            node = node[part]
    if isinstance(node, list): node[int(parts[-1])] = copy.deepcopy(value)
    else: node[parts[-1]] = copy.deepcopy(value)


def check_path(root,path):
    """Reject typos before a validator that intentionally tolerates old metadata."""
    node=root
    parts=path.split('.')
    for index,part in enumerate(parts):
        if isinstance(node,list):
            if not part.isdigit() or not 0<=int(part)<len(node):raise ValueError('参数列表编号无效：'+path)
            node=node[int(part)]
        elif isinstance(node,dict):
            if part not in node:
                # These empty maps have native validators and dynamic records.
                prefix='.'.join(parts[:index])
                if prefix in ('extensions.color.hsl','extensions.color.points','extensions.color.bw_mix'):
                    return
                if path=='extensions.reference':return
                raise ValueError('未知参数路径：'+path)
            node=node[part]
        else:raise ValueError('参数路径不是可编辑对象：'+path)


def widgets(root):
    yield root
    for child in root.winfo_children(): yield from widgets(child)


def variables(obj):
    """Discover variables in dictionaries/lists too (RGB, HSL, lights, curves)."""
    def visit(value, path, depth=0):
        if isinstance(value, tk.Variable): yield path, value
        elif depth < 3 and isinstance(value, dict):
            for key, item in value.items(): yield from visit(item, path + '.' + str(key), depth + 1)
        elif depth < 3 and isinstance(value, (tuple, list)):
            for index, item in enumerate(value): yield from visit(item, path + '.' + str(index), depth + 1)
    for name, value in vars(obj).items():
        if not name.startswith('_'): yield from visit(value, name)


class AutomationController:
    def __init__(self, app):
        self.app = app
        self.bridge = HostBridge()
        self.active = None
        self.revision = 0
        self.worker_error = None
        self.closed = False
        self.app.root.bind('<Destroy>', self.destroyed, add='+')
        self.app.root.after(30, self.pump)

    def destroyed(self, event):
        if event.widget is self.app.root:
            self.closed = True; self.bridge.close()

    def report_error(self, message):
        if self.active is None: return False
        self.worker_error = str(message)
        return True

    def idle(self):
        media_busy = any(w is not None and w.winfo_exists() and w.busy for w in
                         (getattr(self.app,'video_preview_window',None),getattr(self.app,'live_photo_window',None)))
        return not self.app.busy and not self.app._render_pending and not self.app.drag and not media_busy

    def notify_changed(self):
        self.revision += 1

    def pump(self):
        if self.closed: return
        try:
            if self.active:
                ident, operation, result = self.active
                with self.bridge.lock: cancelled = self.bridge.jobs[ident]['cancel_requested']
                if cancelled and self.app.busy and getattr(self.app,'_automation_cancellable',True): self.app.cancel.set()
                if cancelled:
                    for w in (getattr(self.app,'video_preview_window',None),getattr(self.app,'live_photo_window',None)):
                        if w is not None and w.winfo_exists() and w.busy:
                            if hasattr(w,'cancel_task'): w.cancel_task()
                            else: w.cancel.set()
                self.bridge.update(ident, progress=self.app.status.get(), rendering=self.app._render_pending)
                if self.idle():
                    failed = self.worker_error or ('参数渲染失败。' if self.app._render_failed else None)
                    if failed:
                        self.bridge.update(ident, state='failed', error=failed, finished=time.time())
                    elif cancelled and operation not in ('export','save_project'):
                        self.bridge.update(ident, state='cancelled', finished=time.time())
                    else:
                        self.revision += 1 if operation not in ('status', 'catalog', 'parameters', 'preview', 'mask_read') else 0
                        if self.app.document and operation not in ('status','catalog','parameters','preview','mask_read','media'):
                            self.app.commit_edit('MCP · ' + operation)
                        self.bridge.update(ident, state='done', result=plain(result), status=self.status(), finished=time.time(),
                                           cancellation_too_late=bool(cancelled))
                    self.active = None; self.worker_error = None
            # Cancelled queued work must never run later.
            if self.active is None and self.idle():
                try: ident, operation, arguments = self.bridge.queue.get_nowait()
                except queue.Empty: pass
                else:
                    with self.bridge.lock: cancelled = self.bridge.jobs[ident]['cancel_requested']
                    if cancelled:
                        self.bridge.update(ident, state='cancelled', finished=time.time())
                    else:
                        self.worker_error = None
                        self.bridge.update(ident, state='running', started=time.time())
                        self.active = (ident, operation, None)
                        try:
                            result = self.dispatch(operation, arguments)
                            self.active = (ident, operation, result)
                        except Exception as error:
                            self.bridge.update(ident, state='failed', error=str(error), finished=time.time())
                            self.active = None
        except Exception as error:
            if self.active:
                self.bridge.update(self.active[0], state='failed', error=str(error), finished=time.time())
                self.active = None
        if not self.closed: self.app.root.after(30, self.pump)

    def status(self):
        a = self.app
        from aura_version import VERSION
        import gpu_render
        return dict(version=VERSION, instance=self.bridge.instance, revision=self.revision,render_backend=plain(getattr(a,'gpu_render_report',gpu_render.report())),
                    source=str(a.path) if a.path else None, busy=a.busy, rendering=a._render_pending,
                    status=a.status.get(), shape=list(a.document.rgb.shape[:2]) if a.document else None,
                    people=len(a.face_settings), active_face=a.active_face, active_layer=a.active_layer,
                    repair_pending=bool(a.repair_pending()) if a.document else False,
                    shape_pending=bool(a.shape_pending()) if a.document else False,
                    photos=[str(v['path']) for v in a.library.entries.values()], history=plain(a.history[-30:]))

    def require_document(self):
        if not self.app.document: raise ValueError('请先通过 aura_open 打开照片。')

    def bindings(self):
        a = self.app
        by_var = {}
        out = {}
        for path, variable in variables(a):
            if path.split('.')[0] in READ_ONLY or path.split('.')[0].endswith(('_note', '_hint', '_label', '_choice_note')):
                continue
            out[path] = dict(variable=variable, callbacks=[], widgets=[], writable=False)
            by_var.setdefault(str(variable), []).append(path)
        for widget in widgets(a.root):
            if hasattr(widget, 'variable') and hasattr(widget, 'apply_command'):
                for path in by_var.get(str(widget.variable), []):
                    item = out[path]; item.update(writable=True, minimum=widget.lo, maximum=widget.hi,
                                               decimals=widget.decimals, title=widget.title)
                    item['callbacks'].append(('python', widget.apply_command)); item['widgets'].append(widget)
                continue
            try:
                kind = widget.winfo_class()
                key = 'variable' if kind in ('TCheckbutton', 'Checkbutton', 'TRadiobutton', 'Radiobutton', 'Scale', 'TScale') else 'textvariable'
                ref = str(widget.cget(key))
            except tk.TclError: continue
            for path in by_var.get(ref, []):
                if kind not in ('TCheckbutton', 'Checkbutton', 'TRadiobutton', 'Radiobutton', 'TCombobox', 'TEntry', 'Entry', 'Scale', 'TScale'): continue
                item = out[path]; item['writable'] = True; item['widgets'].append(widget)
                if kind == 'TCombobox':
                    choices = list(widget.cget('values'))
                    if choices: item['enum'] = choices
                    item['callbacks'].append(('combo', widget))
                elif kind not in ('TEntry', 'Entry'):
                    try: command = widget.cget('command')
                    except tk.TclError: command = ''
                    if command: item['callbacks'].append(('tcl', command))
        # These nonvisual settings are part of the editable recipe as well.
        for path in ('manual_enabled', 'liquify_enabled', 'overlay', 'mask_overlay', 'split', 'threshold', 'feather', 'radius'):
            if path in out: out[path]['writable'] = True
        for path in RETIRED:
            if path in out: out[path]['writable'] = False
        return out

    def parameters(self):
        a = self.app
        if a.session: a.sync_person_values()
        result = dict(beauty=a.parameters(), people=copy.deepcopy(a.face_settings),
                      active_face=a.active_face, active_layer=a.active_layer,
                      controls={k: v['variable'].get() for k, v in self.bindings().items()},
                      raw=copy.deepcopy(a.document.raw_settings) if a.document else {},
                      extensions=plain(a.workflow_extensions),
                      layers=plain(a.region_layers), patches=copy.deepcopy(a.patches),
                      manual_records=copy.deepcopy(a.manual_records), manual_tools=a.manual_settings(),
                      liquify_tools=a.liquify_settings())
        # Fill neutral canonical values for discoverability, without enabling effects.
        import creative_color, creative_portrait, composition, develop_output, develop_optics, effect_controls, relight_settings
        ext = result['extensions']
        ext.pop('masks', None); ext.pop('assets', None)
        ext['color'] = creative_color.validate(ext.get('color', {}))
        ext['composition'] = composition.checked(ext.get('composition', {}))
        ext['output'] = develop_output.checked(ext.get('output', {}))
        ext['optics'] = develop_optics.checked(ext.get('optics', {}))
        ext['background'] = dict({k: 0 for k, *_ in creative_portrait.BACKGROUND}, **ext.get('background', {}))
        ext['effects'] = {k: dict(enabled=effect_controls.settings(ext, k)[0], opacity=effect_controls.settings(ext, k)[1] * 100) for k in effect_controls.TITLES}
        for i in range(len(a.face_settings)):
            person = ext.setdefault('people', {}).setdefault(str(i), {})
            person.update(creative_portrait.person_values(person))
            if person['relight'] is None: person['relight'] = relight_settings.defaults()
        return plain(result)

    def catalog(self):
        from beauty_settings import RANGES
        from region_masks import LOCAL_RANGES
        bindings = self.bindings()
        controls = []
        for path, item in bindings.items():
            value = item['variable'].get()
            controls.append(dict(path='controls.' + path, value=value,
                type='boolean' if type(value) is bool else 'integer' if type(value) is int else 'number' if type(value) is float else 'string',
                writable=item['writable'], **{k:item[k] for k in ('minimum','maximum','enum','decimals','title') if k in item}))
        return dict(schema=1, controls=controls, beauty={k:dict(minimum=lo,maximum=hi,writable=k not in RETIRED) for k,(lo,hi) in RANGES.items()},
                    layer_parameters={k:dict(minimum=lo,maximum=hi) for k,(lo,hi) in LOCAL_RANGES.items()},
                    canonical=self.parameters(), actions=list(ACTIONS),
                    coordinates='Original image pixels [x,y]; gradients use normalized coordinates.',
                    update='Use dot paths in changes. Lists can be replaced as a whole; indices select existing items. Read revision before a guarded edit.')

    def validate_beauty(self, values):
        from beauty_settings import RANGES
        if not isinstance(values, dict) or set(values) - set(RANGES): raise ValueError('未知美颜参数。')
        for key, value in values.items():
            lo, hi = RANGES[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError('美颜参数超范围：' + key)
            if key in RETIRED and value != 0: raise ValueError('已停用参数不能启用：' + key)

    def set_parameters(self, arguments):
        a = self.app; self.require_document()
        expected = arguments.get('expected_revision')
        if expected is not None and expected != self.revision: raise ValueError('参数版本已变化，请重新读取。')
        changes = arguments.get('changes')
        if not isinstance(changes, dict) or not changes or len(changes) > 2000: raise ValueError('changes 必须为非空路径/值对象。')
        before = self.parameters(); candidate = copy.deepcopy(before); bindings = self.bindings(); control_changes = {}
        allowed = {'beauty','people','extensions','layers','patches','manual_records','manual_tools','liquify_tools','active_face','active_layer','raw'}
        for path, value in changes.items():
            if path.startswith('controls.'):
                name = path[9:]
                if name not in bindings or not bindings[name]['writable']: raise ValueError('控件不存在或只读：' + name)
                item = bindings[name]; old = item['variable'].get()
                if type(old) is bool:
                    if type(value) is not bool: raise ValueError('开关必须为 boolean：' + name)
                elif type(old) in (int, float):
                    if type(value) not in (int, float) or not math.isfinite(value): raise ValueError('需要有限数值：' + name)
                    if type(old) is int and int(value) != value: raise ValueError('需要整数：' + name)
                    if 'minimum' in item and not item['minimum'] <= value <= item['maximum']: raise ValueError('控件参数超范围：' + name)
                elif not isinstance(value, str): raise ValueError('需要字符串：' + name)
                if 'enum' in item and value not in item['enum']: raise ValueError('控件选项无效：' + name)
                if value != old: control_changes[name] = value
            else:
                if path.split('.')[0] not in allowed: raise ValueError('未知参数域：' + path)
                if path.startswith(('extensions.masks', 'extensions.assets')): raise ValueError('蒙版请使用专用接口。')
                check_path(candidate,path)
                put_path(candidate, path, value)
        self.validate_beauty(candidate['beauty'])
        if not isinstance(candidate['people'], list) or len(candidate['people']) != len(a.face_settings): raise ValueError('不能修改人物数量。')
        for values in candidate['people']: self.validate_beauty(values)
        if type(candidate['active_face']) is not int or not 0 <= candidate['active_face'] < max(1,len(a.face_settings)): raise ValueError('人物编号无效。')
        if type(candidate['active_layer']) is not int or not -1 <= candidate['active_layer'] < len(a.region_layers): raise ValueError('蒙版编号无效。')
        import manual_retouch, patch_repair, region_masks, local_develop
        manual_retouch.validate_tools(candidate['manual_tools'])
        manual_retouch.validate_records(candidate['manual_records'], a.document.rgb.shape[:2])
        patch_repair.validate_patches(candidate['patches'], a.document.rgb.shape[:2])
        # The wire form never accepts arrays as replacement masks.
        if len(candidate['layers']) != len(a.region_layers): raise ValueError('请使用 aura_layer 添加或删除蒙版。')
        layers = []
        for old, new in zip(a.region_layers, candidate['layers']):
            rec = copy.deepcopy(new); rec['mask'] = old['mask']; layers.append(rec)
        region_masks.validate_layers(layers, a.document.rgb.shape[:2])
        from reshape_settings import KEYS as SHAPE_KEYS
        if a.liquify_state is not None and (a.liquify_state['flow'].any() or a.liquify_state['freeze'].any()):
            pairs=zip(before['people'],candidate['people']) if a.face_settings else [(before['beauty'],candidate['beauty'])]
            if any(any(old.get(k)!=new.get(k) for k in SHAPE_KEYS) for old,new in pairs) or any(candidate['beauty'].get(k)!=before['beauty'].get(k) for k in SHAPE_KEYS):
                raise ValueError('已有液化或冻结保护；请先恢复液化并清除保护，再改变形变坐标基础。')
        # A read includes neutral templates; write only explicitly changed groups.
        # In particular this must not disable a legacy light rig during a beauty edit.
        ext = copy.deepcopy(a.workflow_extensions)
        touched = {p.split('.')[1] for p in changes if p.startswith('extensions.')}
        if 'extensions' in changes: touched = set(candidate['extensions'])
        for group in touched: ext[group] = copy.deepcopy(candidate['extensions'][group])
        from workflow_extensions import validate_extensions
        ext = validate_extensions(ext, a.document.rgb.shape[:2])
        for group in ('color','composition','optics','output'):
            if group in touched and set(candidate['extensions'][group])-set(before['extensions'][group]):raise ValueError('未知参数字段：'+group)
        if set(candidate['raw'])!=set(before['raw']):raise ValueError('未知 RAW 参数。')
        from photo_document import validate_raw_settings
        raw = validate_raw_settings(candidate['raw'])
        liquid = candidate['liquify_tools']
        if set(liquid) != set(a.liquify_settings()): raise ValueError('液化设置字段无效。')
        for key in ('enabled','guide_face','guide_body','fix_nodes'):
            if type(liquid[key]) is not bool: raise ValueError('液化开关无效。')
        for key,lo,hi in [('radius',5,1000),('strength',0,100),('density',0,100),('rate',0,100)]:
            if type(liquid[key]) not in (int,float) or not math.isfinite(liquid[key]) or not lo <= liquid[key] <= hi: raise ValueError('液化参数无效：'+key)
        if raw != before['raw'] and not a.document.is_raw:raise ValueError('当前照片不是 RAW。')
        if raw != before['raw'] and any(path != 'raw' and not path.startswith('raw.') for path in changes):
            raise ValueError('RAW 重新显影必须独立提交，再修改其他参数。')
        if raw != before['raw']:
            a.open(a.path, raw, preserve=True); return {'changed': list(changes), 'redeveloped': True}
        backup = a.edit_snapshot(); previous = a.edit_index
        a.commit_edit('MCP 修改前')
        try:
            a.face_settings = candidate['people']; a.active_face = candidate['active_face']
            if a.face_settings:
                # beauty is the current person's convenience alias.
                if candidate['beauty'] != before['beauty']: a.face_settings[a.active_face] = candidate['beauty']
                a.load_person_controls()
            else:
                for key,value in candidate['beauty'].items(): getattr(a,key).set(value)
            a.region_layers = layers; a.active_layer = candidate['active_layer']; a.sync_layers()
            a.patches = candidate['patches']; a.manual_records = candidate['manual_records']; a.load_manual_settings(candidate['manual_tools'])
            for key,value in liquid.items():
                name = 'liquify_' + key if key not in ('guide_face','guide_body','fix_nodes') else 'liquify_' + key
                getattr(a,name).set(value)
            a.load_extensions(ext)
            # Execute control callbacks with redraw/render/history coalesced.
            deferred = {}; originals = {}
            for name in ('refresh','refresh_color','draw','record'):
                originals[name] = getattr(a,name)
                setattr(a,name,lambda *args,_name=name,**kwargs: deferred.setdefault(_name,True))
            try:
                callbacks = []
                for name,value in control_changes.items():
                    item = bindings[name]; item['variable'].set(value)
                    for callback in item['callbacks']:
                        if callback not in callbacks: callbacks.append(callback)
                for kind,callback in callbacks:
                    if kind == 'python': callback()
                    elif kind == 'tcl': a.root.tk.call(callback)
                    else: callback.event_generate('<<ComboboxSelected>>')
            finally:
                for name,fn in originals.items(): setattr(a,name,fn)
            # Revalidate callback-produced records before rendering.
            self.validate_beauty(a.parameters())
            validate_extensions(a.workflow_extensions,a.document.rgb.shape[:2])
            color_only=all(path.startswith(('extensions.color','extensions.reference','extensions.output','extensions.optics','controls.creative_vars.','controls.hsl_vars.','controls.curve_vars.','controls.point_color_vars.','controls.bw_vars.')) for path in changes)
            if color_only and a.color_input is not None:a.refresh_color()
            else:a.parameter_apply(a.refresh)
            a.record('MCP 修改参数')
        except Exception:
            if backup is not None:
                a.edit_states.append((backup,'MCP 回滚')); a.restore_edit(len(a.edit_states)-1,'恢复'); a.edit_index = previous
            raise
        return {'changed': list(changes)}

    def dispatch(self, operation, arguments):
        handler = getattr(self, 'op_' + operation, None)
        if handler is None: raise ValueError('未知 AURA 操作：' + operation)
        return handler(arguments)

    def op_status(self, args): return self.status()
    def op_catalog(self, args):
        result=self.catalog();controls=result.pop('controls');result.pop('canonical')
        query=args.get('query','').casefold();offset=args.get('offset',0);limit=args.get('limit',80)
        if not isinstance(query,str) or type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=500:raise ValueError('参数目录查询无效。')
        found=[r for r in controls if query in (r['path']+' '+r.get('title','')).casefold()]
        result.update(controls=found[offset:offset+limit],total=len(controls),writable_total=sum(r['writable'] for r in controls),matched=len(found),offset=offset,next_offset=offset+limit if offset+limit<len(found) else None)
        return result

    def op_parameters(self, args):
        result=self.parameters();paths=args.get('paths')
        if paths is None:return result
        if not isinstance(paths,list) or not 1<=len(paths)<=100 or any(not isinstance(p,str) for p in paths):raise ValueError('paths 需为1–100个参数路径。')
        selected={}
        for path in paths:
            if path.startswith('controls.'): selected[path]=result['controls'][path[9:]];continue
            value=result
            for part in path.split('.'):value=value[int(part)] if isinstance(value,list) else value[part]
            selected[path]=value
        return {'values':selected,'revision':self.revision}
    def op_set_parameters(self, args): return self.set_parameters(args)

    def op_open(self, args):
        path = Path(args['path']).resolve()
        if not path.is_file(): raise ValueError('文件不存在。')
        a = self.app; a._skip_recovery = True
        if 'auto_recommend' in args:
            if type(args['auto_recommend']) is not bool: raise ValueError('auto_recommend 必须为 boolean。')
            a.auto_recommend.set(args['auto_recommend'])
        if path.suffix.lower() in ('.beauty','.zip'): a.load_recipe(path)
        else: a.open(path, args.get('raw_settings'),as_shot_import=args.get('raw_settings') is None)
        return {'source': str(path)}

    def op_action(self, args):
        self.require_document()
        name = args['name']
        if name not in ACTIONS: raise ValueError('未知动作。可用：' + ', '.join(ACTIONS))
        if name=='create_combined_regions': self.app.create_region_masks(True)
        elif name=='apply_face_range': self.app.apply_beauty_range('face')
        elif name=='apply_body_range': self.app.apply_beauty_range('body')
        else: getattr(self.app, ACTIONS[name])()
        return {'action': name}

    def output_path(self, args, suffixes):
        path = Path(args['path']).resolve()
        if path.suffix.lower() not in suffixes: raise ValueError('输出扩展名无效。')
        if self.app.path and path == self.app.path.resolve(): raise ValueError('不能覆盖原照片。')
        if path.exists(): raise ValueError('输出文件已存在，请使用新文件名。')
        path.parent.mkdir(parents=True,exist_ok=True)
        return path

    def op_save_project(self, args):
        self.require_document(); a = self.app; a.flush_parameters()
        if a.shape_pending(): raise ValueError('形变尚未完成。')
        path = self.output_path(args,{'.beauty'})
        from project_io import save_project
        payload = a.project_arguments()
        def ready(_): a.project_path = path; a.record('MCP 保存项目')
        a.work(lambda: save_project(path,**payload),ready,cancellable=False)
        return {'path': str(path)}

    def op_export(self, args):
        self.require_document(); a = self.app; a.flush_parameters()
        if a.repair_pending() or a.shape_pending(): raise ValueError('修复或形变尚未完成，请先 aura_action repair / calibrate。')
        path = self.output_path(args,{'.tif','.tiff','.png','.jpg','.jpeg'})
        from photo_document import export_document
        image = a.prepare_export_image(a.output_float.copy()); options = copy.deepcopy(a.workflow_extensions.get('output',{}))
        a.work(lambda:export_document(path,image,depth=16,options=options),lambda _:a.record('MCP 导出照片'),cancellable=False)
        return {'path':str(path),'shape':list(image.shape),'output':plain(options)}

    def op_preview(self, args):
        self.require_document(); a = self.app; a.flush_parameters()
        from PIL import Image
        from photo_document import to_uint8
        source = args.get('source','processed')
        if source not in ('processed','original','export'): raise ValueError('预览来源无效。')
        rgb = a.document.base_float() if source == 'original' else a.output_float
        if source == 'export': rgb = a.prepare_export_image(rgb)
        box = args.get('box')
        if box is not None:
            h,w = rgb.shape[:2]
            if not isinstance(box,list) or len(box)!=4 or any(type(x)is not int for x in box): raise ValueError('裁切需为整数 [left,top,right,bottom]。')
            x,y,z,t = box
            if not 0<=x<z<=w or not 0<=y<t<=h: raise ValueError('预览裁切超出照片。')
            rgb = rgb[y:t,x:z]
        image = Image.fromarray(to_uint8(rgb)); native = image.size
        edge = args.get('max_edge',1600)
        if type(edge)is not int or not 64<=edge<=4096: raise ValueError('预览 max_edge 需为64–4096。')
        image.thumbnail((edge,edge),Image.Resampling.LANCZOS)
        buf = io.BytesIO(); image.save(buf,format='PNG')
        return dict(image=base64.b64encode(buf.getvalue()).decode('ascii'),mimeType='image/png',
                    native_size=list(native),size=list(image.size),source=source,box=box)

    def op_layer(self, args):
        self.require_document(); a = self.app
        import numpy as np
        from region_masks import LOCAL_DEFAULTS,validate_layers
        action = args.get('action','add')
        layers = copy.deepcopy(a.region_layers)
        if action == 'add':
            layer = dict(name=args.get('name','MCP 局部蒙版'),enabled=True,parameters=dict(LOCAL_DEFAULTS),color_process=2,
                         mask=np.zeros(a.document.rgb.shape[:2],bool))
            layer.update(args.get('record',{})); layer['mask']=np.zeros(a.document.rgb.shape[:2],bool)
            layers.append(layer); selected=len(layers)-1
        else:
            index=args.get('index',a.active_layer)
            if type(index)is not int or not 0<=index<len(layers): raise ValueError('蒙版编号无效。')
            if action=='delete': del layers[index]; selected=min(index,len(layers)-1)
            elif action=='update': layers[index]=merge(layers[index],args.get('record',{})); selected=index
            elif action=='select': selected=index
            else: raise ValueError('蒙版操作无效。')
        validate_layers(layers,a.document.rgb.shape[:2]); a.commit_edit('MCP 蒙版前')
        a.region_layers=layers;a.active_layer=selected;a.sync_layers();a.parameter_apply(a.refresh);a.record('MCP 局部蒙版')
        return {'index':selected,'count':len(layers)}

    def target_mask(self, target, create=False):
        a=self.app
        if target=='selection': return a.selection.mask
        if target.startswith('layer:'):
            index=int(target[6:])
            if not 0<=index<len(a.region_layers): raise ValueError('蒙版编号无效。')
            return a.region_layers[index]['mask']
        if target.startswith('extension:'):
            import numpy as np
            key=target[10:]
            if not key or len(key)>100: raise ValueError('蒙版键无效。')
            masks=a.workflow_extensions.setdefault('masks',{})
            if key not in masks:
                if not create: raise ValueError('蒙版不存在。')
                if len(masks)>=40: raise ValueError('蒙版数量已达上限。')
                masks[key]=np.zeros(a.document.rgb.shape[:2],bool)
            return masks[key]
        raise ValueError('蒙版目标应为 selection、layer:N 或 extension:KEY。')

    def op_mask(self,args):
        self.require_document(); a=self.app
        import numpy as np,cv2
        target=args['target']; action=args.get('action','paint'); a.commit_edit('MCP 绘制蒙版前')
        mask=self.target_mask(target,True)
        if action=='clear': mask.fill(False)
        elif action=='fill': mask.fill(True)
        elif action=='invert': np.logical_not(mask,out=mask)
        elif action=='load':
            from PIL import Image
            with Image.open(args['path']) as im:
                if im.size!=(mask.shape[1],mask.shape[0]): raise ValueError('蒙版图必须与原图尺寸一致。')
                mask[:]=np.asarray(im.convert('L'))>=128
        elif action=='paint':
            points=args['points']; radius=args.get('radius',a.radius.get()); erase=args.get('erase',False)
            if not isinstance(points,list) or not 1<=len(points)<=2000 or type(erase)is not bool: raise ValueError('笔画无效。')
            if type(radius) not in (int,float) or not math.isfinite(radius) or not 1<=radius<=1000: raise ValueError('笔画半径无效。')
            h,w=mask.shape
            if any(not isinstance(p,list) or len(p)!=2 or any(type(v)not in(int,float) or not math.isfinite(v) for v in p) or not 0<=p[0]<w or not 0<=p[1]<h for p in points): raise ValueError('笔画坐标超出原图。')
            stroke=np.zeros(mask.shape,np.uint8); ps=np.rint(points).astype(np.int32)
            for p in ps: cv2.circle(stroke,tuple(p),round(radius),1,-1)
            if len(ps)>1: cv2.polylines(stroke,[ps],False,1,2*round(radius))
            mask[stroke>0]=not erase
        else: raise ValueError('蒙版操作无效。')
        a.parameter_apply(a.refresh);a.record('MCP 绘制蒙版')
        return {'target':target,'pixels':int(mask.sum())}

    def op_mask_read(self,args):
        self.require_document(); mask=self.target_mask(args['target'])
        from PIL import Image
        buf=io.BytesIO(); Image.fromarray(mask.astype('uint8')*255).save(buf,format='PNG')
        return dict(image=base64.b64encode(buf.getvalue()).decode('ascii'),mimeType='image/png',shape=list(mask.shape))

    def op_liquify(self,args):
        self.require_document();a=self.app
        import liquify
        points=args['points']; tool=args.get('tool','push')
        if tool not in liquify.TOOLS or not isinstance(points,list) or not 1<=len(points)<=200: raise ValueError('液化笔画无效。')
        h,w=a.document.rgb.shape[:2]
        if any(not isinstance(p,list) or len(p)!=2 or any(type(v)not in(int,float) or not math.isfinite(v) for v in p) or not 0<=p[0]<w or not 0<=p[1]<h for p in points): raise ValueError('液化坐标无效。')
        radius=args.get('radius',a.liquify_radius.get()); strength=args.get('strength',a.liquify_strength.get())
        density=args.get('density',a.liquify_density.get());dose=args.get('dose',1)
        if any(type(v)not in(int,float) or not math.isfinite(v) or not lo<=v<=hi for v,lo,hi in [(radius,5,1000),(strength,0,100),(density,0,100),(dose,0,10)]): raise ValueError('液化参数无效。')
        state=copy.deepcopy(a.liquify_state) if a.liquify_state is not None else liquify.create((h,w))
        start=points[0]
        for end in points[1:] or [start]:
            liquify.stroke(state,start,end,radius,strength,tool,density=density,dose=dose,reverse=bool(args.get('reverse',False)));start=end
        if liquify.jacobian(state).min()<.18: raise ValueError('液化网格发生折叠。')
        a.commit_edit('MCP 液化前');a.liquify_state=state;a.liquify_enabled.set(True);a.parameter_apply(a.refresh);a.record('MCP 液化笔画')
        return {'tool':tool,'points':len(points)}

    def op_import_lut(self,args):
        self.require_document()
        import creative_color
        lut=creative_color.read_cube(args['path'])
        return self.set_parameters({'changes':{'extensions.color.lut':lut}})

    def op_regions(self,args):
        self.require_document()
        from region_masks import PARTS
        parts=args.get('parts',[])
        if not isinstance(parts,list) or not parts or set(parts)-set(PARTS): raise ValueError('部位名称无效。')
        if not self.app.session.faces: raise ValueError('未识别到可靠人物。')
        for key,var in self.app.part_checks.items(): var.set(key in parts)
        self.app.create_region_masks(bool(args.get('combine',False)))
        return {'parts':parts,'combine':bool(args.get('combine',False))}

    def op_preset(self,args):
        self.require_document();kind=args['kind'];action=args.get('action','apply');a=self.app
        if kind not in ('beauty','color','xmp'):raise ValueError('预设类型无效。')
        path=Path(args['path']).resolve()
        if action=='save':
            path=self.output_path(args,{'.json'})
            if kind=='beauty':
                from beauty_preset import write_preset
                write_preset(path,a.parameters(),args.get('name','MCP 人像参数'))
            elif kind=='color':
                import creative_color
                data=dict(kind='aura-color-style',schema=2,color=creative_color.validate(a.workflow_extensions.get('color',{})),
                          reference=copy.deepcopy(a.workflow_extensions.get('reference',{})),optics=copy.deepcopy(a.workflow_extensions.get('optics',{})))
                with path.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,allow_nan=False,indent=2)
            else:raise ValueError('现有 AURA 不支持导出 XMP。')
            return {'path':str(path)}
        if action not in ('read','apply') or not path.is_file():raise ValueError('预设文件或动作无效。')
        if kind=='beauty':
            from beauty_preset import read_preset
            values,name=read_preset(path);self.validate_beauty(values)
            if action=='read':return {'name':name,'parameters':values}
            changes={'beauty':values}
            if args.get('all_people'):changes={'people.'+str(i):values for i in range(len(a.face_settings))} or changes
            return self.set_parameters({'changes':changes})
        if kind=='xmp':
            from xmp_color_style import read
            values,report=read(path)
            if action=='read':return {'color':values,'report':report}
            result=self.set_parameters({'changes':{'extensions.color':values}});result['report']=report;return result
        if path.stat().st_size>2_000_000:raise ValueError('预设过大。')
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if data.get('kind')!='aura-color-style' or data.get('schema')not in(1,2):raise ValueError('调色预设格式无效。')
        import creative_color
        changes={'extensions.color':creative_color.validate(data['color'])}
        if data.get('reference'):changes['extensions.reference']=data['reference']
        if 'optics'in data:changes['extensions.optics']=data['optics']
        if action=='read':return {'parameters':changes}
        ref=data.get('reference',{})
        if ref.get('target_roi') is not None or ref.get('target_person') is not None:
            raise ValueError('参考追色区域属于原照片，请在目标照片重新确认。')
        return self.set_parameters({'changes':changes})

    def op_reference(self,args):
        self.require_document();a=self.app;scope=args.get('scope','全图');path=Path(args['path']).resolve()
        from reference_regions import SCOPES
        if scope not in SCOPES or not path.is_file():raise ValueError('参考图或范围无效。')
        color=args.get('color',a.reference_color.get());tone=args.get('tone',a.reference_tone.get())
        if any(type(x)not in(int,float) or not math.isfinite(x) or not 0<=x<=100 for x in (color,tone)):raise ValueError('追色强度无效。')
        def job():
            from photo_document import open_document
            from creative_color import statistics
            rgb=open_document(path).base_float();mask=None
            if scope!='全图':
                import cv2
                import numpy as np
                from reference_regions import ReferenceSession,diagnostic
                from creative_regions import regions
                factor=min(1,1800/max(rgb.shape[:2]));rgb=cv2.resize(rgb,(round(rgb.shape[1]*factor),round(rgb.shape[0]*factor)))
                session=ReferenceSession(np.clip(np.rint(rgb),0,255).astype(np.uint8),.35,a.progress)
                if not session.faces:raise ValueError('参考图未识别到人像，请选择全图取样。')
                mask=a.region_for_reference(regions(session),scope)
                diagnostic(mask,rgb.shape[:2])
            return statistics(rgb,mask)
        def ready(stats):
            a.workflow_extensions['reference']=dict(stats=stats,scope=scope,name=path.name,color=color,tone=tone)
            a.sync_creative_color_ui();a.parameter_apply(a.refresh);a.record('MCP 参考图追色')
        a.work(job,ready);return {'path':str(path),'scope':scope}

    def op_media(self,args):
        module=args['module'];action=args.get('action','parameters');a=self.app
        if module not in ('video','live'): raise ValueError('媒体模块无效。')
        if module=='video': a.show_video_preview();window=a.video_preview_window
        else: a.show_live_photo();window=a.live_photo_window
        if window.busy: raise ValueError('媒体模块正在处理，请先等待。')
        if action=='parameters':
            return {'values':{k:v.get() for k,v in window.variables.items()},
                    'recipe':plain(__import__('dataclasses').asdict(window.recipe())),
                    'status':window.status.get(),
                    'options':{'quality':window.quality.get(),'position':window.position.get()} if module=='video' else {'platform':window.platform.get(),'image_path':window.image_path.get(),'video_path':window.video_path.get()}}
        if action=='set':
            from live_beauty import LiveRecipe
            values={k:v.get() for k,v in window.variables.items()};changes=args.get('values',{})
            if not isinstance(changes,dict) or set(changes)-set(values): raise ValueError('媒体参数名称无效。')
            values.update(changes);LiveRecipe(**values).validate()
            options=args.get('options',{})
            if not isinstance(options,dict):raise ValueError('媒体选项无效。')
            # Validate the whole request before any variable changes.
            if module=='video':
                if set(options)-{'quality','position'}:raise ValueError('视频选项无效。')
                if 'quality' in options and options['quality'] not in ('快速预览 · 540p','原始清晰度 · 当前帧'):raise ValueError('预览质量无效。')
                if 'position' in options:
                    pos=options['position'];duration=window.info['duration'] if window.info else 0
                    if type(pos)not in(int,float) or not math.isfinite(pos) or not 0<=pos<=duration:raise ValueError('时间位置无效。')
            else:
                if set(options)-{'platform','video_path'}:raise ValueError('实况选项无效。')
                if 'platform' in options and options['platform']not in('iPhone 配对照片＋MOV','安卓 JPEG／HEIC 实况照片'):raise ValueError('实况平台无效。')
                if 'video_path' in options and not Path(options['video_path']).is_file():raise ValueError('配对视频不存在。')
            for key,value in changes.items():window.variables[key].set(value)
            if module=='video':
                if set(options)-{'quality','position'}: raise ValueError('视频选项无效。')
                if 'quality' in options:
                    if options['quality'] not in ('快速预览 · 540p','原始清晰度 · 当前帧'):raise ValueError('预览质量无效。')
                    window.quality.set(options['quality'])
                if 'position' in options:
                    p=options['position'];duration=window.info['duration'] if window.info else 0
                    if type(p)not in(int,float) or not math.isfinite(p) or not 0<=p<=duration:raise ValueError('时间位置无效。')
                    window.position.set(p)
                window.parameters_changed()
            else:
                if set(options)-{'platform','video_path'}:raise ValueError('实况选项无效。')
                if 'platform' in options:
                    if options['platform'] not in ('iPhone 配对照片＋MOV','安卓 JPEG／HEIC 实况照片'):raise ValueError('实况平台无效。')
                    window.platform.set(options['platform'])
                if 'video_path' in options:
                    if not Path(options['video_path']).is_file():raise ValueError('配对视频不存在。')
                    window.video_path.set(str(Path(options['video_path']).resolve()))
            return {'changed':list(changes),'options':options}
        if action=='open':
            path=Path(args['path']).resolve()
            if not path.is_file():raise ValueError('媒体文件不存在。')
            if module=='video':window.open_video(path)
            else:
                window.image_path.set(str(path))
                if args.get('video_path'):window.video_path.set(str(Path(args['video_path']).resolve()))
                if args.get('platform'):
                    if args['platform']not in('iPhone 配对照片＋MOV','安卓 JPEG／HEIC 实况照片'):raise ValueError('实况平台无效。')
                    window.platform.set(args['platform'])
                window.load_cover()
            return {'path':str(path)}
        if action=='update':
            if module=='video':
                if not window.info:raise ValueError('请先打开视频。')
                window.recipe().validate();window.update_frame()
            else:
                if window.original is None:raise ValueError('请先打开封面。')
                window.recipe().validate();window.preview()
        elif action=='export':
            if module=='video':
                if not window.info:raise ValueError('请先打开视频。')
                target=self.output_path(args,{'.mp4'});window.recipe().validate();window.submit('export',str(target),window.recipe())
                return {'path':str(target)}
            else:
                from live_beauty import process_live
                target=Path(args['path']).resolve()
                if target.exists():raise ValueError('实况输出目录已存在。')
                recipe=window.recipe();recipe.validate()
                image=window.image_path.get();video=window.video_path.get() if window.platform.get().startswith('iPhone') else None
                if not image or window.platform.get().startswith('iPhone') and not video:raise ValueError('实况原件不完整。')
                def progress(stage,n,total,frame):window.events.put(('progress',(stage,n,total,None)))
                window.start(lambda:('export',(target,process_live(image,video,target,recipe,window.cancel,progress))))
                return {'path':str(target)}
        elif action=='reset':window.reset()
        elif action=='from_photo':window.from_photo()
        elif action=='seek' and module=='video':window.seek()
        elif action=='loop' and module=='video':window.prepare_loop()
        elif action=='close':window.close()
        elif action=='preview':
            from PIL import Image
            rgb=(window.current or {}).get('after') if module=='video' else window.result
            if rgb is None:raise ValueError('请先更新媒体预览。')
            im=Image.fromarray(rgb);im.thumbnail((1600,1600));buf=io.BytesIO();im.save(buf,format='PNG')
            return {'image':base64.b64encode(buf.getvalue()).decode('ascii'),'mimeType':'image/png'}
        else:raise ValueError('媒体动作无效。')
        return {'module':module,'action':action}


ACTIONS = dict(repair='run_repair',scan='scan',render='refresh',undo='undo',redo='redo',
               reset_selection='reset',recommend='apply_defaults',calibrate='prepare_shape',
               create_combined_regions='create_combined_regions', reset_liquify='reset_liquify',
               clear_liquify_protection='clear_liquify_protection',reset_color='reset_global_color',
               reset_composition='reset_composition',scene_clean='run_scene_clean',assign_body_mask='assign_body_mask',
               apply_face_range='apply_face_range',apply_body_range='apply_body_range',
               face_details='prepare_details',body_details='prepare_body_controls',forms='prepare_form_controls',
               fit='fit',actual='actual')


def attach(app):
    """Called only after the UI has initialized all parameter providers."""
    app.automation = AutomationController(app)
    return app.automation
