"""Standalone release information; never launch an installed-AURA updater."""
from tkinter import ttk, messagebox
import threading
from aura_version import VERSION
class UpdateUI:
    def init_updates(self):
        self._update_cancel=threading.Event()
        self._update_running=False
    def build_update_settings(self,parent):
        ttk.Label(parent,text='AURA Photo '+VERSION+'\n独立静态照片版\n安装器可选择中文或英文，设置中可随时更改。\n使用 AURA Photo 安装包更新，保留本版设置。',wraplength=300).pack(fill='x',pady=6)
        ttk.Button(parent,text='本版功能与模型说明',command=self.show_updates).pack(fill='x',pady=4)
    def show_updates(self,*args,**kwargs):
        messagebox.showinfo('AURA Photo · 独立版说明',
            '支持静态照片与 RAW 编辑。\n附带 NVIDIA GPU 推理与渲染运行库；不可用时回退 CPU。\n首次启用 GPU 渲染需同意联网初始化，之后可离线使用。\n面部定位：MediaPipe 网格适配。\n皮肤 / 人物分割：MediaPipe 多类模型。\n眼、眉、唇：网格区域，可手动修边。\n不含富士滤镜、HEIC、实况照片及视频。\n细发丝、遮挡和侧脸请检查蒙版。\n完整许可见程序目录 THIRD_PARTY_NOTICES.txt。',parent=self.root)
    def choose_update_package(self):self.show_updates()
