"""Read motion-photo resources and preserve original MOV auxiliary tracks.

No shell commands or writes to input resources. The MOV writer replaces only
the video track, retaining original audio, timed metadata and movie metadata.
"""
from pathlib import Path
from dataclasses import dataclass
import io,struct,hashlib,re,xml.etree.ElementTree as ET,sys,json,os,subprocess,tempfile
from PIL import Image,ImageOps,ImageCms

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'tools/live-runtime'
if RUNTIME.is_dir() and str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))

def atom(kind,payload):return struct.pack('>I4s',len(payload)+8,kind)+payload

def boxes(data,start=0,end=None):
    end=len(data) if end is None else end;pos=start
    while pos<end:
        if end-pos<8:raise ValueError('媒体容器尾部不完整。')
        size,kind=struct.unpack_from('>I4s',data,pos);header=8
        if size==1:
            if end-pos<16:raise ValueError('媒体容器长尺寸不完整。')
            size=struct.unpack_from('>Q',data,pos+8)[0];header=16
        elif size==0:size=end-pos
        if size<header or pos+size>end:raise ValueError('媒体容器尺寸无效。')
        yield kind,pos,size,header
        pos+=size

def children(data):
    header=next(boxes(data))[3]
    return [(k,data[p:p+n]) for k,p,n,h in boxes(data,header)]

def child(data,kind):
    found=[b for k,b in children(data) if k==kind]
    if len(found)!=1:raise ValueError('媒体结构不受支持：'+kind.decode('ascii','replace'))
    return found[0]

def payload(data):
    k,p,n,h=next(boxes(data));return data[h:n]

def track_type(track):return payload(child(child(track,b'mdia'),b'hdlr'))[8:12]
def track_id(track):
    p=payload(child(track,b'tkhd'));return struct.unpack_from('>I',p,20 if p[0] else 12)[0]
def timescale(box):
    p=payload(box);return struct.unpack_from('>I',p,20 if p[0] else 12)[0]

def offset_map(offset,ranges):
    for lo,hi,new in ranges:
        if lo<=offset<hi:return new+(offset-lo)
    raise ValueError('媒体样本不在数据块内，暂不支持此容器。')

def remap_track(track,ranges):
    containers={b'trak',b'mdia',b'minf',b'stbl'}
    def patch(box):
        kind=box[4:8];p=payload(box)
        if kind in containers:return atom(kind,b''.join(patch(b) for k,b in children(box)))
        if kind in (b'stco',b'co64'):
            count=struct.unpack_from('>I',p,4)[0];width=4 if kind==b'stco' else 8
            if len(p)!=8+count*width:raise ValueError('媒体偏移表损坏。')
            fmt='>I' if width==4 else '>Q'
            values=[offset_map(struct.unpack_from(fmt,p,8+i*width)[0],ranges) for i in range(count)]
            if any(v>0xffffffff for v in values):kind=b'co64';fmt='>Q'
            return atom(kind,p[:8]+b''.join(struct.pack(fmt,v) for v in values))
        return box
    return patch(track)

def sample_chunks(data,track):
    stbl=child(child(child(track,b'mdia'),b'minf'),b'stbl')
    sizes=payload(child(stbl,b'stsz'));fixed,count=struct.unpack_from('>II',sizes,4)
    sizes=[fixed]*count if fixed else list(struct.unpack_from('>'+str(count)+'I',sizes,12))
    mapping=payload(child(stbl,b'stsc'));n=struct.unpack_from('>I',mapping,4)[0]
    runs=[struct.unpack_from('>III',mapping,8+12*i) for i in range(n)]
    tables=[b for k,b in children(stbl) if k in (b'stco',b'co64')]
    if len(tables)!=1:raise ValueError('媒体偏移表不受支持。')
    table=tables[0];p=payload(table);n=struct.unpack_from('>I',p,4)[0];width=4 if table[4:8]==b'stco' else 8
    offsets=[struct.unpack_from('>I' if width==4 else '>Q',p,8+i*width)[0] for i in range(n)]
    result=[];idx=0;run=0
    for i,off in enumerate(offsets,1):
        start=off
        while run+1<len(runs) and runs[run+1][0]<=i:run+=1
        for _ in range(runs[run][1]):
            if idx>=count:raise ValueError('媒体样本数量不一致。')
            size=sizes[idx]
            if off+size>len(data):raise ValueError('媒体样本越界。')
            idx+=1;off+=size
        result.append((start,data[start:off]))
    if idx!=count:raise ValueError('媒体样本缺失。')
    return result

def sample_bytes(data,track):return [b for off,b in sample_chunks(data,track)]

