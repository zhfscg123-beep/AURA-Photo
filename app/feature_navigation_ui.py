"""Explicit module ownership, grouped menus and local parameter navigation."""
import tkinter as tk
from tkinter import ttk
from dark_ui import COLORS,Section,ParameterScale,ToolButton
from dpi_support import dp,ui_font
from workspace_ui import CategoryButton
from feature_catalogue import GROUPS,SECTIONS,LEGACY,Feature,search
from rounded_menu import RoundedMenu

class FeatureNavigationUI:
    def setup_feature_navigation(self):
        actual=[s for s in self.settings_panel.winfo_children() if isinstance(s,Section)]+self.color_workbench.external
        self.nav_groups={g.key:g for g in GROUPS};self.nav_sections={};self.section_owners={};self._visited_categories=set()
        for group in GROUPS:
            for key in group.sections:
                attr,title,description,aliases=SECTIONS[key];section=getattr(self,attr)
                if section in self.section_owners:raise ValueError('重复功能归属：'+key)
                self.nav_sections[key]=section;self.section_owners[section]=group.key
                section.title=title;section.caption=title
                section.header.configure(text=('▾  ' if section.opened else '▸  ')+title)
        if set(actual)!=set(self.section_owners):raise ValueError('存在未明确归属的功能模块，请检查导航目录。')
        self.category_sections={g.key:[self.nav_sections[k] for k in g.sections] for g in GROUPS}
        self.nav_description=tk.StringVar()
        self.nav_description_label=ttk.Label(self.person_control.master,textvariable=self.nav_description,style='Muted.TLabel',wraplength=270)
        self.nav_description_label.pack(fill='x',padx=8,pady=(0,8),before=self.person_control)
        self.category_buttons={}
        for group in GROUPS:
            button=CategoryButton(self.category_rail,group.key,group.icon,lambda k=group.key:self.select_category(k));button.pack(pady=2)
            button.bind('<MouseWheel>',lambda e:(self.rail_scroll.yview_scroll(-int(e.delta/120),'units'),'break')[1]);self.category_buttons[group.key]=button
            button.bind('<FocusIn>',lambda e,b=button:self.reveal_rail_button(b),add='+')
        self.install_feature_actions();self.select_category('调色');self.build_feature_index()
        self.root.bind('<Control-k>',lambda e:self.show_feature_search());self.root.bind('<Control-K>',lambda e:self.show_feature_search())
        self.root.bind('<ButtonPress-1>',lambda e:self._navigation_menu.dismiss_outside(e) if getattr(self,'_navigation_menu',None) is not None else None,add='+')
    def reveal_rail_button(self,button):
        self.root.update_idletasks();top=self.rail_scroll.canvasy(0);y=button.winfo_y();h=button.winfo_height();viewport=self.rail_scroll.winfo_height()
        if y<top:self.rail_scroll.yview_moveto(y/max(1,self.category_rail.winfo_height()))
        elif y+h>top+viewport:self.rail_scroll.yview_moveto((y+h-viewport)/max(1,self.category_rail.winfo_height()))
    def sync_navigation_scope(self):
        key=getattr(self,'active_category',None)
        if key not in getattr(self,'nav_groups',{}):return
        group=self.nav_groups[key];self.nav_description.set(group.scope+' · '+group.purpose)
        uses_person=key not in ('调色','背景')
        if uses_person:
            if not self.person_control.winfo_manager():self.person_control.pack(fill='x',padx=8,pady=(0,10),after=self.nav_description_label)
            self.person_control.configure(state='readonly' if self.face_settings and not self.busy else 'disabled')
        else:self.person_control.pack_forget()
    def show_feature_menu(self):
        menu=self.new_navigation_menu('工具')
        if menu is None:return
        menu.add_command(label='搜索功能 / 参数    Ctrl+K',command=self.show_feature_search);menu.add_separator()
        for group in GROUPS:
            child=RoundedMenu(self.root,group.key,parent=menu)
            child.add_command(label='查看'+group.key+'模块',command=lambda k=group.key:self.select_category(k));child.add_separator()
            for key in group.sections:child.add_command(label=SECTIONS[key][1],command=lambda k=key:self.focus_section(self.nav_sections[k]))
            menu.add_cascade(label=group.key,menu=child)
        self.post_navigation_menu(menu,self.tools_nav_button)
    def new_navigation_menu(self,title):
        old=getattr(self,'_navigation_menu',None)
        if old is not None and old.visible and old.title==title:old.unpost();return None
        if old is not None and old.winfo_exists():old.destroy()
        self._navigation_menu=RoundedMenu(self.root,title);return self._navigation_menu
    def post_navigation_menu(self,menu,button,index=None):
        self.file_popup.place_forget();self.close_settings()
        menu.anchor=button
        menu.post(button.winfo_rootx(),button.winfo_rooty()+button.winfo_height())
        if index is not None:menu.activate(index);menu.focus_set()
    def show_edit_menu(self,index=None):
        menu=self.new_navigation_menu('编辑')
        if menu is None:return
        menu.add_command(label='撤销    Ctrl+Z',command=self.undo,state='normal' if self.document and not self.busy else 'disabled')
        menu.add_command(label='重做    Ctrl+Y',command=self.redo,state='normal' if self.document and not self.busy else 'disabled')
        menu.add_separator();menu.add_command(label='编辑记录 · 逐笔管理',command=self.show_edit_records,state='normal' if self.document and not self.busy else 'disabled')
        menu.add_command(label='效果开关与局部擦回',command=lambda:self.focus_section(self.effect_panel))
        self.post_navigation_menu(menu,self.edit_nav_button,index)
    def show_view_menu(self,index=None):
        menu=self.new_navigation_menu('视图')
        if menu is None:return
        for title,fn in [('适合窗口',self.fit),('面部视图',self.facefit),('100% 原图像素',self.actual)]:menu.add_command(label=title,command=fn)
        menu.add_separator();menu.add_checkbutton(label='显示修复选区',variable=self.overlay,command=self.draw)
        menu.add_checkbutton(label='显示当前部位蒙版',variable=self.mask_overlay,command=self.draw)
        self.post_navigation_menu(menu,self.view_nav_button,index)
    def build_feature_index(self):
        features=[];var_names={str(v):k for k,v in vars(self).items() if isinstance(v,tk.Variable)}
        for name in ('creative_vars','scene_vars','background_vars'):
            var_names.update({str(v):k for k,v in getattr(self,name,{}).items()})
        def walk(widget,path,description,aliases,section,location):
            if isinstance(widget,Section):
                if widget.title=='界面显示':aliases+=' DPI 缩放 分辨率 高分屏 屏幕 display'
                elif widget.title=='导入设置':aliases+=' 默认 推荐 自动美颜 import defaults'
                elif widget.title=='自动保存与缓存':aliases+=' 恢复 缓存 空间 autosave recovery cache'
                parent_path=' › '.join(path)
                path=path+[widget.title]
                prefix='module:' if widget is section and location=='panel' else 'section:'
                features.append(Feature(prefix+str(widget),widget.title,parent_path,description,aliases,widget.header,widget,'section' if location=='panel' else location))
            title=None;target=widget;detail=description
            if isinstance(widget,ParameterScale):
                title=widget.title;target=widget.entry;aliases=aliases+' '+var_names.get(str(widget.variable),'')
                detail=description+f'\n输入范围：{widget.lo:g}–{widget.hi:g}。按 Enter 应用，按 Esc 取消。'
            elif isinstance(widget,ToolButton):title=widget.label;detail='绘制工具；定位后点击图标启用。'+description
            elif isinstance(widget,(ttk.Button,tk.Button)):
                title=widget.cget('text');detail='操作入口；定位后点击执行。'+description
            elif isinstance(widget,ttk.Checkbutton):title=widget.cget('text');detail='开关 / 范围选项；定位不会自动修改。'+description
            elif isinstance(widget,ttk.Combobox):
                title=getattr(widget,'_aura_search_name',None)
                if not title:
                    labels=[c.cget('text') for c in widget.master.winfo_children() if isinstance(c,ttk.Label) and 0<len(c.cget('text'))<14 and not any(p in c.cget('text') for p in ('。','\n','；'))]
                    title=labels[0] if labels else (path[-1]+'选择' if path else '选项')
                aliases+=' '+str(widget.cget('values'))
            if title:
                features.append(Feature('control:'+str(widget),title,' › '.join(path),detail,aliases,target,section,location))
            for child in widget.winfo_children():walk(child,path,description,aliases,section,location)
        for group in GROUPS:
            for key in group.sections:
                _,title,description,aliases=SECTIONS[key];walk(self.nav_sections[key],[group.key],group.scope+'：'+description,aliases,self.nav_sections[key],'panel')
        walk(self.color_workbench.mask_panel,['调色','蒙版'],'局部调色：软笔刷、可编辑渐变与多组件范围。','flow density 流量 密度 组件 线性 径向 渐变 局部 蒙版',self.color_workbench.mask_panel,'panel')
        walk(self.file_popup,['文件'],'导入照片、打开或保存项目、视频快速预览、实况美颜、导出成片及批量处理。','import open save export project batch video 视频 预览 时间轴 文件',None,'file')
        walk(self.settings_content,['设置'],'全局设置，不属于单张照片的修图参数。','preferences settings 全局',None,'settings')
        for key,title,path,description,target in (
            ('library','照片库','照片库','搜索文件名、评分、筛选和双图对照。','library'),
            ('records','编辑记录','编辑 › 编辑记录','逐笔显示、隐藏、修改不透明度或删除手动记录。','records'),
            ('undo','撤销','编辑 › 撤销','打开编辑菜单；需主动点击撤销，不会因搜索而改动照片。',('edit',0)),
            ('redo','重做','编辑 › 重做','打开编辑菜单；需主动点击重做。',('edit',1)),
            ('fit','适合窗口','视图 › 适合窗口','查看完整照片，不改变导出尺寸。',('view',0)),
            ('face','面部视图','视图 › 面部视图','定位人物面部以检查细节。',('view',1)),
            ('actual','100% 原图像素','视图 › 100% 原图像素','查看原图像素比例；不是屏幕DPI设置。',('view',2)),
            ('shortcuts','快捷键','快捷键','查看软件的键盘操作。','shortcuts')):
            features.append(Feature('action:'+key,title,path,description,'历史 对比' if key=='records' else key,target,None,'action'))
        self.feature_index=features
    def reveal_feature(self,item):
        if item.location=='action':
            if isinstance(item.target,tuple):
                kind,index=item.target
                button=self.edit_nav_button if kind=='edit' else self.view_nav_button
                self.file_popup.place_forget();self.close_settings();button.focus_set()
                self.status.set('已定位入口：'+item.path+'。请展开对应菜单选择操作。');return
            if item.target=='library':self.show_photo_library()
            elif item.target=='records':
                if self.document:self.show_edit_records()
                else:self.status.set('请先导入照片，再打开编辑记录。')
            elif item.target=='shortcuts':self.show_shortcuts()
            return
        if self.color_workbench.owns(item.target):self.color_workbench.focus_section(item.section)
        elif item.location in ('panel','section'):self.focus_section(item.section)
        elif item.location=='file':self.file_popup.place_forget();self.toggle_file()
        elif item.location=='settings':
            if not self.settings_open:self.toggle_settings()
        ancestors=[];node=item.target
        while node is not None:
            if isinstance(node,Section):ancestors.append(node)
            node=node.master
        for ancestor in reversed(ancestors):
            if not ancestor.opened:ancestor.toggle()
        self.root.update_idletasks()
        target=item.target
        in_color=self.color_workbench.owns(target)
        content=self.settings_content if item.location=='settings' else self.color_workbench.panel if in_color else self.settings_panel
        scroll=self.drawer_scroll if item.location=='settings' else self.color_workbench.scroll if in_color else self.settings_scroll
        if item.location!='file':
            offset=target.winfo_rooty()-content.winfo_rooty()-dp(self.root,14)
            scroll.yview_moveto(max(0,offset)/max(1,content.winfo_height()))
        if isinstance(target,(ttk.Entry,ttk.Combobox)) and str(target.cget('state'))=='disabled':target=target.master
        target.focus_set()
        if isinstance(target,ttk.Entry):target.selection_range(0,'end')
        self.status.set('已定位：'+(item.path if item.path.endswith(item.title) else item.path+' › '+item.title))
    def show_feature_search(self,event=None):
        if self.drag:self.status.set('请先松开当前画笔或拖动，再搜索功能。');return 'break'
        previous=getattr(self,'feature_search_window',None)
        if previous is not None and previous.winfo_exists():previous.lift();self.feature_search_entry.focus_set();return 'break'
        self.build_feature_index();window=tk.Toplevel(self.root);window.title('搜索功能与参数');window.transient(self.root)
        window.geometry(f'{min(dp(self.root,780),self.root.winfo_screenwidth()-dp(self.root,32))}x{min(dp(self.root,580),self.root.winfo_screenheight()-dp(self.root,70))}')
        frame=ttk.Frame(window,padding=14);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='搜索功能或参数',font=ui_font(self.root,13,'bold')).pack(anchor='w')
        query=tk.StringVar();entry=ttk.Entry(frame,textvariable=query);entry.pack(fill='x',pady=10)
        examples=ttk.Label(frame,text='例如：瘦脸、身体美白、脖子、吸管、眼周纹、液化、HSL、导出',style='Muted.TLabel',wraplength=dp(self.root,720));examples.pack(anchor='w')
        area=ttk.Frame(frame);area.pack(fill='both',expand=True,pady=10)
        tree=ttk.Treeview(area,columns=('path',),show='tree headings',selectmode='browse',height=9);tree.heading('#0',text='功能 / 参数');tree.heading('path',text='所属位置')
        tree.column('#0',width=dp(self.root,270));tree.column('path',width=dp(self.root,420));tree.pack(side='left',fill='both',expand=True)
        ttk.Scrollbar(area,command=tree.yview).pack(side='right',fill='y');bar=area.winfo_children()[-1];tree.configure(yscrollcommand=bar.set)
        note=tk.StringVar();detail=tk.StringVar();note_label=ttk.Label(frame,textvariable=note,style='Muted.TLabel',wraplength=dp(self.root,720));note_label.pack(anchor='w')
        detail_label=ttk.Label(frame,textvariable=detail,wraplength=dp(self.root,720));detail_label.pack(fill='x',pady=8)
        row=ttk.Frame(frame);row.pack(fill='x');ttk.Label(row,text='↑↓ 选择 · Enter 定位 · Esc 关闭',style='Muted.TLabel').pack(side='left')
        found=[]
        def selection(e=None):
            ids=tree.selection();text=found[int(ids[0])].description if ids else ''
            if ids:
                item=found[int(ids[0])]
                if isinstance(item.target,tk.Widget) and 'state' in item.target.keys() and str(item.target.cget('state'))=='disabled':
                    text+=' 当前不可用：'+('请先导入照片。' if not self.document else '正在计算，请等待完成。' if self.busy else '请查看模块中的启用条件或识别提示。')
            detail.set(text)
        def update(*_):
            found[:]=search(self.feature_index,query.get());tree.delete(*tree.get_children())
            for i,item in enumerate(found):tree.insert('','end',iid=str(i),text=item.title,values=(item.path,))
            note.set(f'显示 {len(found)} 项；输入更多关键词缩小范围。' if found else '未找到匹配功能。试试“磨皮”“液化”“脖子”或“导出”；也可清空后浏览全部模块。')
            if found:tree.selection_set('0');tree.focus('0')
            selection()
        def locate(e=None):
            if not tree.selection():return 'break'
            item=found[int(tree.selection()[0])];window.destroy();self.reveal_feature(item);return 'break'
        def move(e,step):
            if found:
                index=int(tree.selection()[0]) if tree.selection() else 0;index=max(0,min(len(found)-1,index+step));tree.selection_set(str(index));tree.focus(str(index));tree.see(str(index));selection()
            return 'break'
        ttk.Button(row,text='定位功能',command=locate).pack(side='right');ttk.Button(row,text='关闭',command=window.destroy).pack(side='right',padx=6)
        trace=query.trace_add('write',update);entry.bind('<Down>',lambda e:move(e,1));entry.bind('<Up>',lambda e:move(e,-1));entry.bind('<Return>',locate)
        tree.bind('<<TreeviewSelect>>',selection);tree.bind('<Double-Button-1>',locate);tree.bind('<Return>',locate)
        window.bind('<Escape>',lambda e:(window.destroy(),'break')[1]);window.protocol('WM_DELETE_WINDOW',window.destroy)
        def cleanup(e):
            if e.widget is window:
                try:query.trace_remove('write',trace)
                except tk.TclError:pass
        window.bind('<Destroy>',cleanup,add='+')
        def resize(e):
            if e.widget is window:
                width=max(dp(self.root,140),window.winfo_width()-dp(self.root,32))
                for label in (examples,note_label,detail_label):label.configure(wraplength=width)
        window.bind('<Configure>',resize,add='+')
        self.feature_search_window=window;self.feature_search_entry=entry;self.feature_search_query=query;self.feature_search_tree=tree;self.feature_search_note=note
        update();entry.focus_set();return 'break'
