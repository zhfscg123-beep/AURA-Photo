"""Read-only delivery review with paired native-detail views."""
import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image,ImageTk
from dark_ui import COLORS
from dpi_support import dp
from production_checks import for_app

def show(app):
    if app.document is None or app.output_float is None:return
    if app.busy or app._render_pending:
        app.status.set('请等待当前渲染完成，再检查成片。');return
    parent=app.color_dialog_parent() if hasattr(app,'color_dialog_parent') else app.root
    previous_grab=parent.grab_current()
    window=tk.Toplevel(parent);window.title('成片检查');window.transient(parent)
    width=min(dp(app.root,1100),window.winfo_screenwidth()-40);height=min(dp(app.root,780),window.winfo_screenheight()-80)
    window.geometry(f'{width}x{height}');window.minsize(min(width,700),min(height,520))
    timer=[None]
    shell=ttk.Frame(window,padding=12);shell.pack(fill='both',expand=True)
    ttk.Label(shell,text=app.path.name+' · 检查当前完整效果，调整请返回编辑').pack(anchor='w')
    footer=ttk.Frame(shell);footer.pack(side='bottom',fill='x',pady=(8,0))
    def close():
        if timer[0] is not None:window.after_cancel(timer[0]);timer[0]=None
        window.destroy()
        if previous_grab is not None and previous_grab.winfo_exists():previous_grab.grab_set()
    ttk.Button(footer,text='返回编辑',command=close).pack(side='right')
    ttk.Label(footer,text='100% 为一原图像素对应一屏幕像素；两侧滚动同步。数值提示不代表审美合格。',wraplength=width-190).pack(side='left',fill='x',expand=True)
    result=for_app(app)
    check_frame=ttk.Frame(shell);check_frame.pack(fill='x',pady=8)
    checks=ttk.Treeview(check_frame,columns=('status','message'),show='headings',height=5)
    checks.heading('status',text='状态');checks.heading('message',text='检查结果');checks.column('status',width=80,stretch=False);checks.column('message',width=width-135)
    checks.pack(side='left',fill='both',expand=True)
    bar=ttk.Scrollbar(check_frame,orient='vertical',command=checks.yview);bar.pack(side='right',fill='y');checks.configure(yscrollcommand=bar.set)
    for row in result['checks']:checks.insert('','end',values=({'ok':'已检查','review':'请核对','error':'待处理'}[row['status']],row['message']))
    options=ttk.Frame(shell);options.pack(fill='x',pady=4)
    region=tk.StringVar(value='导出构图');zoom=tk.StringVar(value='适合');clip=tk.BooleanVar(value=False)
    choices=['导出构图','完整画幅']+[f'人像 {i+1}' for i in range(len(app.session.faces))]
    for title,var,values in [('检查区域',region,choices),('比例',zoom,['适合','100%','200%','400%'])]:
        ttk.Label(options,text=title).pack(side='left',padx=(0,5));combo=ttk.Combobox(options,textvariable=var,values=values,state='readonly',width=12);combo.pack(side='left',padx=(0,12));combo.bind('<<ComboboxSelected>>',lambda event:draw())
    ttk.Checkbutton(options,text='标记纯白／纯黑',variable=clip,command=lambda:draw()).pack(side='left')
    body=ttk.Frame(shell);body.pack(fill='both',expand=True);views=[];photos=[]
    sources=(app.session.original,app.output)
    from develop_output import preview
    export_sources=(app.prepare_export_image(app.session.original),preview(app.prepare_export_image(app.output_float),app.workflow_extensions.get('output',{})))
    faces=list(app.session.faces)
    def scroll(axis,*args):
        for c in views:getattr(c,axis+'view')(*args)
        draw(False)
    for title in ('导入底图','当前成片'):
        frame=ttk.Frame(body);frame.pack(side='left',fill='both',expand=True,padx=4)
        ttk.Label(frame,text=title).pack(anchor='w')
        host=ttk.Frame(frame);host.pack(fill='both',expand=True)
        c=tk.Canvas(host,bg=COLORS['viewport'],highlightthickness=0,takefocus=1);c.grid(row=0,column=0,sticky='nsew');views.append(c)
        vertical=ttk.Scrollbar(host,orient='vertical',command=lambda *args:scroll('y',*args));vertical.grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(host,orient='horizontal',command=lambda *args:scroll('x',*args));horizontal.grid(row=1,column=0,sticky='ew')
        c.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set);host.rowconfigure(0,weight=1);host.columnconfigure(0,weight=1)
        c.bind('<MouseWheel>',lambda e:(scroll('y','scroll',-int(e.delta/120),'units'),'break')[1])
        for key,axis,amount in [('<Left>','x',-1),('<Right>','x',1),('<Up>','y',-1),('<Down>','y',1)]:c.bind(key,lambda e,axis=axis,amount=amount:(scroll(axis,'scroll',amount,'units'),'break')[1])
    def draw(reset=True):
        if not window.winfo_exists():return
        photos.clear();before,after=export_sources if region.get()=='导出构图' else sources
        box=None
        if region.get().startswith('人像 '):
            face=faces[int(region.get().split()[-1])-1];a,b,c,d=face.box;pad=int(max(c-a,d-b)*.15)
            box=(max(0,a-pad),max(0,b-pad),min(before.shape[1],c+pad),min(before.shape[0],d+pad))
        for canvas,rgb in zip(views,(before,after)):
            if box:
                a,b,c,d=box;rgb=rgb[b:d,a:c]
            factor=min(1,max(1,canvas.winfo_width()-4)/rgb.shape[1],max(1,canvas.winfo_height()-4)/rgb.shape[0]) if zoom.get()=='适合' else int(zoom.get()[:-1])/100
            fullw,fullh=max(1,round(rgb.shape[1]*factor)),max(1,round(rgb.shape[0]*factor))
            canvas.configure(scrollregion=(0,0,fullw,fullh))
            if reset:canvas.xview_moveto(0);canvas.yview_moveto(0)
            left=max(0,int(canvas.canvasx(0)/factor));top=max(0,int(canvas.canvasy(0)/factor))
            right=min(rgb.shape[1],left+int(canvas.winfo_width()/factor)+3);bottom=min(rgb.shape[0],top+int(canvas.winfo_height()/factor)+3)
            tile=np.asarray(rgb[top:bottom,left:right],np.uint8)
            if tile.size==0:continue
            if clip.get():
                tile=tile.copy();high=np.all(tile>=255,axis=2);low=np.all(tile==0,axis=2);tile[high]=[255,70,70];tile[low]=[60,130,255]
            image=Image.fromarray(tile).resize((max(1,round(tile.shape[1]*factor)),max(1,round(tile.shape[0]*factor))),Image.Resampling.LANCZOS if factor<1 else Image.Resampling.NEAREST)
            photo=ImageTk.PhotoImage(image,master=window);photos.append(photo);canvas.delete('all')
            canvas.create_image(round(left*factor),round(top*factor),anchor='nw',image=photo)
    window._production_checks=result;window._review_draw=draw;window._review_zoom=zoom;window._review_region=region
    window.bind('<Escape>',lambda e:close());window.protocol('WM_DELETE_WINDOW',close);window.grab_set();window.update();draw()
    def resized(event):
        if event.widget is not window:return
        if timer[0] is not None:window.after_cancel(timer[0])
        def redraw():timer[0]=None;draw(False)
        timer[0]=window.after(120,redraw)
    window.bind('<Configure>',resized)
    def initial_draw():timer[0]=None;draw()
    timer[0]=window.after_idle(initial_draw)
    return window