@dataclass
class Movie:
    data:bytes
    moov:bytes
    video:bytes
    movie_scale:int
    video_scale:int
    identifier:str|None
    videos:list
    video_index:int

def read_movie(path,video_index=0):
    path=Path(path)
    if path.stat().st_size>512*1024**2:raise ValueError('测试版仅处理512 MB以内的实况短视频。')
    data=path.read_bytes();parts=list(boxes(data))
    if any(k==b'moof' for k,p,n,h in parts):raise ValueError('测试版暂不支持分片视频。')
    moovs=[data[p:p+n] for k,p,n,h in parts if k==b'moov']
    if len(moovs)!=1:raise ValueError('缺少唯一的MOV/MP4电影头。')
    moov=moovs[0];tracks=[b for k,b in children(moov) if k==b'trak']
    videos=[t for t in tracks if track_type(t)==b'vide']
    if not videos or len(videos)>2:raise ValueError('当前支持一条主视频和最多一条辅助视频。')
    if not 0<=video_index<len(videos):raise ValueError('视频轨道索引无效。')
    video=videos[video_index]
    if b'encv' in video:raise ValueError('不支持加密视频。')
    # The identifier is stored in QuickTime mdta keys/ilst. Parse item indices.
    identifier=None
    for k,b in children(moov):
        candidates=[]
        if k==b'meta':candidates=[b]
        elif k==b'udta':candidates=[x for a,x in children(b) if a==b'meta']
        for meta in candidates:
            header=next(boxes(meta))[3]
            # QT's meta is a plain container; ISO meta adds version/flags.
            start=header+4 if meta[header:header+4]==b'\0'*4 else header
            entries={a:meta[p:p+n] for a,p,n,h in boxes(meta,start)}
            if b'keys' not in entries or b'ilst' not in entries:continue
            keys=payload(entries[b'keys']);num=struct.unpack_from('>I',keys,4)[0];pos=8;index=None
            for i in range(1,num+1):
                size=struct.unpack_from('>I',keys,pos)[0]
                if size<8 or pos+size>len(keys):raise ValueError('元数据索引损坏。')
                if keys[pos+8:pos+size]==b'com.apple.quicktime.content.identifier':index=i
                pos+=size
            if index is not None:
                for tag,p,n,h in boxes(entries[b'ilst'],8):
                    if int.from_bytes(tag,'big')==index:
                        val=payload(child(entries[b'ilst'][p:p+n],b'data'))
                        identifier=val[8:].decode('utf8').strip('\0')
    return Movie(data,moov,video,timescale(child(moov,b'mvhd')),timescale(child(child(video,b'mdia'),b'mdhd')),identifier,videos,video_index)

def auxiliary_fingerprints(movie):
    return [(track_id(t),track_type(t).decode('ascii','replace'),hashlib.sha256(b''.join(sample_bytes(movie.data,t))).hexdigest())
            for k,t in children(movie.moov) if k==b'trak' and track_type(t)!=b'vide']

def replace_video(original,encoded,destination):
    src=read_movie(original)
    paths=list(encoded) if isinstance(encoded,(list,tuple)) else [encoded]
    if len(paths)!=len(src.videos):raise ValueError('每条视频轨道都必须完成美颜，不能保留未处理的辅助视频。')
    donors=[read_movie(p) for p in paths]
    for i,new in enumerate(donors):
        if src.movie_scale!=new.movie_scale or timescale(child(child(src.videos[i],b'mdia'),b'mdhd'))!=new.video_scale:raise ValueError('编码时间基不一致，禁止封装。')
    chunks=[];ranges_src={};ranges_new=[];size=0
    for k,p,n,h in boxes(src.data):
        if k in (b'moov',b'mdat'):continue
        block=src.data[p:p+n];chunks.append(block);size+=n
    # Copy only referenced audio/metadata chunks, byte-for-byte. Old unedited
    # video is excluded, so exporting doesn't double storage for the clip.
    auxiliary=[];payload_size=0
    for k,track in children(src.moov):
        if k!=b'trak' or track_type(track)==b'vide':continue
        ranges=[]
        for off,block in sample_chunks(src.data,track):
            ranges.append((off,off+len(block),size+8+payload_size))
            auxiliary.append(block);payload_size+=len(block)
        ranges_src[track_id(track)]=ranges
    if auxiliary:
        block=atom(b'mdat',b''.join(auxiliary));chunks.append(block);size+=len(block)
    video_tracks={}
    for original_track,new in zip(src.videos,donors):
        ranges_new=[]
        for k,p,n,h in boxes(new.data):
            if k!=b'mdat':continue
            block=atom(b'mdat',new.data[p+h:p+n]);ranges_new.append((p+h,p+n,size+8))
            chunks.append(block);size+=len(block)
        donor=remap_track(new.video,ranges_new)
        # Keep each original ID, display matrix, flags and track relationships.
        donor_parts=dict(children(donor));original_parts=children(original_track)
        donor=atom(b'trak',b''.join(donor_parts[k] if k in (b'mdia',b'edts') and k in donor_parts else b
                                  for k,b in original_parts if k!=b'edts' or b'edts' in donor_parts)
                   +(donor_parts.get(b'edts',b'') if not any(k==b'edts' for k,b in original_parts) else b''))
        video_tracks[track_id(original_track)]=donor
    moov=atom(b'moov',b''.join(video_tracks[track_id(b)] if k==b'trak' and track_type(b)==b'vide'
                             else remap_track(b,ranges_src[track_id(b)]) if k==b'trak' else b for k,b in children(src.moov)))
    destination=Path(destination)
    with destination.open('xb') as out:
        for block in chunks:out.write(block)
        out.write(moov)
    final=read_movie(destination)
    if auxiliary_fingerprints(src)!=auxiliary_fingerprints(final) or src.identifier!=final.identifier:
        raise ValueError('音频或实况元数据校验失败。')
    return {'auxiliary_tracks':auxiliary_fingerprints(final),'content_identifier':final.identifier,'source_moov_metadata_preserved':True,'video_tracks':len(final.videos)}

