"""Dependency-free MCP stdio server for the running AURA desktop host.

Uses newline-delimited UTF-8 JSON-RPC. Never imports Tk or AI runtimes and never
writes logs to stdout. See docs/AURA-MCP.md for tools and canonical paths.
"""
import base64
import json
import sys
from pathlib import Path
from aura_bridge import BridgeClient, MAX_MESSAGE

PROTOCOLS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')


def field(kind, description='', **extra):
    return dict(type=kind, description=description, **extra)


def tool(name, operation, description, properties=None, required=(), readonly=False):
    return dict(name=name, operation=operation, description=description,
                inputSchema=dict(type='object', properties=properties or {}, required=list(required), additionalProperties=False),
                annotations=dict(readOnlyHint=readonly, destructiveHint=False, idempotentHint=readonly, openWorldHint=False))


PATH = field('string','Absolute file path. Outputs must use a new filename.')
POINTS = field('array','Original-image pixel coordinates [x,y].', items=dict(type='array', items=dict(type='number'), minItems=2,maxItems=2),minItems=1,maxItems=2000)
TOOLS = [
    tool('aura_launch',None,'Start the updated AURA desktop host if no live endpoint is available; reuse an existing updated host. This opens the normal AURA window without replacing an older running application.'),
    tool('aura_status','status','Read the actual AURA version, current photo, processing state and parameter revision.',readonly=True),
    tool('aura_list_parameters','catalog','Discover every live control with bounds/options, canonical domains and actions. Paged, 80 controls by default; follow next_offset or filter query by name/title. Canonical values are available through aura_get_parameters.',
         {'query':field('string',default=''),'offset':field('integer',minimum=0,default=0),'limit':field('integer',minimum=1,maximum=500,default=80)},readonly=True),
    tool('aura_get_parameters','parameters','Read current portrait, color, lighting, optics, crop, output, layer, retouch and tool parameters. Prefer paths for focused queries; omit paths for a full reusable recipe.',
         {'paths':field('array',items=dict(type='string'),minItems=1,maxItems=100)},readonly=True),
    tool('aura_set_parameters','set_parameters','Change any current parameter using dot paths. Examples: beauty.whiten; people.0.body_whiten; extensions.color.values.exposure; extensions.people.0.relight.lights.0.power; controls.creative_vars.exposure. Use canonical paths for atomic multi-field changes. Retired controls cannot run.',
         {'changes':field('object','Mapping from parameter dot paths to JSON values.'),'expected_revision':field('integer','Optional optimistic concurrency guard.'),'wait':field('boolean','Wait up to timeout seconds, otherwise return a job id.',default=True),'timeout':field('number',default=45,minimum=0,maximum=300)},('changes',)),
    tool('aura_open','open','Open or switch a photo/RAW or load a .beauty / mobile project using AURA itself.',
         {'path':PATH,'raw_settings':field('object'),'auto_recommend':field('boolean'),'wait':field('boolean',default=True),'timeout':field('number',default=45,minimum=0,maximum=300)},('path',)),
    tool('aura_action','action','Execute a named AURA action from aura_list_parameters.actions, including repair, rescan, render, calibrate, undo and redo.',
         {'name':field('string'),'wait':field('boolean',default=True),'timeout':field('number',default=45,minimum=0,maximum=300)},('name',)),
    tool('aura_preview','preview','Return a PNG preview or native-resolution crop from the completed processing pipeline. box uses [left,top,right,bottom]. A crop no larger than max_edge remains at original pixel scale.',
         {'source':field('string',enum=['processed','original','export'],default='processed'),'box':field('array',items=dict(type='integer'),minItems=4,maxItems=4),'max_edge':field('integer',default=1600,minimum=64,maximum=4096)},readonly=True),
    tool('aura_export','export','Export the current completed photo with AURA crop, color space, bit depth and HDR settings. Refuses to overwrite source or existing output.',
         {'path':PATH,'wait':field('boolean',default=True),'timeout':field('number',default=45,minimum=0,maximum=300)},('path',)),
    tool('aura_save_project','save_project','Save a new editable .beauty project, including masks, parameters and retouch records.',
         {'path':PATH,'wait':field('boolean',default=True),'timeout':field('number',default=45,minimum=0,maximum=300)},('path',)),
    tool('aura_layer','layer','Add, update, select or delete a local adjustment layer. Parameters include gradient/range masks, enabled, name, feature assignment and all local develop values. Use aura_mask for pixels.',
         {'action':field('string',enum=['add','update','select','delete'],default='add'),'index':field('integer'),'name':field('string'),'record':field('object')},()),
    tool('aura_mask','mask','Paint, load, fill, clear or invert a mask. target: selection, layer:N, extension:KEY (effect erasers, beauty include/exclude, cleanup and ownership masks).',
         {'target':field('string'),'action':field('string',enum=['paint','load','fill','clear','invert'],default='paint'),'points':POINTS,'radius':field('number',minimum=1,maximum=1000),'erase':field('boolean',default=False),'path':PATH},('target',)),
    tool('aura_read_mask','mask_read','Read an existing mask as a native-resolution PNG.',{'target':field('string')},('target',),readonly=True),
    tool('aura_liquify','liquify','Apply an original-coordinate liquify stroke with the existing bounded deformation engine and freeze protection.',
         {'points':POINTS,'tool':field('string',enum=['push','bloat','pucker','restore','freeze','thaw','twirl','smooth','push_left'],default='push'),'radius':field('number',minimum=5,maximum=1000),'strength':field('number',minimum=0,maximum=100),'density':field('number',minimum=0,maximum=100),'dose':field('number',minimum=0,maximum=10),'reverse':field('boolean',default=False)},('points',)),
    tool('aura_import_lut','import_lut','Load a supported 3D .cube LUT into the current color settings.',{'path':PATH},('path',)),
    tool('aura_preset','preset','Read, apply or save AURA beauty/color presets; read or apply supported Lightroom XMP mappings. AURA currently cannot export XMP.',
         {'kind':field('string',enum=['beauty','color','xmp']),'action':field('string',enum=['read','apply','save'],default='apply'),'path':PATH,'name':field('string'),'all_people':field('boolean',default=False)},('kind','path')),
    tool('aura_import_reference','reference','Analyze a reference photograph and apply the existing color/tone matching workflow, including supported semantic scopes.',
         {'path':PATH,'scope':field('string',enum=['全图','人物肤色','面部皮肤','身体皮肤','衣物','头发','整个人物','背景'],default='全图'),'color':field('number',minimum=0,maximum=100),'tone':field('number',minimum=0,maximum=100),'wait':field('boolean',default=True),'timeout':field('number',minimum=0,maximum=300,default=45)},('path',)),
    tool('aura_create_regions','regions','Generate per-person AI component masks with the same engine as the desktop UI.',
         {'parts':field('array',items=dict(type='string',enum=['person','skin','body','brows','sclera','iris','lips','teeth','hair','clothes'])),'combine':field('boolean',default=False),'wait':field('boolean',default=True),'timeout':field('number',minimum=0,maximum=300,default=45)},('parts',)),
    tool('aura_media','media','Control every current video/live-photo recipe parameter and file workflow. actions: parameters,set,open,update,preview,export,reset,from_photo,seek,loop,close. Video options: quality,position; live options: platform,video_path.',
         {'module':field('string',enum=['video','live']),'action':field('string',default='parameters'),'values':field('object'),'options':field('object'),'path':PATH,'video_path':PATH,'platform':field('string'),'wait':field('boolean',default=True),'timeout':field('number',minimum=0,maximum=300,default=45)},('module',)),
    tool('aura_wait_job',None,'Wait for a submitted job, or return its current progress after a bounded timeout.',
         {'job_id':field('string'),'timeout':field('number',default=45,minimum=0,maximum=300)},('job_id',),readonly=True),
    tool('aura_cancel_job',None,'Cancel queued work or request cancellation of a running cancellable AI operation. Completion is confirmed by aura_wait_job.',{'job_id':field('string')},('job_id',)),
]


