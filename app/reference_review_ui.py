"""Review both semantic selections before committing a reference match."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image,ImageTk
from reference_regions import select,diagnostic

def review(app,reference_rgb,reference_data,target_rgb,target_data,scope,name):
    if scope!='全图' and (not reference_data['people'] or not target_data['people']):
        from tkinter import messagebox
        messagebox.showinfo('区域暂不可用','其中一张照片未识别到人像，无法可靠区分人物部位与背景。请选择“全图”并用取样框限定范围。',parent=app.color_dialog_parent());return None
    parent=app.color_dialog_parent();window=tk.Toplevel(parent)
    window.title('确认追色区域');window.transient(parent)
    width=min(1040,window.winfo_screenwidth()-60);height=min(650,window.winfo_screenheight()-90)
    window.geometry(f'{width}x{height}');window.minsize(min(650,width),min(480,height))
    shell=ttk.Frame(window,padding=12);shell.pack(fill='both',expand=True)
    ttk.Label(shell,text=f'{scope} · 分别确认参考图与当前照片的对应区域').pack(anchor='w')
    ttk.Label(shell,text='分别拖框限制参考取样和目标应用范围；绿色为选中范围。关闭窗口保留已有参考。',wraplength=width-45).pack(anchor='w',pady=(4,10))
    footer=ttk.Frame(shell);footer.pack(side='bottom',fill='x',pady=(8,0))
    note=tk.StringVar();ttk.Label(footer,textvariable=note,wraplength=width-50).pack(fill='x')
    buttons=ttk.Frame(footer);buttons.pack(fill='x',pady=(8,0))
    columns=ttk.Frame(shell);columns.pack(fill='both',expand=True)
    states=[]
    for title,rgb,data in [('参考图',reference_rgb,reference_data),('当前照片',target_rgb,target_data)]:
        frame=ttk.Frame(columns);frame.pack(side='left',fill='both',expand=True,padx=5)
        ttk.Label(frame,text=title).pack(anchor='w')
        count=len(data['people']);choices=['全部人物']+[f'人像 {i+1}' for i in range(count)]
        value=tk.StringVar(value='人像 1' if count==1 else '全部人物')
        combo=ttk.Combobox(frame,textvariable=value,values=choices,state='readonly')
        if scope in ('全图','背景'):combo.configure(state='disabled')
        combo.pack(fill='x',pady=4)
        canvas=tk.Canvas(frame,background='#e9edf2',highlightthickness=1,highlightbackground='#bac5d2')
        canvas.pack(fill='both',expand=True)
        status=tk.StringVar();ttk.Label(frame,textvariable=status,wraplength=max(230,width//2-50)).pack(fill='x',pady=4)
        state=dict(rgb=rgb,data=data,value=value,canvas=canvas,status=status,roi=None,start=None)
        states.append(state)
        actions=ttk.Frame(frame);actions.pack(fill='x')
        ttk.Button(actions,text='清除取样框',command=lambda s=state:clear(s)).pack(side='left')
        ttk.Button(actions,text='输入范围…',command=lambda s=state:enter(s)).pack(side='left',padx=4)
        combo.bind('<<ComboboxSelected>>',lambda event,s=state:draw(s))
        canvas.bind('<Configure>',lambda event,s=state:draw(s))
        canvas.bind('<ButtonPress-1>',lambda event,s=state:press(event,s))
        canvas.bind('<B1-Motion>',lambda event,s=state:drag(event,s))
        canvas.bind('<ButtonRelease-1>',lambda event,s=state:release(event,s))
    def person(s):return None if s['value'].get()=='全部人物' or scope in ('全图','背景') else int(s['value'].get().split()[-1])-1
    def mask(s):return select(s['data'],scope,person(s),s['roi'])
    def clear(s):s['roi']=None;draw(s)
    def enter(s):
        from tkinter import simpledialog
        text=simpledialog.askstring('输入范围','左、上、右、下百分比，用空格分隔，例如 20 20 80 80',initialvalue=' '.join(f'{v*100:g}' for v in (s['roi'] or [0,0,1,1])),parent=window)
        if text is None:return
        try:
            box=[float(v)/100 for v in text.replace(',',' ').replace('，',' ').split()]
            select(s['data'],scope,person(s),box)
        except (ValueError,TypeError):note.set('请输入四个 0–100 的数，右大于左，下大于上。');return
        s['roi']=box;note.set('范围已更新。');draw(s)
    def coordinates(event,s):
        x,y,w,h=s.get('placement',(0,0,1,1))
        return np.clip([(event.x-x)/w,(event.y-y)/h],0,1).tolist()
    def press(event,s):
        x,y,w,h=s.get('placement',(0,0,1,1))
        if x<=event.x<=x+w and y<=event.y<=y+h:s['start']=coordinates(event,s)
    def drag(event,s):
        if s['start'] is None:return
        x,y=s['start'];a,b=coordinates(event,s)
        if abs(x-a)<.002 or abs(y-b)<.002:return
        s['roi']=[min(x,a),min(y,b),max(x,a),max(y,b)];draw(s)
    def release(event,s):drag(event,s);s['start']=None
    def draw(s):
        canvas=s['canvas'];w,h=max(1,canvas.winfo_width()),max(1,canvas.winfo_height())
        if w<5 or h<5:return
        source=Image.fromarray(np.clip(s['rgb'],0,255).astype(np.uint8));source.thumbnail((w,h))
        m=mask(s)
        if m is not None:
            overlay=Image.fromarray(m.astype(np.uint8)*255).resize(source.size,Image.Resampling.NEAREST)
            pixels=np.asarray(source).astype(np.float32).copy();a=np.asarray(overlay)/255*.33
            pixels=pixels*(1-a[:,:,None])+np.array([30,210,145])*a[:,:,None]
            source=Image.fromarray(pixels.astype(np.uint8))
        s['image']=ImageTk.PhotoImage(source,master=window);canvas.delete('all')
        x,y=(w-source.width)//2,(h-source.height)//2;s['placement']=(x,y,source.width,source.height)
        canvas.create_image(x,y,anchor='nw',image=s['image'])
        if s['roi']:
            a,b,c,d=s['roi'];canvas.create_rectangle(x+a*source.width,y+b*source.height,x+c*source.width,y+d*source.height,outline='#ffcf40',width=2)
        try:s['status'].set(diagnostic(m,s['rgb'].shape[:2]))
        except ValueError as error:s['status'].set(str(error))
    def confirm():
        import creative_color as color
        try:
            for s in states:diagnostic(mask(s),s['rgb'].shape[:2])
            stats=color.statistics(reference_rgb,mask(states[0]))
            # Reject invalid target samples before mutating the current recipe.
            color.statistics(target_rgb,mask(states[1]))
        except ValueError as error:note.set(str(error));return
        app.commit_edit('确认追色区域前')
        app.workflow_extensions['reference']=dict(stats=stats,scope=scope,name=name,
            color=app.reference_color.get(),tone=app.reference_tone.get(),
            target_person=person(states[1]),target_roi=states[1]['roi'],
            source_person=person(states[0]),source_roi=states[0]['roi'],region_version=2)
        app.reference_note.set(name+' · 区域已确认');app.record('确认参考图与目标区域')
        window.destroy();app.refresh()
    ttk.Button(buttons,text='取消',command=window.destroy).pack(side='right',padx=4)
    ttk.Button(buttons,text='确认区域',command=confirm).pack(side='right',padx=4)
    window.bind('<Escape>',lambda event:window.destroy());window.grab_set()
    window.update_idletasks()
    for s in states:draw(s)
    return window