def open_cover(path):
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:pass
    with Image.open(path) as im:
        exif=im.getexif();note=exif.get_ifd(34665).get(37500,b'')
        if not isinstance(note,bytes):note=b''
        identifier=apple_identifier(note)
        info=dict(im.info);image=ImageOps.exif_transpose(im).convert('RGB')
        icc=info.get('icc_profile')
        profile=info.get('nclx_profile') or {}
        if profile.get('transfer_characteristics') in (16,18):raise ValueError('测试版尚不支持HDR封面。')
        if profile and not icc and (profile.get('color_primaries')!=1 or profile.get('transfer_characteristics')!=13):
            raise ValueError('此HEIC封面缺少可用的SDR ICC配置；测试版暂不支持该色彩配置。')
        if icc:
            image=ImageCms.profileToProfile(image,ImageCms.ImageCmsProfile(io.BytesIO(icc)),ImageCms.createProfile('sRGB'),outputMode='RGB')
        exif[274]=1
        photo_tags=dict(exif.get_ifd(34665));photo_tags[40962]=image.width;photo_tags[40963]=image.height;exif[34665]=photo_tags
        return image,exif.tobytes(),identifier,info

def apple_identifier(note):
    # Apple MakerNote offsets are relative to its own header. Read tag 0x0011
    # specifically; a phone may contain several unrelated UUIDs in other tags.
    if not note.startswith(b'Apple iOS\0') or len(note)<16 or note[12:14] not in (b'MM',b'II'):return None
    order='>' if note[12:14]==b'MM' else '<';count=struct.unpack_from(order+'H',note,14)[0]
    if 16+count*12>len(note):return None
    for i in range(count):
        tag,kind,length,offset=struct.unpack_from(order+'HHII',note,16+i*12)
        if tag!=0x11 or kind!=2:continue
        if length<2 or offset+length>len(note):return None
        value=note[offset:offset+length].rstrip(b'\0')
        if re.fullmatch(rb'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',value):return value.decode('ascii')
    return None

def xmp_bytes(jpeg):
    if not jpeg.startswith(b'\xff\xd8'):raise ValueError('安卓测试版暂时只接受JPEG实况容器。')
    pos=2
    while pos+4<=len(jpeg):
        if jpeg[pos]!=255:break
        marker=jpeg[pos+1]
        if marker in (0xda,0xd9):break
        length=int.from_bytes(jpeg[pos+2:pos+4],'big');end=pos+2+length
        if length<2 or end>len(jpeg):raise ValueError('JPEG标记损坏。')
        value=jpeg[pos+4:end]
        if marker==0xe1 and value.startswith(b'http://ns.adobe.com/xap/1.0/\0'):
            yield value.split(b'\0',1)[1]
        pos=end

