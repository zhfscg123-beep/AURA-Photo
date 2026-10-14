"""One native develop workspace sharing AURA's document and render controller.

Widgets are built here once. Opening switches the active viewport; accepting or
cancelling restores the main viewport, without a second application/session.
"""
import copy
import time
import tkinter as tk
from tkinter import ttk
import numpy as np
from PIL import Image,ImageTk
from dark_ui import COLORS, Section
from dpi_support import dp, ui_font, scale_widget_tree
from editing import Viewport
from scroll_ui import attach_scroll


class ColorWorkbench:
    def __init__(self, app):
        self.app=app;self.active=False;self.snapshot=None;self.page='基本';self.point_preview=False;self.display_key=None;self.display_image=None;self.target_drag=None
        from color_workbench_gpu import register
        register()
        from render_queue import LatestRenderer
        self.display_renderer=LatestRenderer()
        self.apply_timer=None
        self.drag_renderer=LatestRenderer();self.drag_identity=None;self.drag_revision=None;self.drag_preview_at=0;self.drag_frame_key=None;self.drag_frame_image=None
        self.window=tk.Toplevel(app.root);self.window.withdraw()
        self.window.title('AURA · 调色工作台');self.window.transient(app.root)
        self.window.protocol('WM_DELETE_WINDOW',self.request_return)
        self.window._ui_scale=app.root._ui_scale;self.window._ui_dpi=app.root._ui_dpi
        header=ttk.Frame(self.window,padding=(16,12));header.pack(fill='x')
        ttk.Label(header,text='调色工作台',font=ui_font(app.root,15,'bold')).pack(side='left')
        ttk.Label(header,textvariable=app.filename,style='Muted.TLabel').pack(side='left',padx=16)
        self.back=ttk.Button(header,text='返回',command=self.request_return);self.back.pack(side='right')
        self.accept=ttk.Button(header,text='应用',style='Accent.TButton',command=self.apply);self.accept.pack(side='right',padx=8)
        ttk.Button(header,text='取消未应用调整',command=lambda:self.close(False)).pack(side='right',padx=8)
        body=ttk.Frame(self.window);body.pack(fill='both',expand=True)
        nav_host=ttk.Frame(body,width=dp(app.root,104));nav_host.pack(side='left',fill='y');nav_host.pack_propagate(False)
        nav_scroll=tk.Canvas(nav_host,bg=COLORS['panel'],highlightthickness=0);nav_scroll.pack(fill='both',expand=True)
        nav=ttk.Frame(nav_scroll,padding=(8,8));nav_id=nav_scroll.create_window(0,0,window=nav,anchor='nw')
        nav.bind('<Configure>',lambda e:nav_scroll.configure(scrollregion=nav_scroll.bbox('all')));nav_scroll.bind('<Configure>',lambda e:nav_scroll.itemconfigure(nav_id,width=e.width));self.buttons={}
        self.nav_scrolling=attach_scroll(nav_scroll,nav,compact=True)
        for name in ('基本','曲线','颜色','分级','细节','效果','蒙版','光学','预设','参考','RAW','输出','兼容'):
            b=ttk.Button(nav,text=name,width=7,command=lambda n=name:self.show_page(n));b.pack(fill='x',pady=3);self.buttons[name]=b
            b.bind('<MouseWheel>',lambda e:(nav_scroll.yview_scroll(-int(e.delta/120),'units'),'break')[1])
            def reveal(e,button=b):
                top=nav_scroll.canvasy(0);y=button.winfo_y();h=button.winfo_height()
                if y<top:nav_scroll.yview_moveto(y/max(1,nav.winfo_height()))
                elif y+h>top+nav_scroll.winfo_height():nav_scroll.yview_moveto((y+h-nav_scroll.winfo_height())/max(1,nav.winfo_height()))
            b.bind('<FocusIn>',reveal)
        preview=ttk.Frame(body);preview.pack(side='left',fill='both',expand=True)
        self.canvas=tk.Canvas(preview,bg=COLORS['viewport'],highlightthickness=0,takefocus=1);self.canvas.pack(fill='both',expand=True)
        toolbar=ttk.Frame(preview,padding=(8,8));toolbar.pack(fill='x')
        for label,fn in [('适合',app.fit),('100%',app.actual),('撤销',app.undo),('重做',app.redo)]:ttk.Button(toolbar,text=label,width=5,command=fn).pack(side='left',padx=2)
        ttk.Button(toolbar,text='成片检查',command=lambda:__import__('production_review_ui').show(app)).pack(side='left',padx=2)
        self.compare=tk.StringVar(value='原图滑动对比');self.clipping=tk.BooleanVar(value=False)
        self.wipe_position=tk.DoubleVar(value=0);self.wipe_dragging=False;self.wipe_photo=None
        combo=ttk.Combobox(toolbar,textvariable=self.compare,values=['当前效果','打开前','原图','左右并排','原图滑动对比','打开前滑动对比'],state='readonly',width=13);combo.pack(side='left',padx=8)
        combo.bind('<<ComboboxSelected>>',lambda e:app.draw())
        ttk.Checkbutton(toolbar,text='曝光溢出',variable=self.clipping,command=app.draw).pack(side='left')
        self.wipe_row=ttk.Frame(preview,padding=(8,0,8,6))
        ttk.Label(self.wipe_row,text='前后对比',style='Muted.TLabel').pack(side='left')
        self.wipe_scale=ttk.Scale(self.wipe_row,from_=0,to=100,variable=self.wipe_position,length=220,command=self.wipe_changed);self.wipe_scale.pack(side='left',fill='x',expand=True,padx=8)
        ttk.Button(self.wipe_row,text='居中',width=4,command=lambda:(self.wipe_position.set(50),self.wipe_changed(50))).pack(side='right')
        self.wipe_row.pack(fill='x')
        self.compare.trace_add('write',lambda *_:self.update_compare_controls())
        self.right=ttk.Frame(body,width=dp(app.root,380),padding=(8,0));self.right.pack(side='right',fill='y');self.right.pack_propagate(False)
        self.page_title=tk.StringVar(value='基本');ttk.Label(self.right,textvariable=self.page_title,font=ui_font(app.root,13,'bold')).pack(anchor='w',pady=8)
        self.hist_host=ttk.Frame(self.right);self.hist_host.pack(fill='x')
        self.scroll=tk.Canvas(self.right,bg=COLORS['panel'],highlightthickness=0);self.scroll.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(self.right,command=self.scroll.yview);bar.pack(side='right',fill='y');self.scroll.configure(yscrollcommand=bar.set)
        self.panel=ttk.Frame(self.scroll);self.panel_id=self.scroll.create_window(0,0,window=self.panel,anchor='nw')
        self.panel.bind('<Configure>',lambda e:self.scroll.configure(scrollregion=self.scroll.bbox('all')))
        self.scroll.bind('<Configure>',lambda e:self.scroll.itemconfigure(self.panel_id,width=e.width))
        self.panel_scrolling=attach_scroll(self.scroll,self.panel,bar)
        footer=ttk.Frame(self.window,padding=(16,8));footer.pack(fill='x')
        ttk.Label(footer,textvariable=app.status,style='Muted.TLabel',wraplength=1000).pack(fill='x')
        self.external=[];self.pages={};self.view=Viewport()
        self.canvas.bind('<Configure>',lambda e:self.redraw())
        self.canvas.bind('<MouseWheel>',self.wheel);self.canvas.bind('<Motion>',self.hover);self.canvas.bind('<Leave>',app.pointer_leave)
        for num,kwargs in [(1,{}),(2,{'pan':True}),(3,{'erase':True})]:
            self.canvas.bind(f'<ButtonPress-{num}>',lambda e,k=kwargs:self.press(e,**k))
            self.canvas.bind(f'<B{num}-Motion>',self.motion);self.canvas.bind(f'<ButtonRelease-{num}>',self.release)
        for key,fn in [('<Control-z>',app.undo),('<Control-y>',app.redo),('<Control-Shift-Z>',app.redo)]:self.window.bind(key,lambda e,f=fn:app.shortcut(e,f))
        self.window.bind('<KeyPress-space>',app.space_down);self.window.bind('<KeyRelease-space>',app.space_up)
        self.window.bind('<Escape>',lambda e:(app.select_tool('pan'),'break')[1])
        self.window.bind('<KeyPress-backslash>',lambda e:self.peek(True));self.window.bind('<KeyRelease-backslash>',lambda e:self.peek(False))
        self.window.bind('<FocusOut>',lambda e:self.peek(False) if e.widget is self.window else None)
        self.window.bind('<Configure>',self.layout)
        self.window.after(40,self.poll)

    def finish_build(self):
        a=self.app
        self.external=[a.creative_color_panel,a.raw_panel,a.histogram_panel,a.reference_panel]
        self.pages={'基本':[a.develop_sections['wb'],a.color_basic_section],
          '曲线':[a.color_curve_section],'颜色':[a.color_hsl_section,a.develop_sections['point'],a.develop_sections['bw'],a.develop_sections['calibration']],
          '分级':[a.develop_sections['grading']],'细节':[a.develop_sections['detail']],
          '效果':[a.develop_sections['effects'],a.color_lut_section],
          '光学':[a.develop_sections['lens'],a.develop_sections['transform']],
          '预设':[a.color_filter_section],'输出':[a.develop_sections['output'],a.develop_sections['display_device']],
          '兼容':[a.develop_process_control,a.color_legacy_grade]}
        self.global_children=list(a.creative_color_panel.body.winfo_children())
        for section in self.external:
            if not section.opened:section.toggle()
        a.creative_color_panel.header.pack_forget()
        self.bind_scroll(a.creative_color_panel);self.bind_scroll(a.raw_panel);self.bind_scroll(a.reference_panel)
        scale_widget_tree(self.window);self.show_page('基本')
        from color_workbench_masks import WorkbenchMasks
        self.mask_ui=WorkbenchMasks(self)
        self.pages['蒙版']=[self.mask_panel]

    def bind_scroll(self,widget):
        if not isinstance(widget,(ttk.Scale,tk.Canvas,ttk.Combobox)):
            widget.bind('<MouseWheel>',lambda e:(self.scroll.yview_scroll(-int(e.delta/120),'units'),'break')[1])
        for child in widget.winfo_children():self.bind_scroll(child)

    def owns(self,widget):
        while widget is not None:
            if widget is self.window:return True
            widget=getattr(widget,'master',None)
        return False

    def show_page(self,name):
        self.page=name;self.page_title.set(name)
        for key,b in self.buttons.items():b.configure(style='Accent.TButton' if key==name else 'TButton')
        a=self.app
        if not hasattr(a,'creative_color_panel'):return
        for widget in self.panel.winfo_children():widget.pack_forget()
        for widget in a.creative_color_panel.body.winfo_children():widget.pack_forget()
        if name=='RAW':a.raw_panel.pack(fill='x')
        elif name=='参考':a.reference_panel.pack(fill='x')
        elif name=='蒙版':
            if hasattr(self,'mask_panel'):self.mask_panel.pack(fill='x')
            if hasattr(self,'mask_ui'):self.mask_ui.update_view()
        else:
            a.creative_color_panel.pack(fill='x')
            for widget in self.pages.get(name,[]):
                widget.pack(fill='x',pady=(0,8))
                if isinstance(widget,Section) and not widget.opened:widget.toggle()
        if name!='蒙版':a.mask_overlay.set(False)
        if name!='颜色':self.point_preview=False
        self.scroll.yview_moveto(0);self.redraw()

    def open(self):
        a=self.app
        if self.active:self.window.lift();return True
        if not a.document or a.busy or a.drag or a._render_pending:
            a.status.set('请先打开照片并等待当前处理完成，再进入调色工作台。');return False
        a.flush_parameters();a.commit_edit('打开调色工作台前');a.end_feature_compare()
        self.snapshot=a.capture_photo()
        self.accept.configure(state='normal');self.back.configure(state='normal')
        for key in ('region_layers','face_settings','patches','manual_records','history'):self.snapshot[key]=copy.deepcopy(self.snapshot[key])
        self.undo_before=list(a.edit_states);self.index_before=a.edit_index
        self.applied_marker=self.edit_marker()
        self.before=a.output.copy();self.saved=(a.canvas,a.view,a.pointer,a.overlay.get(),a.mask_overlay.get());self.saved_split=a.split.get()
        self.saved_mask_view=getattr(a,'_local_mask_view','彩色叠加')
        from creative_regions import regions
        self.preview_skin=regions(a.session,a.region_layers)['skin'].astype(np.float32)
        self.preview_skin_identity=(id(a.document),id(a.session))
        self.point_preview=False;self.display_key=None;self.display_image=None
        a.canvas=self.canvas;a.view=self.view;a.pointer=None;a.root._photo_canvas=self.canvas
        a.overlay.set(False);a.mask_overlay.set(False);a.select_tool('pan')
        self.wipe_position.set(0);a.split.set(0);self.active=True;self.compare.set('原图滑动对比');self.clipping.set(False)
        self.wipe_dragging=False
        sw,sh=a.root.winfo_screenwidth(),a.root.winfo_screenheight()
        self.window.geometry(f'{min(dp(a.root,1400),sw-48)}x{min(dp(a.root,880),sh-100)}+24+24')
        self.window.deiconify();self.window.lift();self.window.grab_set();self.window.update_idletasks()
        self.show_page(self.page);self.window.update();a.fit();self.canvas.focus_set();return True

    def edit_marker(self):
        a=self.app
        return id(a.document),id(a.session),a.edit_index,len(a.history)

    def has_unapplied(self):
        return self.edit_marker()!=self.applied_marker or any(self.owns(c) and getattr(c,'dirty',False) for c in self.app.controls)

    def apply(self):
        if self.apply_timer is not None:self.window.after_cancel(self.apply_timer);self.apply_timer=None
        if not self.active:return
        a=self.app
        if a.busy or a.drag:a.status.set('请等待当前处理完成，再应用调整。');return
        for control in a.controls:
            if self.owns(control) and hasattr(control,'cancel_pending'):
                control.cancel_pending();control.commit()
                if getattr(control,'dirty',False):a.status.set('请检查尚未确认的参数输入。');return
        if a._render_pending:
            a.status.set('正在完成调色；完成后保留在工作台。')
            self.accept.configure(state='disabled');self.back.configure(state='disabled')
            self.apply_timer=self.window.after(100,self.apply);return
        self.accept.configure(state='normal');self.back.configure(state='normal')
        if a._render_failed:a.status.set('调色更新失败，尚未应用。请修正参数后重试。');return
        a.end_feature_compare();a.commit_edit('应用调色工作台');a.mark_draft()
        self.snapshot=a.capture_photo();self.snapshot['view']=copy.copy(self.saved[1])
        self.snapshot['vars']['status']='调整已应用；可继续编辑或返回。'
        for key in ('region_layers','face_settings','patches','manual_records','history'):self.snapshot[key]=copy.deepcopy(self.snapshot[key])
        self.undo_before=list(a.edit_states);self.index_before=a.edit_index;self.before=a.output.copy()
        self.applied_marker=self.edit_marker();self.display_key=None
        a.status.set('调整已应用；可继续编辑或返回。');a.draw()

    def request_return(self):
        if not self.active:return
        a=self.app
        if a.busy or a.drag:a.status.set('请等待当前处理完成，再返回。');return
        if not self.has_unapplied():self.close(True);return
        if getattr(self,'return_dialog',None) is not None:
            self.return_dialog.lift();return
        dialog=tk.Toplevel(self.window);self.return_dialog=dialog;dialog.title('尚有未应用的调整');dialog.transient(self.window)
        dialog._ui_scale=self.window._ui_scale;dialog._ui_dpi=self.window._ui_dpi
        body=ttk.Frame(dialog,padding=20);body.pack(fill='both',expand=True)
        ttk.Label(body,text='如何处理未应用的调整？',font=ui_font(a.root,12,'bold')).pack(anchor='w')
        ttk.Label(body,text='已经应用的调整会保留。',style='Muted.TLabel').pack(anchor='w',pady=(8,16))
        row=ttk.Frame(body);row.pack(fill='x')
        def decide(choice):
            dialog.grab_release();dialog.destroy();self.return_dialog=None;self.window.grab_set()
            if choice=='apply':self.close(True)
            elif choice=='discard':self.close(False)
            else:self.canvas.focus_set()
        ttk.Button(row,text='应用后返回',style='Accent.TButton',command=lambda:decide('apply')).pack(side='left',padx=(0,8))
        ttk.Button(row,text='放弃未应用调整',command=lambda:decide('discard')).pack(side='left',padx=(0,8))
        keep=ttk.Button(row,text='继续编辑',command=lambda:decide('keep'));keep.pack(side='left')
        dialog.protocol('WM_DELETE_WINDOW',lambda:decide('keep'));dialog.bind('<Escape>',lambda e:decide('keep'))
        scale_widget_tree(dialog);dialog.grab_set();keep.focus_set()

    def close(self,accept):
        if not self.active:return
        a=self.app
        if a.busy or a.drag:
            a.status.set('请完成当前处理或松开拖动，再返回主界面。');return
        for control in a.controls:
            if self.owns(control) and hasattr(control,'cancel_pending'):
                control.cancel_pending()
                if accept:control.commit()
                else:control.dirty=False
        if accept and a._render_pending:
            a.status.set('正在完成调色，随后返回主界面…');self.window.after(100,lambda:self.close(True));return
        if accept and a._render_failed:
            a.status.set('调色更新失败，请修正参数或取消本次调整。');return
        if self.apply_timer is not None:self.window.after_cancel(self.apply_timer);self.apply_timer=None
        a.end_feature_compare();a.invalidate_parameter_render();self.display_renderer.invalidate();self.drag_renderer.invalidate()
        self.window.grab_release();self.window.withdraw();self.active=False
        a.canvas,a.view,a.pointer,overlay,mask=self.saved;a.root._photo_canvas=a.canvas
        if accept:a.commit_edit('应用调色工作台');a.mark_draft()
        else:
            a.restore_photo(self.snapshot);a.edit_states=self.undo_before;a.edit_index=self.index_before
            a.mark_draft()
        a._local_mask_view=self.saved_mask_view
        a.overlay.set(overlay);a.mask_overlay.set(mask);a.split.set(self.saved_split);a.select_tool('pan');a.draw()
        self.snapshot=None;self.before=None;a.root.lift()

    def focus_section(self,section):
        if not self.open():return
        a=self.app;name='基本'
        if section is a.raw_panel:name='RAW'
        elif section is a.reference_panel:name='参考'
        else:
            node=section
            while node is not None:
                found=next((key for key,items in self.pages.items() if node in items),None)
                if found:name=found;break
                node=getattr(node,'master',None)
        self.show_page(name)
        chain=[];node=section
        while node is not None and node is not self.panel:
            if isinstance(node,Section):chain.append(node)
            node=getattr(node,'master',None)
        for node in reversed(chain):
            if not node.opened:node.toggle()
        self.window.update_idletasks();self.scroll.yview_moveto(max(0,section.winfo_rooty()-self.panel.winfo_rooty())/max(1,self.panel.winfo_height()))

    def peek(self,on):
        if not self.active:return
        if on and not hasattr(self,'peek_previous'):self.peek_previous=self.compare.get();self.compare.set('原图')
        if not on and hasattr(self,'peek_previous'):self.compare.set(self.peek_previous);del self.peek_previous
        self.redraw()

    def redraw(self):
        if self.active:self.app.draw()

    def layout(self,event=None):
        if event is not None and event.widget is not self.window:return
        if self.window._ui_scale!=self.app.root._ui_scale:
            self.window._ui_scale=self.app.root._ui_scale;self.window._ui_dpi=self.app.root._ui_dpi;scale_widget_tree(self.window)
        self.right.configure(width=dp(self.app.root,380 if self.window.winfo_width()/self.app.root._ui_scale>1150 else 340))

    def press(self,event,**kwargs):
        a=self.app
        if self.is_wipe() and not kwargs.get('pan') and not a.space:
            if abs(event.x-a.size()[0]*self.wipe_position.get()/100)<=dp(a.root,16):
                self.wipe_dragging=True;self.canvas.focus_set();self.set_wipe(event.x);return
            if a.mode.get()!='pan' and self.wipe_position.get()>0 and event.x<a.size()[0]*self.wipe_position.get()/100:
                a.status.set('左侧是原图对比区；请在右侧结果区取色或绘制，或将对比滑块移到最左。');return
        if self.compare.get() in ('原图','打开前','左右并排'):
            a.status.set('切换到当前效果或划分对比后，可在照片上调整。');return
        if a.busy or a._render_pending:return
        if kwargs.get('pan') or a.space:a.press(event,**kwargs);return
        mode=a.mode.get()
        if mode=='develop_guide':
            h,w=a.document.rgb.shape[:2];p=a.original_point(a.point(event))/[max(1,w-1),max(1,h-1)]
            a.commit_edit('透视引导线前');self.target_drag=dict(mode=mode,start=p.tolist());a.drag={'mode':'develop_guide'};return
        if mode in ('develop_target_hsl','develop_target_curve') and not kwargs.get('pan') and not a.space:
            p=np.rint(a.original_point(a.point(event))).astype(int);h,w=a.color_input.shape[:2]
            if not 0<=p[0]<w or not 0<=p[1]<h:return
            a.commit_edit('照片直接调整前');pixel=a.color_input[p[1],p[0]]/255
            if mode=='develop_target_hsl':
                import color_science as cs
                from develop_engine import HUES
                lab=cs.oklab(cs.decode(pixel));hue=float(np.rad2deg(np.arctan2(lab[2],lab[1]))%360)
                name=min(HUES,key=lambda key:abs((hue-HUES[key]+180)%360-180));a.choose_hsl(name)
                axis=['色相','饱和度','明亮度'].index(a.hsl_target_axis.get());self.target_drag=dict(mode=mode,y=event.y,start=a.hsl_vars[axis].get(),axis=axis)
            else:
                import point_curves
                x=float(np.clip(np.mean(pixel),.002,.998));pts=copy.deepcopy(a.point_curve_editor.points());ys=point_curves.evaluate(np.array(x),pts)
                index=min(range(len(pts)),key=lambda i:abs(pts[i][0]-x))
                if abs(pts[index][0]-x)>.015:pts.append([x,float(ys)]);pts.sort();index=next(i for i,p in enumerate(pts) if p[0]==x)
                self.target_drag=dict(mode=mode,y=event.y,start=pts[index][1],points=pts,index=index)
            a.drag={'mode':'develop_target'};return
        if hasattr(self,'mask_ui') and self.mask_ui.press(event,erase=kwargs.get('erase',False)):return
        a.press(event,**kwargs)

    def wheel(self,event):
        a=self.app
        if a.mode.get()=='develop_component' and event.state&0x0004:
            if not a.drag:a.view.zoom(1.2**(event.delta/120),event.x,event.y,a.size());a.draw()
            return 'break'
        return a.wheel(event)

    def hover(self,event):
        if self.is_wipe() and abs(event.x-self.app.size()[0]*self.wipe_position.get()/100)<=dp(self.app.root,16):
            self.canvas.configure(cursor='sb_h_double_arrow');self.canvas.delete('tool_cursor');return
        self.app.hover(event)
        if hasattr(self,'mask_ui'):self.mask_ui.draw_handles()

    def motion(self,event):
        if self.wipe_dragging:self.set_wipe(event.x);return
        a=self.app;d=self.target_drag
        if d:
            if d['mode']=='develop_guide':
                from color_workbench_masks import source_screen
                start=source_screen(a,d['start']);self.canvas.delete('workbench_guide');self.canvas.create_line(*start,event.x,event.y,fill=COLORS['accent'],width=2,tags='workbench_guide');return
            if d['mode']=='develop_target_hsl':a.hsl_vars[d['axis']].set(float(np.clip(d['start']+(d['y']-event.y)/2,-100,100)))
            else:
                pts=copy.deepcopy(d['points']);pts[d['index']][1]=float(np.clip(d['start']+(d['y']-event.y)/350,0,1));a.point_curve_editor.set_points(pts)
            a.preview_global_color();return
        if hasattr(self,'mask_ui') and self.mask_ui.motion(event):return
        a.motion(event)

    def release(self,event):
        if self.wipe_dragging:self.set_wipe(event.x);self.wipe_dragging=False;return
        a=self.app
        if self.target_drag:
            self.motion(event);mode=self.target_drag['mode'];drag=self.target_drag;self.target_drag=None;a.drag=None
            if mode=='develop_guide':
                import develop_optics as optics
                h,w=a.document.rgb.shape[:2];p=a.original_point(a.point(event))/[max(1,w-1),max(1,h-1)]
                value=optics.checked(a.workflow_extensions.get('optics',{}))
                if len(value['guides'])>=4:a.optics_note.set('最多四条引导线；请先清除。');return
                if np.linalg.norm(p-drag['start'])<.001:return
                value['guides'].append(dict(axis='vertical' if a.guide_axis.get()=='垂直线' else 'horizontal',start=drag['start'],end=p.tolist()))
                a.workflow_extensions['optics']=optics.checked(value);a.optics_note.set(f'已绘制 {len(value["guides"])} 条引导线；点击应用校正。');a.commit_edit('添加透视引导线');a.draw();return
            a.parameter_apply(a.hsl_changed if mode=='develop_target_hsl' else a.color_changed);a.commit_edit('照片直接调整');return
        if hasattr(self,'mask_ui') and self.mask_ui.release(event):return
        a.release(event)

    def toggle_point_preview(self):
        self.point_preview=not self.point_preview;self.redraw()

    def is_wipe(self):return self.compare.get() in ('原图滑动对比','打开前滑动对比','划分对比')

    def update_compare_controls(self):
        self.wipe_row.pack(fill='x')
        if self.active:self.app.split.set(self.wipe_position.get() if self.compare.get()=='原图滑动对比' else 0)
        if not self.is_wipe():self.wipe_dragging=False

    def wipe_changed(self,value):
        if self.compare.get()!='原图滑动对比':self.compare.set('原图滑动对比')
        if self.active:self.app.split.set(float(value))
        self.redraw()

    def set_wipe(self,x):
        self.wipe_position.set(float(np.clip(x/max(1,self.app.size()[0])*100,0,100)))
        if self.compare.get() in ('打开前滑动对比','划分对比'):self.redraw()
        else:self.wipe_changed(self.wipe_position.get())

    def draw_default_compare(self):
        if not self.active or self.compare.get()!='原图滑动对比' or self.app.output is None:return
        a=self.app;c=self.canvas
        for item in c.find_all():
            if c.type(item)=='text' and c.itemcget(item,'text') in ('修复结果','左原图 / 右结果'):c.delete(item)
        value=self.wipe_position.get();c.delete('wipe_handle')
        if 0<value<100:
            x=a.size()[0]*value/100;cy=a.size()[1]/2;radius=dp(a.root,10)
            c.create_line(x,0,x,a.size()[1],fill='white',width=dp(a.root,2),tags='wipe_handle')
            c.create_oval(x-radius,cy-radius,x+radius,cy+radius,fill='white',outline=COLORS['accent'],width=2,tags='wipe_handle')
            c.create_text(x,cy,text='↔',fill=COLORS['accent'],tags='wipe_handle')
        c.create_text(dp(a.root,14),dp(a.root,14),text='左：原图 / 右：当前效果',anchor='nw',fill=COLORS['text'],font=ui_font(a.root,10,'bold'),tags='wipe_handle')

    def draw_preview(self):
        if not self.active or self.app.output is None:return False
        # The default comparison shares the original module's proven viewport
        # split path. It must work immediately, without an async pair job.
        if self.compare.get()=='原图滑动对比':return False
        a=self.app;mode={'当前效果':'current','打开前':'before','原图':'original','划分对比':'wipe-before','左右并排':'side','原图滑动对比':'wipe-original','打开前滑动对比':'wipe-before'}[self.compare.get()]
        if mode=='current' and not self.clipping.get() and not self.point_preview:return False
        cw,ch=a.size();h,w=a.output.shape[:2];s=a.view.scale
        x0=max(0,int(np.floor(a.view.cx-cw/(2*s))));y0=max(0,int(np.floor(a.view.cy-ch/(2*s))))
        x1=min(w,int(np.ceil(a.view.cx+cw/(2*s))));y1=min(h,int(np.ceil(a.view.cy+ch/(2*s))))
        if x0>=x1 or y0>=y1:return False
        bounds=(x0,y0,x1,y1);size=(max(1,round((x1-x0)*s)),max(1,round((y1-y0)*s)))
        record=None
        if self.point_preview:
            records=a.workflow_extensions.get('color',{}).get('point_colors',[]);i=a.point_color_index.get()
            if i<len(records):record=copy.deepcopy(records[i])
        signature=(id(a.output),id(a.output_float),bounds,size,mode,self.clipping.get(),str(record),id(a.color_input))
        if signature!=self.display_key:
            self.display_key=signature
            after=a.output;before=self.snapshot['output_float'];original=a.session.original;floating=a.output_float;source=a.color_input;clip=self.clipping.get();proof=copy.deepcopy(a.workflow_extensions.get('output',{}))
            import face_reshape,photo_body
            optical=copy.deepcopy(a.workflow_extensions.get('optics',{}));flow=copy.deepcopy(a.liquify_state['flow']) if a.liquify_active() else None
            body=copy.deepcopy(photo_body.current_field(a.photo_body_cache)) if a.photo_body_changed else None;fields=copy.deepcopy(face_reshape._fields(a.reshape_cache,a.face_settings))
            import creative_color
            point_data=creative_color.validate(a.workflow_extensions.get('color',{})) if record else None;point_document=a.document
            def job():
                from color_workbench_render import compose_mapped
                from ai_runtime import saved_mode
                if saved_mode()=='cpu':return compose_mapped(after,before,original,floating,bounds,size,mode,clip,source,record,optical,flow,body,fields,point_data,point_document,proof),'CPU · 用户设置'
                try:
                    from gpu_render import execute_pixel,DocumentCUDA
                    return execute_pixel(compose_mapped,after,before,original,floating,bounds,size,mode,clip,source,record,optical,flow,body,fields,point_data,DocumentCUDA(point_document) if record else None,proof,host_result=True),'CUDA'
                except Exception as e:
                    return compose_mapped(after,before,original,floating,bounds,size,mode,clip,source,record,optical,flow,body,fields,point_data,point_document,proof),'CPU回退：'+str(e).splitlines()[0][:90]
            self.display_renderer.submit(job)
        if self.display_image and self.display_image[0]==signature:
            self.photo=self.display_image[1];self.canvas.delete('all');position=a.view.to_canvas(x0,y0,a.size())
            if mode in ('wipe-before','wipe-original'):
                self.canvas.create_image(*position,anchor='nw',image=self.photo[0])
                cut=int(np.clip(round(a.size()[0]*self.wipe_position.get()/100-position[0]),0,size[0]))
                if cut<size[0]:
                    self.wipe_photo=tk.PhotoImage(master=self.canvas,width=size[0]-cut,height=size[1])
                    self.canvas.tk.call(str(self.wipe_photo),'copy',str(self.photo[1]),'-from',cut,0,size[0],size[1],'-to',0,0)
                    self.canvas.create_image(position[0]+cut,position[1],anchor='nw',image=self.wipe_photo)
                x=a.size()[0]*self.wipe_position.get()/100;radius=dp(a.root,10);cy=a.size()[1]/2
                self.canvas.create_line(x,0,x,a.size()[1],fill='white',width=dp(a.root,2),tags='wipe_handle')
                self.canvas.create_oval(x-radius,cy-radius,x+radius,cy+radius,fill='white',outline=COLORS['accent'],width=2,tags='wipe_handle')
                self.canvas.create_text(x,cy,text='↔',fill=COLORS['accent'],tags='wipe_handle')
            else:self.canvas.create_image(*position,anchor='nw',image=self.photo)
            label=self.compare.get()+' · '+self.display_image[2]
            if mode=='side':label='左：打开前 / 右：当前效果 · '+self.display_image[2]
            elif mode.startswith('wipe-'):label=('左：原图' if mode=='wipe-original' else '左：打开前')+' / 右：当前效果 · '+self.display_image[2]
            self.canvas.create_text(dp(a.root,14),dp(a.root,14),text=label,anchor='nw',fill=COLORS['text'],font=ui_font(a.root,10,'bold'))
            return True
        return False

    def poll(self):
        if not self.window.winfo_exists():return
        if self.active and self.window.grab_current() is None:self.window.grab_set()
        result=self.display_renderer.take()
        if result and result[2] is not None:
            from core import ROOT
            (ROOT/'color-workbench-error.log').write_text(result[2],encoding='utf8')
            self.app.status.set('对比预览未完成，请切回原图滑动对比；详情见 color-workbench-error.log。')
        if result and result[2] is None:
            _,(pixels,backend),_=result
            photos=[ImageTk.PhotoImage(Image.fromarray(p)) for p in pixels] if pixels.ndim==4 else ImageTk.PhotoImage(Image.fromarray(pixels))
            self.display_image=(self.display_key,photos,backend);self.redraw()
        if self.active and hasattr(self,'mask_ui'):self.mask_ui.sync()
        result=self.drag_renderer.take()
        if result and self.active and not self.app._render_pending and self.drag_identity==(id(self.app.document),id(self.app.session)) and self.drag_revision==(self.app.renderer.generation,id(self.app.output_float)):
            if result[2] is None:
                self.app._preview_frame=result[1][0];self.app.status.set('调色预览 · '+result[1][1]+' · 松开后更新完整照片');self.redraw()
            else:self.app.status.set('调色预览暂未完成；松开后更新完整照片。')
        if self.active and self.app._render_pending:self.drag_renderer.invalidate()
        self.window.after(40,self.poll)

    def preview_drag(self):
        a=self.app
        if not self.active or not a.document or a._render_pending or a.color_input is None:return
        if self.preview_skin_identity!=(id(a.document),id(a.session)):
            from creative_regions import regions
            self.preview_skin=regions(a.session,a.region_layers)['skin'].astype(np.float32);self.preview_skin_identity=(id(a.document),id(a.session))
        now=time.monotonic()
        if now-self.drag_preview_at<.05:return
        self.drag_preview_at=now;self.drag_identity=(id(a.document),id(a.session));self.drag_revision=(a.renderer.generation,id(a.output_float));self.drag_frame_key=None
        import creative_color as color
        data=copy.deepcopy(a.workflow_extensions.get('color',{}));data['process']=2 if a.color_process.get()=='专业浮点调色' else 1;data['values']={k:v.get() for k,v in a.creative_vars.items()};data['curve']=[v.get() for v in a.curve_vars]
        data.setdefault('hsl',{})[a.hsl_name.get()]=[v.get() for v in a.hsl_vars]
        try:data=color.validate(data)
        except ValueError:return
        source=a.color_input;original=a.document.rgb;scene=getattr(a.document,'scene',None);skin=self.preview_skin;layers=copy.deepcopy(a.region_layers);output=copy.deepcopy(a.workflow_extensions.get('output',{}))
        def job():
            from color_workbench_render import drag_preview
            from ai_runtime import saved_mode
            if saved_mode()=='cpu':return drag_preview(source,skin,original,scene,data,layers,output),'CPU · 用户设置'
            try:
                from gpu_render import execute_pixel
                return execute_pixel(drag_preview,source,skin,original,scene,data,layers,output,host_result=True),'CUDA'
            except Exception as e:return drag_preview(source,skin,original,scene,data,layers,output),'CPU回退：'+str(e).splitlines()[0][:70]
        self.drag_renderer.submit(job)

    def display_drag(self,bounds,size,localcut):
        a=self.app;signature=(id(a._preview_frame),bounds,size,localcut,str(a.workflow_extensions.get('optics',{})))
        if self.drag_frame_key!=signature:
            from color_workbench_render import drag_display
            import photo_body,face_reshape
            args=(a._preview_frame,a.session.original,bounds,size,a.document.rgb.shape,a.workflow_extensions.get('optics',{}),a.liquify_state['flow'] if a.liquify_active() else None,photo_body.current_field(a.photo_body_cache) if a.photo_body_changed else None,face_reshape._fields(a.reshape_cache,a.face_settings),localcut)
            try:
                from gpu_render import execute_pixel
                pixels=execute_pixel(drag_display,*args,host_result=True)
            except Exception as error:
                from gpu_render import record_cpu_recovery
                record_cpu_recovery('调色预览采样',error);a.status.set('调色预览采样使用CPU回退：'+str(error).splitlines()[0][:70]);pixels=drag_display(*args)
            self.drag_frame_image=Image.fromarray(pixels);self.drag_frame_key=signature
        return self.drag_frame_image
