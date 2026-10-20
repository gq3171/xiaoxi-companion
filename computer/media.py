"""Prepare real task media on NVMe; serve bounded JPEG/PCM packets to the panel.

No URL fetching or model calls. The caller supplies an existing task file and
owns cancellation. Manifests are published only after conversion and checks.
"""
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time

ID=re.compile(r'^[0-9a-f]{32}$')
FPS=8
PCM_RATE=16000
MAX_PACKET=60*1024
MAX_SECONDS=1800
MAX_SOURCE=256*1024*1024

TASK_RULE='''\n主人要求图片、音乐或视频结果时，取得真实可访问的媒体文件，保存在本任务work_directory内并检查文件内容；普通网页链接或空文件不等于媒体。
完成时可附media=[{"path":"工作目录内相对文件路径","title":"简短名称"}]，最多四项；服务会转换成小屏幕支持的图像与声音格式，不需自行生成播放数据。先评估用途与可读性：照片/插画适合小屏，密集图表、长文档/表格应交简短摘要并保留原文件；需要看细节的视频不靠缩小假装可读。可另制清晰局部图或分段摘要，清楚说明取舍。保留声音/视频原文件；板端是320x240、8fps、16kHz单声道预览，不是高清/高保真播放。只交付实际文件，不宣称已经在板上播放。'''
BRAIN_RULE='''\n仅当设备本轮状态包含media_protocol=1时，支持屏幕媒体查看。主人明确要查看已取得的媒体，可action=speak并附media_action=show；明确要播放可media_action=play，可附media_index为1至4的实际列表序号；暂停用pause，退出用close。不凭空说已经打开或播放，等待设备实际处理。服务端实际媒体清单按顺序提供；只有唯一一项或标题明确匹配时附media_index，否则先展示列表供选择。
需要新查找图片、音乐或视频时，用computer_task交给电脑取得实际媒体文件，并在任务里要求以media清单交付；未取得实际文件就如实说明。自主生活不打开、播放或获取媒体。
先根据主人目标和本轮实际硬件决定呈现：照片/插画可展示；音乐在允许发声且非静音时播放；音量为0或安静策略禁止时，不输出media_action=play，先说明当前静音不会播放、可调高音量后开始，不能说可能听不到却直接开播；密集图表、长文档/表格先口述重点并保留原文件，需要细节可请电脑裁出清晰部分。高速或细节密集视频在320x240/8fps只作预览，明确限制，不能声称完整体验。安静/休息/低电量或网络差优先短摘要、静态预览或稍后播放，不替主人取消任务。不能凭空提供手机投屏/下载地址/外部显示器。
当前播放器回执只证明设备已展示或送到扬声器，不证明主人看见/听见；中断/静音不说播放完成。模型决定意义和呈现，设备核验实际能力。'''


MEDIA_PROBE='/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABcQERQRDhcUEhQaGBcbIjklIh8fIkYyNSk5UkhXVVFIUE5bZoNvW2F8Yk5QcptzfIeLkpSSWG2grJ+OqoOPko3/2wBDARgaGiIeIkMlJUONXlBejY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY3/wAARCADwAUADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFgEBAQEAAAAAAAAAAAAAAAAAAAQG/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AngImlAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf/9k='

class MediaUnavailable(ValueError):pass


def finish_media(store,job,workspace,reply,cancelled=lambda:False):
    message=str(reply.get('message') or '任务结束，未提供说明。')
    entries=reply.get('media',[])
    if reply.get('state')!='succeeded' or not entries:return message
    if not isinstance(entries,list) or len(entries)>4:raise MediaUnavailable('媒体结果清单无效')
    for entry in entries:
        if not isinstance(entry,dict):raise MediaUnavailable('媒体结果需要实际文件记录')
        store.update(job,'running','文件已取得，正在准备屏幕可查看或播放的版本。')
        store.media.prepare(job,workspace,entry.get('path'),entry.get('title',''),cancelled)
    return message


def available_media(computer):
    if computer is None or not getattr(computer,'media',None):return '\n服务端实际媒体清单：本轮未连接媒体目录。'
    try:
        rows=computer.media.catalog()
        allowed=('title','kind','duration_ms','has_audio','source_width','source_height','fps')
        items=[dict(index=i+1,**{k:r[k] for k in allowed if k in r}) for i,r in enumerate(rows)]
        return '\n服务端实际媒体清单（仅文件已准备，不代表已播放）：'+json.dumps(items,ensure_ascii=False)
    except (ValueError,OSError,KeyError):
        return '\n服务端实际媒体清单：本次读取失败，不猜文件内容。'


