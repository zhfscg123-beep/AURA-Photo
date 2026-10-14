"""Bounded caches, resident analyzers and explicit video preview/export jobs."""
import os,json,time,hashlib,threading,queue,traceback,uuid,copy
from pathlib import Path
from collections import OrderedDict
from dataclasses import asdict
from fractions import Fraction
import cv2,numpy as np
from live_media import ROOT,read_movie
from live_beauty import LiveRecipe,VideoBeautifier,prepare_video_frame,orient,rotation,decode_info,video_pts,check_cancel,resize_video
from video_skin import SKIN_REVISION
import video_tracks

FACE_KEYS=('smooth','whiten','slim','jaw','chin_width','chin_length','eye_size','nose_width','mouth_width','redness','skin_warmth')
def face_needed(recipe):return any(getattr(recipe,k) for k in FACE_KEYS) or recipe.texture!=50
def fingerprint(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def bytes_used(value,seen=None):
    seen=set() if seen is None else seen
    if id(value) in seen:return 0
    seen.add(id(value))
    if isinstance(value,np.ndarray):return value.nbytes
    if isinstance(value,dict):return sum(bytes_used(v,seen) for v in value.values())
    if isinstance(value,(tuple,list)):return sum(bytes_used(v,seen) for v in value)
    if type(value).__module__=='core':return bytes_used(vars(value),seen)
    return 0

class ByteCache:
    def __init__(self,limit):self.limit=limit;self.items=OrderedDict();self.bytes=0
    def get(self,key):
        if key not in self.items:return None
        self.items.move_to_end(key);return self.items[key][0]
    def put(self,key,value):
        if key in self.items:self.bytes-=self.items.pop(key)[1]
        size=bytes_used(value)
        if size>self.limit:return value
        self.items[key]=(value,size);self.bytes+=size
        while self.bytes>self.limit:self.bytes-=self.items.popitem(last=False)[1][1]
        return value
    def clear(self):self.items.clear();self.bytes=0

def resize_size(width,height,edge):
    scale=1 if edge is None else min(1,float(edge)/max(width,height))
    return max(2,round(width*scale)),max(2,round(height*scale))
def scaled_track(row,base_size,size):
    sx,sy=size[0]/base_size[0],size[1]/base_size[1];factor=(sx+sy)/2
    result=dict(row)
    if row.get('pose') is not None:
        result['pose']=row['pose'].copy();result['pose'][:,:2]*=[sx,sy]
    p=row.get('profile')
    if p is not None:
        result['profile']={k:(np.asarray(v)*[sx,sy] if k in ('origin','hip') else np.asarray(v)*factor) for k,v in p.items()}
    return result
def track_signature(track):
    h=hashlib.sha256()
    if track.get('face') is not None:h.update(np.ascontiguousarray(track['face']).tobytes())
    for k,v in sorted((track.get('profile') or {}).items()):h.update(np.ascontiguousarray(v).tobytes())
    return h.hexdigest()

class PreviewSession:
    def __init__(self,cache_root=None):
        import av
        self.av=av;self.cache_root=Path(cache_root or Path(os.environ.get('AURA_DATA_DIR',ROOT/'.aura-data'))/'video-preview');self.cache_root.mkdir(parents=True,exist_ok=True)
        self.frames=ByteCache(96*1024**2);self.prepared=ByteCache(48*1024**2);self.results=ByteCache(96*1024**2)
        self.engine=VideoBeautifier(LiveRecipe(0,0,50),tracking=False);self.analyzer=None;self.source=None;self.path=None;self.full_tracks=None;self.local_tracks={};self.segments={};self.loop_result=None
        self.stats={'analyses':0,'preparations':0,'renders':0,'result_hits':0,'decoded_frames':0,'engine_creations':1}
    def close(self):
        if self.source is not None:self.source.close();self.source=None
        if self.analyzer is not None:self.analyzer.close();self.analyzer=None
        self.engine.close();self.frames.clear();self.prepared.clear();self.results.clear()
    def open(self,path,cancel):
        check_cancel(cancel);path=Path(path).resolve()
        if path.suffix.lower() not in ('.mp4','.mov','.m4v'):raise ValueError('当前视频预览支持MP4、MOV和M4V。')
        info=decode_info(path)
        if info['duration'] is None or info['duration']<=0:raise ValueError('无法确认视频时长。')
        if info['duration']>600 or path.stat().st_size>2*1024**3:raise ValueError('预览测试版支持10分钟、2GB以内视频。')
        self.sha=fingerprint(path);check_cancel(cancel)
        if self.source is not None:self.source.close()
        self.source=self.av.open(str(path));self.path=path;self.angle=rotation(read_movie(path));self.info=info
        st=path.stat();self.source_stamp=(st.st_size,st.st_mtime_ns)
        self.width,self.height=(info['height'],info['width']) if self.angle%180 else (info['width'],info['height'])
        stream=self.source.streams.video[0];self.start=float((stream.start_time or 0)*stream.time_base);self.duration=float(info['duration']);self.rate=float(info['rate'])
        self.frames.clear();self.prepared.clear();self.results.clear();self.local_tracks.clear();self.segments.clear();self.full_tracks=None;self.loop_result=None
        self.folder=self.cache_root/self.sha;self.folder.mkdir(exist_ok=True)
        own=self.folder/'tracks.npz';meta=self.folder/'tracks.json'
        candidates=[]
        if own.is_file() and meta.is_file():candidates.append((own,json.loads(meta.read_text(encoding='utf8'))))
        for report in (ROOT/'validation-video-dance').glob('*/测试报告.json'):
            try:
                data=json.loads(report.read_text(encoding='utf8'));track=report.parent/'tracks.npz'
                if data.get('source_sha256')==self.sha and track.is_file():candidates.append((track,{'size':data['output_size'],'version':1}))
            except (ValueError,KeyError,OSError):continue
        if candidates:
            track,meta=candidates[-1];self.full_tracks,self.track_report=video_tracks.load(track);self.track_size=tuple(meta['size']);self.track_times=np.array([r['time'] for r in self.full_tracks])
            if track!=own:
                video_tracks.save(own,self.full_tracks,self.track_report);(self.folder/'tracks.json').write_text(json.dumps({'size':self.track_size,'version':1}),encoding='utf8')
        frame=self.frame(0,960,cancel)
        return {'path':str(path),'duration':self.duration,'rate':self.rate,'size':(self.width,self.height),'cached_full_tracks':self.full_tracks is not None,'frame':frame}
    def _rgb(self,frame,edge):
        rgb=orient(frame.to_ndarray(format='rgb24'),self.angle);size=resize_size(self.width,self.height,edge)
        if size!=(self.width,self.height):rgb=resize_video(rgb,size)
        rgb.flags.writeable=False;self.stats['decoded_frames']+=1
        return {'rgb':rgb,'time':float(frame.time)-self.start,'absolute':float(frame.time),'stamp':round(float(frame.time)*1000000),'size':size}
    def frame(self,t,edge,cancel):
        self.check_source()
        t=max(0,min(self.duration-1/max(1,self.rate),float(t)));key=(round(t*1000000),edge);cached=self.frames.get(key)
        if cached is not None:return cached
        check_cancel(cancel);self.source.seek(round((t+self.start)*1000000),backward=True);found=None
        for frame in self.source.decode(video=0):
            check_cancel(cancel)
            if frame.time is None:continue
            found=frame
            if frame.time>=t+self.start-1e-6:break
        if found is None:raise ValueError('当前位置没有可读取视频帧。')
        result=self._rgb(found,edge);self.frames.put((result['stamp'],edge),result);return self.frames.put(key,result)
    def _analyzer(self):
        if self.analyzer is None:
            from preview_analysis import PreviewAnalyzer
            self.analyzer=PreviewAnalyzer()
        return self.analyzer
    def track(self,frame,cancel):
        if self.full_tracks is not None:
            i=int(np.clip(np.searchsorted(self.track_times,frame['absolute']),0,len(self.full_tracks)-1))
            if i and abs(self.track_times[i-1]-frame['absolute'])<abs(self.track_times[i]-frame['absolute']):i-=1
            return scaled_track(self.full_tracks[i],self.track_size,frame['size'])
        cached=self.local_tracks.get(frame['stamp'])
        if cached is not None:return scaled_track(cached[0],cached[1],frame['size'])
        check_cancel(cancel);row=self._analyzer().analyze(frame['rgb'],frame['absolute']);self.stats['analyses']+=1
        row=video_tracks.finish([row],frame['rgb'].shape[:2])[0][0];self.local_tracks[frame['stamp']]=(row,frame['size']);return row
    def render(self,t,recipe,edge,cancel):
        frame=self.frame(t,edge,cancel);track=self.track(frame,cancel) if video_tracks.needed(recipe) else {'face':None,'pose':None,'profile':None,'shot':0}
        self.engine.previous=None;self.engine.previous_center=None;self.engine.shape.clear()
        return self._render_frame(frame,track,recipe,cancel,preview=edge is not None)
    def _render_frame(self,frame,track,recipe,cancel,cache=True,preview=True):
        recipe.validate();check_cancel(cancel);tick=time.perf_counter();sig=tuple(asdict(recipe).values());tsig=track_signature(track);key=(frame['stamp'],frame['size'],tsig,sig,preview,SKIN_REVISION)
        hit=self.results.get(key) if cache else None
        if hit is not None:self.stats['result_hits']+=1;return dict(hit,cache_hit=True,elapsed=time.perf_counter()-tick)
        working=dict(track)
        if not face_needed(recipe):working['face']=None
        pkey=(frame['stamp'],frame['size'],hashlib.sha256(np.ascontiguousarray(working['face']).tobytes()).hexdigest() if working['face'] is not None else 'none',SKIN_REVISION)
        prepared=self.prepared.get(pkey)
        if prepared is None:
            prepared=prepare_video_frame(frame['rgb'],working);self.prepared.put(pkey,prepared);self.stats['preparations']+=1
        check_cancel(cancel);self.engine.recipe=recipe;self.engine.shape.pixel_preview=preview
        out,mask=self.engine.process(frame['rgb'],frame['absolute']*1000,tracked=working,prepared=prepared);out.flags.writeable=False;self.stats['renders']+=1
        result={'before':frame['rgb'],'after':out,'time':frame['time'],'size':frame['size'],'recipe':asdict(recipe),'face':bool(mask.any()),'face_requested':face_needed(recipe),'body':self.engine.body.last_applied,'elapsed':time.perf_counter()-tick,'cache_hit':False,'render_backend':self.engine.render_trace}
        return self.results.put(key,result) if cache else result
    def loop(self,t,recipe,cancel,progress,duration=3.,fps=15):
        self.check_source()
        start=max(0,min(float(t)-.75,max(0,self.duration-duration)));end=min(self.duration,start+duration);duration=end-start
        key=(round(start*1000000),round(end*1000000),fps);cached=self.segments.get(key)
        signature=(key,tuple(asdict(recipe).values()),SKIN_REVISION)
        if self.loop_result is not None and self.loop_result[0]==signature:return self.loop_result[1]
        if cached is None:
            self.source.seek(round((start+self.start)*1000000),backward=True);frames=[];target=start
            for frame in self.source.decode(video=0):
                check_cancel(cancel)
                if frame.time is None:continue
                relative=frame.time-self.start
                if relative<target-1e-6:continue
                if target>=end-1e-6:break
                value=self._rgb(frame,960);self.frames.put((value['stamp'],960),value);frames.append(value);target+=1/fps
            if not frames:raise ValueError('当前片段没有视频帧。')
            if not video_tracks.needed(recipe):tracks=None
            elif self.full_tracks is not None:tracks=[self.track(f,cancel) for f in frames]
            else:
                tracks=self._analyzer().segment([f['rgb'] for f in frames],[f['absolute'] for f in frames],cancel,progress);self.stats['analyses']+=len(frames)
                for f,row in zip(frames,tracks):self.local_tracks[f['stamp']]=(row,f['size'])
            cached=(frames,tracks);self.segments[key]=cached
            while len(self.segments)>1:self.segments.pop(next(iter(self.segments)))
        frames,tracks=cached
        if video_tracks.needed(recipe) and tracks is None:
            if self.full_tracks is not None:tracks=[self.track(f,cancel) for f in frames]
            else:
                tracks=self._analyzer().segment([f['rgb'] for f in frames],[f['absolute'] for f in frames],cancel,progress);self.stats['analyses']+=len(frames)
                for f,row in zip(frames,tracks):self.local_tracks[f['stamp']]=(row,f['size'])
            self.segments[key]=(frames,tracks)
        if not video_tracks.needed(recipe):tracks=[{'face':None,'pose':None,'profile':None,'shot':0} for f in frames]
        results=[];self.engine.previous=None;self.engine.previous_center=None;self.engine.shape.clear()
        for i,(frame,row) in enumerate(zip(frames,tracks)):
            check_cancel(cancel)
            if i and row['shot']!=tracks[i-1]['shot']:self.engine.previous=None;self.engine.previous_center=None;self.engine.shape.clear()
            results.append(self._render_frame(frame,row,recipe,cancel,cache=False))
            if progress:progress('生成3秒循环画面',i+1,len(frames))
        result={'frames':results,'fps':fps,'start':start,'end':end,'silent':True};self.loop_result=(signature,result);return result
    def export(self,target,recipe,cancel,progress):
        self.check_source()
        target=Path(target).resolve();target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() or target==self.path:raise FileExistsError('导出不覆盖已有文件，请使用新文件名。')
        size=resize_size(self.width,self.height,1920);size=tuple(v//2*2 for v in size)
        if self.full_tracks is None and video_tracks.needed(recipe):
            def report(stage,n,total,frame):
                if progress:progress(stage,n,total)
            self.full_tracks,self.track_report=video_tracks.analyze(self.path,recipe,size,cancel=cancel,progress=report);self.track_size=size;self.track_times=np.array([r['time'] for r in self.full_tracks])
            video_tracks.save(self.folder/'tracks.npz',self.full_tracks,self.track_report);(self.folder/'tracks.json').write_text(json.dumps({'size':size,'version':1}),encoding='utf8')
        stage=target.with_name('.'+target.stem+'-'+uuid.uuid4().hex+'.partial.mp4');pts=[];engine=VideoBeautifier(recipe,tracking=False)
        try:
            with self.av.open(str(self.path)) as src,self.av.open(str(stage),'w',format='mp4',options={'movflags':'+faststart','video_track_timescale':str(src.streams.video[0].time_base.denominator)}) as dst:
                video=src.streams.video[0];out=dst.add_stream('libx264',rate=video.average_rate or self.info['rate']);out.width,out.height=size;out.pix_fmt='yuv420p';out.time_base=out.codec_context.time_base=video.time_base;out.options={'crf':'18','preset':'fast','bf':'0'}
                for attr in ('color_trc','color_primaries','colorspace'):setattr(out.codec_context,attr,1)
                out.codec_context.color_range=1;audio=dst.add_stream_from_template(src.streams.audio[0]) if src.streams.audio else None
                for i,frame in enumerate(src.decode(video=0)):
                    check_cancel(cancel);t=Fraction(frame.pts)*frame.time_base;pts.append(t);rgb=orient(frame.to_ndarray(format='rgb24'),self.angle)
                    if rgb.shape[1::-1]!=size:rgb=resize_video(rgb,size)
                    row=scaled_track(self.full_tracks[i],self.track_size,size) if self.full_tracks is not None else {'face':None,'pose':None,'profile':None,'shot':0}
                    if i==0 or self.full_tracks is not None and row['shot']!=self.full_tracks[i-1]['shot']:engine.previous=None;engine.previous_center=None;engine.shape.clear()
                    image,_=engine.process(rgb,float(t*1000),tracked=row)
                    f=self.av.VideoFrame.from_ndarray(image,format='rgb24');f.pts=frame.pts;f.time_base=frame.time_base;f.duration=frame.duration
                    for packet in out.encode(f):dst.mux(packet)
                    if progress and i%15==0:progress('完整导出1080p',i+1,video.frames)
                for packet in out.encode():dst.mux(packet)
                if audio is not None:
                    with self.av.open(str(self.path)) as ac:
                        for packet in ac.demux(ac.streams.audio[0]):
                            check_cancel(cancel)
                            if packet.dts is None:continue
                            packet.stream=audio;dst.mux(packet)
            if video_pts(stage)!=pts:raise ValueError('导出时间戳改变，结果未发布。')
            check_cancel(cancel);os.rename(stage,target)
            return {'target':str(target),'frames':len(pts),'pts_preserved':True,'size':size,'audio_stream_copy':True,'render_backend':engine.render_trace,'render_frames':dict(engine.render_frames)}
        finally:
            engine.close()
            if stage.exists():stage.unlink()
    def check_source(self):
        if self.path is None:raise ValueError('请先打开视频。')
        st=self.path.stat()
        if (st.st_size,st.st_mtime_ns)!=self.source_stamp:raise ValueError('原视频已在其他软件中改变，请重新打开以刷新缓存。')

class PreviewController:
    """Single owner thread, cancellation and latest job wins; no Tk in worker."""
    def __init__(self,cache_root=None):
        self.condition=threading.Condition();self.pending=None;self.generation=0;self.cancel=threading.Event();self.events=queue.Queue();self.closed=False;self.cache_root=cache_root
        self.thread=threading.Thread(target=self.run,name='AURA-video-preview',daemon=True);self.thread.start()
    def submit(self,kind,*args):
        with self.condition:
            self.cancel.set();self.cancel=threading.Event();self.generation+=1;self.pending=(self.generation,kind,args,self.cancel);self.condition.notify_all();return self.generation
    def stop(self):
        with self.condition:self.cancel.set();self.generation+=1;self.pending=None
    def close(self):
        with self.condition:self.closed=True;self.cancel.set();self.pending=None;self.condition.notify_all()
    def run(self):
        session=PreviewSession(self.cache_root)
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda:self.pending is not None or self.closed)
                    if self.closed:return
                    generation,kind,args,cancel=self.pending;self.pending=None
                def progress(stage,n,total):self.events.put((generation,'progress',(stage,n,total)))
                try:
                    if kind=='open':result=session.open(*args,cancel)
                    elif kind=='source':result=session.frame(*args,cancel)
                    elif kind=='frame':result=session.render(*args,cancel)
                    elif kind=='loop':result=session.loop(*args,cancel,progress)
                    elif kind=='export':result=session.export(*args,cancel,progress)
                    else:raise ValueError('未知视频任务。')
                    self.events.put((generation,kind,{'result':result,'stats':dict(session.stats)}))
                except InterruptedError:self.events.put((generation,'cancelled',None))
                except Exception:self.events.put((generation,'error',traceback.format_exc()))
        finally:session.close()
