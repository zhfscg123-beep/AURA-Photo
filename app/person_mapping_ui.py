"""User-confirmed cross-photo person correspondence, never infer identity from order."""
import tkinter as tk
from tkinter import ttk
from PIL import Image,ImageTk
from dpi_support import dp

def face_thumbnails(state):
    image=Image.fromarray(state['session'].original);out=[]
    for face in state['session'].faces:
        a,b,c,d=face.box;crop=image.crop((a,b,c,d));crop.thumbnail((220,220),Image.Resampling.LANCZOS);out.append(crop)
    return out

class PersonMappingUI:
    def choose_people_mapping(self,paths,selected,mapping,tree,parent,source_info=None):
        if self.busy or not selected:return
        if source_info is None:
            if not self.face_settings:return
            source=face_thumbnails(self.capture_photo())[self.active_face];source_index=self.active_face
        else:
            source=source_info['thumbnail'];source_index=source_info['person']
            if source is None:return
        def job():
            return [(i,face_thumbnails(self.library.load(self.library.key(paths[i])))) for i in selected]
        def ready(pairs):
            if not parent.winfo_exists():return
            window=tk.Toplevel(parent);window.title('确认跨照片人物');window.transient(parent);window.grab_set()
            window.geometry(f'{min(dp(self.root,680),self.root.winfo_screenwidth()-40)}x{min(dp(self.root,590),self.root.winfo_screenheight()-80)}')
            frame=ttk.Frame(window,padding=12);frame.pack(fill='both',expand=True);index=[0];choice=tk.StringVar();note=tk.StringVar();photos=[]
            ttk.Label(frame,text=f'来源：人像 {source_index+1}。请在每张照片中选择对应人物；编号只表示位置。',wraplength=dp(self.root,620)).pack(anchor='w')
            label=ttk.Label(frame);label.pack(pady=8)
            row=ttk.Frame(frame);row.pack(fill='both',expand=True);left=ttk.Label(row);left.pack(side='left',fill='both',expand=True);right=ttk.Label(row);right.pack(side='right',fill='both',expand=True)
            combo=ttk.Combobox(frame,textvariable=choice,state='readonly');combo.pack(fill='x',pady=8)
            def preview(e=None):
                images=pairs[index[0]][1];selected_index=combo.current()
                if 0<=selected_index<len(images):
                    photo=ImageTk.PhotoImage(images[selected_index],master=window);photos[1:]=[photo];right.configure(image=photo,text='')
                else:right.configure(image='',text='请选择目标人物')
            def load():
                i,images=pairs[index[0]];label.configure(text=f'{index[0]+1}/{len(pairs)} · {paths[i].name}')
                combo.configure(values=[f'人像 {n+1}' for n in range(len(images))]);choice.set('')
                if i in mapping and mapping[i]<len(images):combo.current(mapping[i])
                note.set('未检测到可靠人物，本图不能同步单人人像参数。' if not images else '选择后点击确认，不会按位置自动匹配。');preview()
            def confirm():
                i,images=pairs[index[0]];target=combo.current()
                if not 0<=target<len(images):note.set('请先选择目标人物；没有可靠人物的图可关闭窗口并取消勾选。');return
                mapping[i]=target;tree.set(str(i),'person',f'→ 人像 {target+1}')
                if index[0]+1==len(pairs):window.destroy();parent.grab_set();return
                index[0]+=1;load()
            combo.bind('<<ComboboxSelected>>',preview)
            ttk.Label(frame,textvariable=note,wraplength=dp(self.root,620)).pack(anchor='w',pady=6)
            ttk.Button(frame,text='确认并继续',command=confirm).pack(side='right')
            def close():window.destroy();parent.grab_set()
            ttk.Button(frame,text='关闭',command=close).pack(side='left');window.protocol('WM_DELETE_WINDOW',close)
            photos.append(ImageTk.PhotoImage(source,master=window));left.configure(image=photos[0]);load()
            self.mapping_window=window
        self.work(job,ready)