def media_rpc(store,path,request):
    if path=='/v1/computer/media_probe':return dict(ok=True,frame=MEDIA_PROBE,synthetic=True)
    if path=='/v1/computer/media_list':return dict(ok=True,media=store.media.catalog(request.get('job_id')))
    if path=='/v1/computer/media_chunk':return store.media.chunk(request.get('job_id'),request.get('id'),request.get('index'))
    return None


def run(argv, cancelled=lambda:False, timeout=180, budget=512*1024*1024, output=None):
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(argv,stdout=output if output else subprocess.DEVNULL,stderr=errors,start_new_session=True)
        deadline=time.monotonic()+timeout
        try:
            while process.poll() is None:
                if cancelled():raise MediaUnavailable('媒体准备已停止')
                if time.monotonic()>deadline:raise MediaUnavailable('媒体准备超时，未发布半成品')
                if output and os.fstat(output.fileno()).st_size>budget:raise MediaUnavailable('媒体超过空间预算')
                time.sleep(.05)
            if process.returncode:raise MediaUnavailable('媒体无法解码或转换，原文件仍保留')
            if output and os.fstat(output.fileno()).st_size>budget:raise MediaUnavailable('媒体超过空间预算')
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL);process.wait()


class MediaStore:
    def __init__(self, root):
        self.root=Path(root)

    def directory(self, job):
        if not isinstance(job,str) or not ID.fullmatch(job):raise MediaUnavailable('媒体任务编号无效')
        return self.root/job

    def manifest(self,job):
        path=self.directory(job)/'manifest.json'
        if not path.exists():return []
        if path.is_symlink() or path.stat().st_size>16384:raise MediaUnavailable('媒体目录记录不可用')
        rows=json.loads(path.read_text())
        if not isinstance(rows,list) or len(rows)>4:raise MediaUnavailable('媒体目录超过预算')
        return rows

    def catalog(self,job=None):
        jobs=[job] if job else [p.parent.name for p in sorted(self.root.glob('*/manifest.json'),key=lambda x:x.stat().st_mtime,reverse=True)[:8]]
        rows=[]
        for key in jobs:
            for row in self.manifest(key):
                rows.append({k:row[k] for k in ('id','job_id','title','kind','frames','fps','duration_ms','has_audio')})
                rows[-1].update({k:row[k] for k in ('source_width','source_height') if k in row})
                if len(rows)==4:return rows
        return rows

    def prepare(self,job,workspace,relative,title='',cancelled=lambda:False):
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):raise MediaUnavailable('媒体转换程序尚未安装')
        base=Path(workspace).resolve()
        if not isinstance(relative,str) or not relative or '\x00' in relative:raise MediaUnavailable('需要实际媒体文件')
        requested=Path(relative)
        if requested.is_absolute():
            try:requested=requested.relative_to(base)
            except ValueError:raise MediaUnavailable('媒体不在任务工作目录')
        if any(x in ('..','.') for x in requested.parts) or not requested.parts:raise MediaUnavailable('媒体路径无效')
        # Walk without following symlinks; copy a stable file into private NVMe
        # before exposing it to ffmpeg. The model cannot nominate config files.
        descriptor=os.open(base,os.O_RDONLY|os.O_DIRECTORY)
        source=None
        try:
            for part in requested.parts[:-1]:
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor);os.close(descriptor);descriptor=child
            source=os.fdopen(os.open(requested.parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor),'rb')
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=MAX_SOURCE:raise MediaUnavailable('媒体文件类型或大小不支持')
            directory=self.directory(job);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            with tempfile.TemporaryDirectory(prefix='.prepare-',dir=directory) as scratch:
                scratch=Path(scratch);original=scratch/'input';digest=hashlib.sha256()
                with original.open('wb') as out:
                    for block in iter(lambda:source.read(256*1024),b''):
                        if cancelled():raise MediaUnavailable('媒体准备已停止')
                        if out.tell()+len(block)>MAX_SOURCE:raise MediaUnavailable('媒体文件超过空间预算')
                        digest.update(block);out.write(block)
                after=os.fstat(source.fileno())
                if (info.st_mtime_ns,info.st_size)!=(after.st_mtime_ns,after.st_size):raise MediaUnavailable('媒体文件正在变化，请先完成保存')
                asset=hashlib.sha256((job+digest.hexdigest()).encode()).hexdigest()[:32]
                existing=self.manifest(job)
                for row in existing:
                    if row['id']==asset:return row
                if len(existing)>=4:raise MediaUnavailable('每项任务最多四个媒体结果')
                with tempfile.TemporaryFile() as probe:
                    run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_streams','-show_format','-of','json',str(original)],cancelled,30,1024*1024,probe)
                    probe.seek(0);meta=json.load(probe)
                streams=meta.get('streams',[]);video=next((s for s in streams if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')),None)
                audio=next((s for s in streams if s.get('codec_type')=='audio'),None)
                if not video and not audio:raise MediaUnavailable('文件没有可播放的图像或声音')
                image=bool(video and not audio and video.get('codec_name') in ('png','mjpeg','webp','bmp','tiff') and video.get('nb_frames','1')=='1')
                duration=float(meta.get('format',{}).get('duration') or (video or audio).get('duration') or 0)
                if not math.isfinite(duration) or duration<0 or (not image and not 0<duration<=MAX_SECONDS):raise MediaUnavailable('媒体时长未知或超过三十分钟')
                command=['ffmpeg','-nostdin','-v','error','-threads','2','-protocol_whitelist','file,pipe','-i',str(original)]
                frames=scratch/'frames.mjpg';pcm=scratch/'audio.pcm'
                if video:
                    video_args=['-map','0:v:0','-an','-vf',('' if image else 'fps=8,')+'scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2:black','-c:v','mjpeg','-q:v','6','-pix_fmt','yuvj420p']
                    if image:video_args+=['-frames:v','1']
                    with frames.open('wb') as output:run(command+video_args+['-f','image2pipe','pipe:1'],cancelled,180,256*1024*1024,output)
                if audio:
                    with pcm.open('wb') as output:run(command+['-map','0:a:0','-vn','-ac','1','-ar','16000','-f','s16le','pipe:1'],cancelled,180,64*1024*1024,output)
                offsets=[]
                if video:
                    # ffmpeg-produced MJPEG contains no untrusted EXIF previews.
                    with frames.open('rb') as data:
                        offset=0;pending=b''
                        while block:=data.read(65536):
                            pending+=block
                            while (end:=pending.find(b'\xff\xd9'))>=0:
                                size=end+2
                                if not pending.startswith(b'\xff\xd8') or size>MAX_PACKET:raise MediaUnavailable('图像帧超过板端预算')
                                offsets.append([offset,size]);offset+=size;pending=pending[size:]
                            if len(pending)>MAX_PACKET:raise MediaUnavailable('图像帧不可解析')
                        if pending or not offsets:raise MediaUnavailable('视频帧不完整')
                count=max(len(offsets),math.ceil(pcm.stat().st_size/4000) if audio else 0) if video else math.ceil(pcm.stat().st_size/8000)
                row=dict(id=asset,job_id=job,title=str(title or requested.name)[:60],kind='image' if image else 'video' if video else 'audio',frames=count,fps=0 if image else FPS if video else 4,duration_ms=0 if image else round(duration*1000),has_audio=bool(audio))
                if video:row.update(source_width=int(video['width']),source_height=int(video['height']))
                (scratch/'index.json').write_text(json.dumps(offsets))
                original.unlink()
                destination=directory/asset
                if destination.exists():shutil.rmtree(destination)
                scratch.rename(destination)
                # TemporaryDirectory's cleanup sees a missing original path.
                temp=directory/'manifest.new';temp.write_text(json.dumps(existing+[row],ensure_ascii=False));temp.replace(directory/'manifest.json')
                return row
        finally:
            if source:source.close()
            os.close(descriptor)

    def chunk(self,job,asset,index):
        if not isinstance(asset,str) or not ID.fullmatch(asset) or type(index) is not int or index<0:raise MediaUnavailable('媒体帧请求无效')
        row=next((r for r in self.manifest(job) if r['id']==asset),None)
        if not row or index>=row['frames']:raise MediaUnavailable('媒体不存在或已经结束')
        directory=self.directory(job)/asset;picture=b'';audio=b''
        if row['kind']!='audio':
            offsets=json.loads((directory/'index.json').read_text());offset,size=offsets[min(index,len(offsets)-1)]
            if not 0<size<=MAX_PACKET:raise MediaUnavailable('图像帧预算无效')
            with (directory/'frames.mjpg').open('rb') as data:data.seek(offset);picture=data.read(size)
            if len(picture)!=size:raise MediaUnavailable('图像帧未保存完整')
        if row['has_audio']:
            size=4000 if row['kind']=='video' else 8000
            with (directory/'audio.pcm').open('rb') as data:data.seek(index*size);audio=data.read(size)
            if len(audio)%2:raise MediaUnavailable('声音数据未保存完整')
            if row['kind']=='video':audio=audio.ljust(size,b'\0')
        return dict(ok=True,id=asset,job_id=job,index=index,eof=index+1==row['frames'],fps=row['fps'],frame=base64.b64encode(picture).decode(),audio=base64.b64encode(audio).decode())