def validate_arguments(arguments, schema):
    if not isinstance(arguments,dict): raise ValueError('Tool arguments must be an object.')
    properties=schema['properties']
    if set(arguments)-set(properties): raise ValueError('Unknown arguments: '+', '.join(sorted(set(arguments)-set(properties))))
    for key in schema.get('required',[]):
        if key not in arguments: raise ValueError('Missing argument: '+key)
    for key,value in arguments.items():
        spec=properties[key];kind=spec['type']
        valid={'string':isinstance(value,str),'object':isinstance(value,dict),'array':isinstance(value,list),
               'boolean':type(value)is bool,'integer':type(value)is int,'number':type(value)in(int,float)}[kind]
        if not valid: raise ValueError('Invalid argument type: '+key)
        if 'enum' in spec and value not in spec['enum']: raise ValueError('Invalid option: '+key)
        if kind in ('number','integer'):
            import math
            if not math.isfinite(value) or 'minimum' in spec and value<spec['minimum'] or 'maximum' in spec and value>spec['maximum']: raise ValueError('Argument out of range: '+key)


def call_tool(client, name, arguments):
    item=next((x for x in TOOLS if x['name']==name),None)
    if item is None: raise ValueError('Unknown tool: '+str(name))
    validate_arguments(arguments,item['inputSchema'])
    if name=='aura_launch':
        import os,subprocess,time
        try:
            job=client.call('status',timeout=2)
            if job.get('state')=='done':
                return dict(content=[dict(type='text',text=json.dumps(job,ensure_ascii=False))],structuredContent=job,isError=False)
        except RuntimeError:pass
        root=Path(__file__).resolve().parent;python=Path(sys.executable)
        windowed=python.with_name('pythonw.exe')
        if windowed.exists():python=windowed
        folder=root/'.aura-data/automation';folder.mkdir(parents=True,exist_ok=True)
        with (folder/'host-start.log').open('ab') as log:
            subprocess.Popen([str(python),str(root/'app.py')],cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                             env=dict(os.environ,PYTHONNOUSERSITE='1'),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:
                job=client.call('status',timeout=1)
                if job.get('state')=='done':return dict(content=[dict(type='text',text=json.dumps(job,ensure_ascii=False))],structuredContent=job,isError=False)
            except RuntimeError:pass
            time.sleep(.2)
        raise RuntimeError('AURA 启动尚未完成；可稍后调用 aura_status，诊断见 .aura-data/automation/host-start.log。')
    elif name=='aura_wait_job': job=client.wait(arguments['job_id'],arguments.get('timeout',45))
    elif name=='aura_cancel_job':
        result=client.request('cancel',id=arguments['job_id'])
        return dict(content=[dict(type='text',text=json.dumps(result,ensure_ascii=False))],structuredContent=result,isError=False)
    else:
        args=dict(arguments);wait=args.pop('wait',True);timeout=args.pop('timeout',45)
        job=client.call(item['operation'],args,wait=wait,timeout=timeout)
    failed=job.get('state')in('failed','cancelled')
    result=job.get('result')
    content=[]
    if isinstance(result,dict) and 'image' in result:
        content.append(dict(type='image',data=result['image'],mimeType=result['mimeType']))
        job=dict(job,result={k:v for k,v in result.items() if k!='image'})
    content.insert(0,dict(type='text',text=json.dumps(job,ensure_ascii=False,allow_nan=False)))
    return dict(content=content,structuredContent=job,isError=failed)


class MCPServer:
    def __init__(self,client=None):
        self.client=client or BridgeClient();self.initialized=False

    def handle(self, request):
        ident=request.get('id') if isinstance(request,dict) else None
        def error(code,message): return dict(jsonrpc='2.0',id=ident,error=dict(code=code,message=message))
        if not isinstance(request,dict) or request.get('jsonrpc')!='2.0' or not isinstance(request.get('method'),str): return error(-32600,'Invalid Request')
        method=request['method'];params=request.get('params',{})
        if not isinstance(params,dict):return error(-32602,'Params must be an object')
        if 'id' not in request:
            # Notifications have no response, including cancellation and initialized.
            return None
        try:
            if method=='initialize':
                requested=params.get('protocolVersion');version=requested if requested in PROTOCOLS else PROTOCOLS[0]
                self.initialized=True
                from aura_version import VERSION
                result=dict(protocolVersion=version,capabilities={'tools':{'listChanged':False}},
                            serverInfo=dict(name='aura',version=VERSION),
                            instructions='Controls the running local AURA. Start with aura_status and aura_list_parameters. Use original-image coordinates; wait for jobs before previews or exports. Retired parameters are read-only. No source photo is overwritten.')
            elif method=='ping': result={}
            elif not self.initialized: return error(-32002,'Server not initialized')
            elif method=='tools/list':
                if params.get('cursor'): raise ValueError('Unknown cursor.')
                result={'tools':[{k:v for k,v in t.items() if k!='operation'} for t in TOOLS]}
            elif method=='tools/call':
                try: result=call_tool(self.client,params['name'],params.get('arguments',{}))
                except Exception as exception: result=dict(content=[dict(type='text',text=str(exception))],isError=True)
            else: return error(-32601,'Method not found')
            return dict(jsonrpc='2.0',id=ident,result=result)
        except (ValueError,TypeError,KeyError) as exception: return error(-32602,str(exception))


def main():
    server=MCPServer()
    source=sys.stdin.buffer;destination=sys.stdout.buffer
    while True:
        line=source.readline(MAX_MESSAGE+1)
        if not line: break
        try:
            if len(line)>MAX_MESSAGE or not line.endswith(b'\n'): raise ValueError('Message too large or missing newline.')
            request=json.loads(line)
            response=server.handle(request)
        except (ValueError,UnicodeError): response=dict(jsonrpc='2.0',id=None,error=dict(code=-32700,message='Parse error'))
        if response is not None:
            destination.write(json.dumps(response,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')+b'\n');destination.flush()


if __name__=='__main__': main()
