"""Explicit unavailable-feature messages for the standalone photo edition."""
from tkinter import messagebox
class LivePhotoUI:
    def show_live_photo(self):
        messagebox.showinfo('静态照片版','此版本暂不提供 HEIC 和实况照片处理，请导出 JPEG / PNG / TIFF 后导入。',parent=self.root)
class VideoPreviewUI:
    def show_video_preview(self):
        messagebox.showinfo('静态照片版','此版本暂不提供视频处理。',parent=self.root)