def exiftool_read(path,options):
    found=list((ROOT/'tools/exiftool').rglob('exiftool.exe'))
    if not found:raise ValueError('缺少实况原件读取工具 ExifTool。')
    work_root=ROOT/'live-work';work_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='read-',dir=work_root) as scratch:
        work=Path(scratch).resolve()
        if work.parent!=work_root.resolve():raise ValueError('元数据工作目录异常。')
        args=['-charset','filename=UTF8',*options,str(Path(path).resolve())]
        if any('\n' in x or '\r' in x for x in args):raise ValueError('文件名包含不支持的换行符。')
        (work/'read.args').write_text('\n'.join(args)+'\n',encoding='utf8')
        env=os.environ.copy()
        for key in ('LC_ALL','LC_CTYPE','LANG'):env.pop(key,None)
        result=subprocess.run([str(found[0]),'-@','read.args'],cwd=work,capture_output=True,timeout=40,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env=env)
        if result.returncode:raise ValueError('实况元数据读取失败：'+result.stderr.decode('utf8','replace')[-200:])
        return result.stdout

def extract_motion_photo(image,destination):
    path=Path(image)
    if path.stat().st_size>512*1024**2:raise ValueError('实况文件过大。')
    data=path.read_bytes();length=None;stamp=-1
    xmls=list(xmp_bytes(data)) if data.startswith(b'\xff\xd8') else []
    for xml in xmls:
        if b'<!DOCTYPE' in xml:raise ValueError('XMP格式不受支持。')
        root=ET.fromstring(xml)
        for node in root.iter():
            attrs={k.rsplit('}',1)[-1]:v for k,v in node.attrib.items()}
            if attrs.get('Semantic')=='MotionPhoto':length=int(attrs.get('Length','0'))
            if 'MicroVideoOffset' in attrs and length is None:length=int(attrs['MicroVideoOffset'])
            for key in ('MotionPhotoPresentationTimestampUs','MicroVideoPresentationTimestampUs'):
                if key in attrs:stamp=int(attrs[key])
    # A Samsung SEF trailer can follow the video. Let the bundled parser locate
    # the exact binary resource, rather than trusting EOF-relative XMP lengths.
    tags=json.loads(exiftool_read(path,['-j','-n','-Make','-MotionPhoto','-MotionPhotoPresentationTimestampUs','-MicroVideoPresentationTimestampUs']))[0]
    stamp=int(tags.get('MotionPhotoPresentationTimestampUs',tags.get('MicroVideoPresentationTimestampUs',stamp)))
    samsung='samsung' in str(tags.get('Make','')).lower() or b'MotionPhoto_Data' in data
    candidate=data[-length:] if length and 16<=length<len(data) else b''
    if not samsung and candidate[4:8]==b'ftyp':
        try:
            Path(destination).write_bytes(candidate);read_movie(destination);return stamp
        except ValueError:pass
    for tag in (('EmbeddedVideoFile','MotionPhotoVideo') if samsung else ('MotionPhotoVideo',)):
        video=exiftool_read(path,['-b','-'+tag])
        if not video or video[4:8]!=b'ftyp':continue
        Path(destination).write_bytes(video);read_movie(destination);return stamp
    raise ValueError('未找到完整实况视频；普通照片或未支持的厂商格式无法封装。')

def pack_motion_photo(jpeg,video,destination,stamp):
    image=Path(jpeg).read_bytes();movie=Path(video).read_bytes()
    # Remove stale XMP before inserting new container lengths and timing.
    result=image[:2];pos=2
    while pos+4<=len(image):
        if image[pos]!=255 or image[pos+1] in (0xda,0xd9):break
        length=int.from_bytes(image[pos+2:pos+4],'big');end=pos+2+length
        block=image[pos:end]
        if not(block[:2]==b'\xff\xe1' and b'http://ns.adobe.com/xap/1.0/' in block):result+=block
        pos=end
    result+=image[pos:]
    xml=f'''<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:Camera="http://ns.google.com/photos/1.0/camera/" Camera:MotionPhoto="1" Camera:MotionPhotoVersion="1" Camera:MotionPhotoPresentationTimestampUs="{int(stamp)}"><Container:Directory xmlns:Container="http://ns.google.com/photos/1.0/container/"><rdf:Seq><rdf:li rdf:parseType="Resource"><Container:Item xmlns:Item="http://ns.google.com/photos/1.0/container/item/" Item:Mime="image/jpeg" Item:Semantic="Primary" Item:Length="0" Item:Padding="0"/></rdf:li><rdf:li rdf:parseType="Resource"><Container:Item xmlns:Item="http://ns.google.com/photos/1.0/container/item/" Item:Mime="video/mp4" Item:Semantic="MotionPhoto" Item:Length="{len(movie)}"/></rdf:li></rdf:Seq></Container:Directory></rdf:Description></rdf:RDF></x:xmpmeta>'''.encode('utf8')
    app=b'http://ns.adobe.com/xap/1.0/\0'+xml
    with Path(destination).open('xb') as out:out.write(result[:2]+b'\xff\xe1'+struct.pack('>H',len(app)+2)+app+result[2:]+movie)
