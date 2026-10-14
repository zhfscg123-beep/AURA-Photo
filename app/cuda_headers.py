"""Recipient-side optional CUDA header setup from NVIDIA's official wheel.

The ZIP contains runtime DLLs but no copied SDK headers. Downloads occur only
after setup consent, never from a render worker.
"""
from pathlib import Path
import hashlib,io,json,os,threading,urllib.request,zipfile
ROOT=Path(__file__).resolve().parent
_lock=threading.RLock()
def location():
    return Path(os.environ.get('AURA_DATA_DIR',str(ROOT/'.aura-photo-data')))/'cuda-toolkit-headers-13.0.96'
def ready():
    return (location()/'include/cuda_runtime.h').is_file() and (location()/'setup-complete.json').is_file()
def ensure_headers():
    if not ready():
        raise RuntimeError('GPU 渲染尚未初始化；请重新启动并选择下载 GPU 编译组件，或使用 CPU。')
    from ascii_paths import ascii_directory
    return ascii_directory(location())
def install_headers():
    with _lock:
        if ready():return
        source=json.loads((ROOT/'licenses/NVIDIA/header-download.json').read_text(encoding='utf8'))
        with urllib.request.urlopen(source['url'],timeout=90) as response:
            data=response.read(20*1024*1024)
        if hashlib.sha256(data).hexdigest()!=source['sha256']:
            raise ValueError('GPU 初始化文件校验失败。')
        target=location().resolve();target.mkdir(parents=True,exist_ok=True);count=0
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.endswith('/') or '/include/' not in name:continue
                p=(target/('include/'+name.split('/include/',1)[1])).resolve()
                if not p.is_relative_to(target):raise ValueError('GPU 初始化文件路径无效。')
                p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(archive.read(name));count+=1
            for name in archive.namelist():
                if '/licenses/' in name and not name.endswith('/'):
                    (target/'License.txt').write_bytes(archive.read(name))
        if not (target/'include/cuda_runtime.h').is_file():raise ValueError('GPU 编译文件不完整。')
        (target/'setup-complete.json').write_text(json.dumps(dict(source,installed_files=count),indent=2),encoding='utf8')
def prepare_interactive():
    if ready():return
    import tkinter as tk
    from tkinter import messagebox
    root=tk.Tk();root.withdraw()
    try:
        consent=messagebox.askyesno('启用 GPU 渲染',
            'GPU 推理运行库已就绪。GPU 照片渲染还需首次联网下载少量 NVIDIA 编译文件，之后可离线使用。\n\n'
            '组件来自 NVIDIA 官方发布的 Python 包，按 NVIDIA CUDA 许可使用；许可全文位于程序目录 licenses/NVIDIA。\n\n'
            '是否下载并启用？选择“否”仍可使用 GPU 推理和 CPU 渲染。',parent=root)
        if consent:
            root.deiconify();root.title('正在初始化 GPU');tk.Label(root,text='正在从 NVIDIA 官方发布包下载编译文件，请稍候……',padx=24,pady=24).pack();root.update()
            try:install_headers()
            except Exception as error:
                messagebox.showwarning('GPU 初始化未完成','已保留 CPU 渲染，可稍后重新启动重试。\n'+str(error),parent=root)
        if not ready():os.environ['AURA_RENDER_BACKEND']='cpu'
    finally:root.destroy()
