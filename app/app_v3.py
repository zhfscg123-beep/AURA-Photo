"""AURA: responsive portrait workspace with RAW and editable projects."""
import sys,time,tkinter as tk,copy
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
import queue,threading
import numpy as np
import cv2
from PIL import Image,ImageTk
from app_v2 import App as BaseApp
from core import ROOT
from damo_engine import PortraitAISession,inpaint_portrait
from editing import Viewport,Selection
from complexion import recommend,render_skin,small_blemishes
from photo_document import open_document,export_document,to_uint8,sha256_file,RAW_EXTENSIONS
from project_io import save_project,read_project
from dark_ui import COLORS,Section,ToolButton,ParameterScale,style
from portrait_effects import wrinkle_and_circles,eye_wrinkle_pending,prepare_eye_wrinkles
import camera_profiles
from ai_runtime import RUNTIME,saved_mode,save_mode,preload_portrait_async
from photo_library import PhotoLibrary
from patch_repair import apply_patches,choose_source
from beauty_settings import DEFAULTS,NAMES,EXTRA,ZONES,normalized,neutral_values
from beauty_preset import write_preset,read_preset
from app_preferences import auto_recommend_enabled,save_auto_recommend
from skin_enhance import enhance_skin
from region_masks import apply_layers,packed_layers,unpacked_layers,equal_layers
from mask_ui import RegionMaskUI
from feature_ui import FeatureUI
from feature_catalog import ADVANCED
from face_details import prepare_face_repairs,apply_face_repairs,apply_face_details,face_repairs_pending,protect_face_details
from body_details import prepare_body,apply_body,body_pending,body_notices
from feature_catalog import BODY
from color_ui import ColorUI
from skin_color import apply_skin_color
from volume_ui import VolumeUI
from face_volume import apply_face_volume
from form_ui import FormUI
from body_shape import prepare_forms,apply_forms,forms_pending,chin_shadow
from workspace_ui import WorkspaceUI,fit_screen,enable_dpi
from edition_update_ui import UpdateUI
from dpi_support import set_ui_dpi,dp,scale_widget_tree,ui_font
from reshape_ui import ReshapeUI
from reshape_settings import RESHAPE,SMART,KEYS as SHAPE_KEYS
import face_reshape
import liquify
from liquify_ui import LiquifyUI
from smart_face_ui import SmartFaceUI
from file_drop import FileDrop,photo_paths
from retouch_ui import RetouchUI, VARS as MANUAL_VARS
import manual_retouch
from app_mutex import register_app_mutex
from liquify_guides_ui import LiquifyGuidesUI
from workflow_ui import WorkflowUI
from batch_ui import BatchUI
from effect_ui import EffectUI
from workflow_extensions import packed_state,restore_state,equal_state
from smart_mask_ui import SmartMaskUI
from creative_color_ui import CreativeColorUI
from creative_scene_ui import CreativeSceneUI
from composition_ui import CompositionUI
from responsive_render_ui import ResponsiveRenderUI
from library_ui import LibraryUI
from edit_records_ui import EditRecordsUI
from person_mapping_ui import PersonMappingUI
from feature_navigation_ui import FeatureNavigationUI
from feature_actions_ui import FeatureActionsUI
from live_crop import LiveCropUI
from beauty_mask_ui import BeautyMaskUI
from photo_edition_ui import LivePhotoUI
from photo_edition_ui import VideoPreviewUI
from photo_body_ui import PhotoBodyUI
import photo_body

class App(UpdateUI,VideoPreviewUI,PhotoBodyUI,LivePhotoUI,BeautyMaskUI,FeatureActionsUI,LiveCropUI,FeatureNavigationUI,PersonMappingUI,LibraryUI,EditRecordsUI,ResponsiveRenderUI,CompositionUI,CreativeSceneUI,CreativeColorUI,SmartMaskUI,EffectUI,BatchUI,WorkflowUI,WorkspaceUI,LiquifyGuidesUI,RetouchUI,LiquifyUI,SmartFaceUI,ReshapeUI,FormUI,VolumeUI,ColorUI,FeatureUI,RegionMaskUI,BaseApp):
    def __init__(self,root):
        self._installer_mutex=register_app_mutex(root)
        self.root=root;self.session=None;self.selection=None;self.path=None;self.output=None;self.document=None;self.output_float=None
        self.generated=None;self.done_mask=None;self.meta={};self.jobs=queue.Queue();self.busy=False;self.cancel=threading.Event()
        self.defaults={};self.recommendation={};self.small_mask=None;self.view=Viewport();self.drag=None;self.space=False;self.controls=[];self.smooth_cache=None
        self.recent=[];self.film_photos=[];self.history=[];self.nav_photo=None;self.nav_box=None;self.project_path=None
        self.slim_cache={};self.slim_ready=False;self.slim_changed=None;self.form_cache={};self.form_changed=None;self.pointer=None;self.tool_buttons={}
        self.show_excluded=True;self.selection_legend='橙：AI 选区 / 蓝：手动补选 / 红：已取消'
        self.edit_states=[];self.edit_index=-1;self.restoring_edit=False
        self.drop_import_queue=[];self.library=PhotoLibrary();self.import_queue=[];self.batch=False;self.batch_errors=[];self.settings_clipboard=None
        self.face_settings=[];self.face_defaults=[];self.active_face=0;self.loading_face=False
        self.patches=[];self.selected_patch=None;self.loading_patch=False
        set_ui_dpi(root);root.title('AURA Photo · 独立静态照片版');fit_screen(root);style(root);self.set_app_icon();self.settings_open=False
        self.auto_recommend=tk.BooleanVar(value=auto_recommend_enabled())
        self.smooth=tk.DoubleVar(value=0);self.repair=tk.DoubleVar(value=75);self.whiten=tk.DoubleVar(value=0);self.texture=tk.DoubleVar(value=50)
        self.protect_dark_points=tk.BooleanVar(value=False)
        self.split=tk.DoubleVar(value=0);self.threshold=tk.DoubleVar(value=.35);self.radius=tk.IntVar(value=8);self.feather=tk.DoubleVar(value=0);self.overlay=tk.BooleanVar(value=False);self.mode=tk.StringVar(value='pan')
        self.tool_hint=tk.StringVar(value='浏览：拖动平移 · Ctrl＋滚轮缩放')
        self.patch_opacity=tk.DoubleVar(value=100)
        self.device_summary=tk.StringVar(value=RUNTIME.summary());self.device_details=tk.StringVar(value='读取照片时检查 GPU；GPU 不可用自动使用 CPU。')
        self.device_mode=tk.StringVar(value='自动 · CPU＋GPU' if saved_mode()=='auto' else '仅 CPU')
        self.raw_ev=tk.DoubleVar(value=0);self.raw_wb=tk.StringVar(value='机内白平衡');self.zoomlabel=tk.StringVar(value='适合');self.summary=tk.StringVar(value='打开照片，自动生成美颜版本。')
        self.camera_look=tk.BooleanVar(value=True)
        self.camera_mode=tk.StringVar(value='机型配置文件 · RAW16');self.camera_profile=tk.StringVar(value='按拍摄风格匹配')
        self.wrinkles=tk.DoubleVar(value=0);self.dark_circles=tk.DoubleVar(value=0);self.slim=tk.DoubleVar(value=0)
        self.filename=tk.StringVar(value='尚未打开照片');self.fileinfo=tk.StringVar(value='Sony / Canon / Nikon / Fujifilm');self.status=tk.StringVar(value='打开 RAW 或照片开始。')
        self.person=tk.StringVar(value='尚未识别人像')
        for name,_,_,_ in EXTRA+ZONES+ADVANCED+RESHAPE+SMART:setattr(self,name,tk.DoubleVar(value=0))
        self.init_masks()
        self.init_features()
        self.init_color()
        self.init_reshape()
        self.init_liquify()
        self.init_smart_face()
        self.init_liquify_guides()
        self.init_retouch()
        self.init_workflow()
        self.init_updates()
        self.init_effects()
        self.init_smart_masks()
        self.init_creative_color()
        self.init_creative_scene()
        self.init_composition()
        self.init_responsive_render()
        self.init_catalog()
        self.init_feature_actions();self.init_live_crop();self.init_beauty_mask();self.init_photo_body()
        from color_workbench import ColorWorkbench
        self.color_workbench=ColorWorkbench(self)
        top=ttk.Frame(root,padding=(16,12));top.pack(fill='x');self.top=top
        if (ROOT/'assets/aura.png').exists():
            size=dp(root,32);self.brand_icon=ImageTk.PhotoImage(Image.open(ROOT/'assets/aura.png').resize((size,size),Image.Resampling.LANCZOS))
            self.brand_label=ttk.Label(top,image=self.brand_icon);self.brand_label.pack(side='left',padx=(0,10))
        ttk.Label(top,text='AURA Photo',style='Title.TLabel').pack(side='left')
        self.file_nav_button=ttk.Button(top,text='文件',width=0,command=self.toggle_file);self.file_nav_button.pack(side='left',padx=(14,4))
        self.edit_nav_button=ttk.Button(top,text='编辑',width=0,command=self.show_edit_menu);self.edit_nav_button.pack(side='left',padx=4)
        self.view_nav_button=ttk.Button(top,text='视图',width=0,command=self.show_view_menu);self.view_nav_button.pack(side='left',padx=4)
        self.tools_nav_button=ttk.Button(top,text='工具',width=0,command=self.show_module_menu);self.tools_nav_button.pack(side='left',padx=4)
        self.library_nav_button=ttk.Button(top,text='照片库',width=0,command=self.show_photo_library);self.library_nav_button.pack(side='left',padx=4)
        self.settings_nav_button=ttk.Button(top,text='设置',width=0,command=self.toggle_settings);self.settings_nav_button.pack(side='right',padx=4)
        self.shortcuts_nav_button=ttk.Button(top,text='快捷键',width=0,command=self.show_shortcuts);self.shortcuts_nav_button.pack(side='right',padx=4)
        self.search_nav_button=ttk.Button(top,text='搜索功能  Ctrl+K',width=0,command=self.show_feature_search);self.search_nav_button.pack(side='right',padx=6)
        self.build_file_popup()
        workspace=ttk.Frame(root);workspace.pack(fill='both',expand=True)
        left=ttk.Frame(workspace,width=225,padding=(10,0));left.pack(side='left',fill='y');left.pack_propagate(False);self.left_panel=left
        self.left_scroll=tk.Canvas(left,bg=COLORS['panel'],highlightthickness=0);self.left_scroll.pack(side='left',fill='both',expand=True)
        left_bar=ttk.Scrollbar(left,orient='vertical',command=self.left_scroll.yview);left_bar.pack(side='right',fill='y');self.left_scroll.configure(yscrollcommand=left_bar.set)
        left=ttk.Frame(self.left_scroll);left_window=self.left_scroll.create_window(0,0,window=left,anchor='nw')
        left.bind('<Configure>',lambda e:self.left_scroll.configure(scrollregion=self.left_scroll.bbox('all')))
        self.left_scroll.bind('<Configure>',lambda e:self.left_scroll.itemconfigure(left_window,width=e.width))
        section=Section(left,'导航器');self.navigator=tk.Canvas(section.body,height=210,background=COLORS['canvas'],highlightthickness=0);self.navigator.pack(fill='x');self.navigator.bind('<Button-1>',self.nav_click)
        row=ttk.Frame(section.body);row.pack(fill='x',pady=(8,0))
        self.navigator_buttons=[]
        for column,(title,fn) in enumerate([('适合',self.fit),('面部',self.facefit),('1:1',self.actual)]):
            row.columnconfigure(column,weight=1,uniform='navigator')
            button=ttk.Button(row,text=title,width=0,style='Compact.TButton',command=fn)
            button.grid(row=0,column=column,sticky='ew',padx=dp(root,1));self.navigator_buttons.append(button)
        ttk.Label(section.body,textvariable=self.zoomlabel,style='Muted.TLabel').pack(anchor='w',pady=(6,0))
        section=Section(left,'照片信息');ttk.Label(section.body,textvariable=self.filename,wraplength=180).pack(anchor='w')
        ttk.Label(section.body,textvariable=self.fileinfo,style='Muted.TLabel',wraplength=185).pack(anchor='w',pady=(8,0))
        section=Section(left,'操作记录',opened=False);self.historylist=tk.Listbox(section.body,height=9,bg=COLORS['panel'],fg=COLORS['muted'],highlightthickness=0,borderwidth=0,selectbackground=COLORS['raised'],font=('Microsoft YaHei UI',9));self.historylist.pack(fill='x')
        self.navigation_hint=ttk.Label(left,text='拖动平移 · Ctrl＋滚轮缩放\n补选时 Ctrl＋滚轮调大小\n空格临时平移 · Esc 返回浏览',style='Muted.TLabel',wraplength=200)
        self.navigation_hint.pack(side='bottom',anchor='w',pady=12)
        def left_wheel(widget):
            widget.bind('<MouseWheel>',lambda e:(self.left_scroll.yview_scroll(-int(e.delta/120),'units'),'break')[1])
            for child in widget.winfo_children():left_wheel(child)
        left_wheel(left);left_wheel(self.left_scroll)
        from scroll_ui import attach_scroll
        self.left_scrolling=attach_scroll(self.left_scroll,left,left_bar,compact=True)
        self.navigator.bind('<Configure>',lambda e:(self.make_navigation(),self.draw()))
        rail=ttk.Frame(workspace,width=104,padding=(5,8));rail.pack(side='right',fill='y',padx=(4,12));rail.pack_propagate(False);self.rail_panel=rail
        self.rail_scroll=tk.Canvas(rail,width=68,bg=COLORS['panel'],highlightthickness=0);self.rail_scroll.pack(side='left',fill='both',expand=True)
        rail_bar=ttk.Scrollbar(rail,orient='vertical',command=self.rail_scroll.yview);rail_bar.pack(side='right',fill='y');self.rail_scroll.configure(yscrollcommand=rail_bar.set)
        self.category_rail=ttk.Frame(self.rail_scroll);rail_window=self.rail_scroll.create_window(0,0,window=self.category_rail,anchor='nw')
        self.category_rail.bind('<Configure>',lambda e:self.rail_scroll.configure(scrollregion=self.rail_scroll.bbox('all')))
        self.rail_scroll.bind('<Configure>',lambda e:self.rail_scroll.itemconfigure(rail_window,width=e.width))
        self.rail_scrolling=attach_scroll(self.rail_scroll,self.category_rail,rail_bar,compact=True)
        right=ttk.Frame(workspace,width=330,padding=(8,0));right.pack(side='right',fill='y');right.pack_propagate(False);self.right_panel=right
        heading=ttk.Frame(right,padding=(8,9));heading.pack(fill='x')
        self.category_title=tk.StringVar(value='人像');ttk.Label(heading,textvariable=self.category_title,font=('Microsoft YaHei UI',13,'bold')).pack(side='left')
        self.person_control=ttk.Combobox(right,textvariable=self.person,values=[],state='disabled');self.person_control.pack(fill='x',padx=8,pady=(0,10));self.person_control.bind('<<ComboboxSelected>>',self.switch_person)
        scroll_container=ttk.Frame(right);scroll_container.pack(fill='both',expand=True)
        scroll=tk.Canvas(scroll_container,background=COLORS['panel'],highlightthickness=0);scroll.pack(side='left',fill='both',expand=True)
        bar=ttk.Scrollbar(scroll_container,orient='vertical',command=scroll.yview);bar.pack(side='right',fill='y');scroll.configure(yscrollcommand=bar.set)
        panel=ttk.Frame(scroll);window=scroll.create_window(0,0,window=panel,anchor='nw')
        self.settings_scroll=scroll;self.settings_panel=panel
        panel.bind('<Configure>',lambda e:scroll.configure(scrollregion=scroll.bbox('all')));scroll.bind('<Configure>',lambda e:scroll.itemconfigure(window,width=e.width))
        self.settings_scrolling=attach_scroll(scroll,panel,bar)
        self.color_entry_panel=Section(panel,'独立调色工作台',opened=True)
        ttk.Label(self.color_entry_panel.body,text='在独立窗口中调整影调、颜色与RAW显影，再返回人像美颜。',style='Muted.TLabel',wraplength=275).pack(fill='x')
        ttk.Button(self.color_entry_panel.body,text='打开调色工作台',style='Accent.TButton',command=self.color_workbench.open).pack(fill='x',pady=8)
        section=Section(self.color_workbench.hist_host,'直方图');self.histogram_panel=section;self.histogram=tk.Canvas(section.body,height=92,bg=COLORS['canvas'],highlightthickness=0);self.histogram.pack(fill='x')
        ttk.Label(section.body,text='RGB / sRGB',style='Muted.TLabel').pack(anchor='e',pady=(4,0))
        section=Section(self.color_workbench.panel,'机内效果 / RAW 显影',opened=False);self.raw_panel=section
        self.camera_control=ttk.Checkbutton(section.body,text='应用相机风格（默认）',variable=self.camera_look,command=self.enable);self.camera_control.pack(anchor='w');self.controls.append(self.camera_control)
        self.source_control=ttk.Combobox(section.body,textvariable=self.camera_mode,values=['机型配置文件 · RAW16','机内预览 · 8位'],state='readonly');self.source_control.pack(fill='x',pady=(6,0));self.source_control.bind('<<ComboboxSelected>>',lambda e:self.enable());self.controls.append(self.source_control)
        self.profile_control=ttk.Combobox(section.body,textvariable=self.camera_profile,values=['按拍摄风格匹配'],state='readonly');self.profile_control.pack(fill='x',pady=(6,0));self.controls.append(self.profile_control)
        self.profile_import=self.button(section.body,'导入此机型 DCP 配置',self.import_profile)
        self.raw_label=ttk.Label(section.body,text='打开 RAW 后检查内嵌机内预览',style='Muted.TLabel',wraplength=275);self.raw_label.pack(anchor='w',pady=(6,0))
        self.button(section.body,'相机设置导入详情',lambda:__import__('camera_import').show(self))
        self.button(section.body,'成片检查',lambda:__import__('production_review_ui').show(self))
        ttk.Label(section.body,text='DCP 按机型校验，保留16位显影精度。相机专有美颜不属于色彩配置。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(6,0))
        ttk.Label(section.body,text='白平衡',style='Muted.TLabel').pack(anchor='w',pady=(8,3))
        self.wb_control=ttk.Combobox(section.body,textvariable=self.raw_wb,values=['机内白平衡','自动白平衡','日光白平衡','自定义色温'],state='readonly');self.wb_control.pack(fill='x');self.controls.append(self.wb_control)
        self.raw_process_control=ttk.Combobox(section.body,textvariable=self.raw_process,values=['专业线性显影','兼容相机风格显影'],state='readonly');self.raw_process_control.pack(fill='x',pady=4);self.controls.append(self.raw_process_control)
        self.slider(section.body,'RAW 自定义色温 K',self.raw_kelvin,2000,50000,lambda:None)
        self.slider(section.body,'RAW 绿／洋红偏色',self.raw_tint,-100,100,lambda:None)
        ttk.Label(section.body,text='专业线性模式保留宽色域与高光余量；相机DCP风格选择兼容模式。',style='Muted.TLabel',wraplength=275).pack(fill='x')
        self.raw_slider=self.slider(section.body,'曝光补偿',self.raw_ev,-2,3,command=lambda:None,decimals=2)
        self.raw_apply=self.button(section.body,'应用来源设置',self.redevelop)
        section=Section(panel,'AI 人像 · 面部与身体美颜');self.portrait_panel=section
        ttk.Label(section.body,text='按当前人物独立调参；身体专项在“身体”模块中调整。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(0,6))
        ttk.Label(section.body,textvariable=self.summary,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(0,8))
        for title,var in [('祛痘',self.repair),('磨皮',self.smooth),('美白',self.whiten),('纹理',self.texture)]:self.slider(section.body,title,var,0,100,self.refresh)
        self.dark_point_control=ttk.Checkbutton(section.body,text='保护深色点 · 当前照片（可选）',variable=self.protect_dark_points,command=self.toggle_dark_point_protection)
        self.dark_point_control.pack(anchor='w',pady=4);self.controls.append(self.dark_point_control)
        self.build_beauty_mask_controls(section.body)
        self.button(section.body,'使用推荐参数',self.apply_defaults)
        self.preset_export=self.button(section.body,'导出当前人像美颜配置',self.export_beauty_preset)
        self.preset_import=self.button(section.body,'应用美颜配置文件',self.import_beauty_preset)
        self.preset_all=tk.BooleanVar(value=False)
        ttk.Checkbutton(section.body,text='配置应用到本图全部人像',variable=self.preset_all).pack(anchor='w',pady=3)
        help_section=Section(section.body,'使用说明',opened=False)
        for text in ('人像从画面左侧向右编号。基础磨皮、美白与纹理覆盖脸、耳朵、脖子及身体皮肤；祛痘检测针对面部。',
            '基础美颜遵循皮肤范围；升级皮肤引擎避开五官细节。唇周与眼眶皮肤可处理，祛痘保护正常五官。',
            '点击数值可直接输入；Enter 应用，Esc 取消。拖动滑块时更新数值，松开后应用。',
            '配置默认应用到当前人像，仅复用参数。新照片仍需识别；本图缓存可直接复用。'):
            ttk.Label(help_section.body,text=text,style='Muted.TLabel',wraplength=250).pack(anchor='w',pady=4)
        self.build_masks_panel(panel)
        self.build_color_panel(panel)
        section=Section(panel,'皮肤质感与肤色 · 当前人像',opened=False);self.texture_panel=section
        for name,title,lo,hi in EXTRA:
            if name!='redness':self.slider(section.body,title,getattr(self,name),lo,hi,self.refresh)
        row=ttk.Frame(section.body);row.pack(fill='x',pady=5)
        for label,gloss,clarity in [('无',0,0),('哑光',-35,0),('缎面',15,10),('水光',35,-10)]:
            b=ttk.Button(row,text=label,command=lambda g=gloss,c=clarity:self.skin_finish(g,c));b.pack(side='left',expand=True,fill='x',padx=1);self.controls.append(b)
        self.build_features_panel(panel)
        self.build_body_panel(panel)
        self.build_photo_body_panel(panel)
        self.build_reshape_panel(panel)
        self.build_liquify_panel(panel)
        self.build_volume_panel(panel)
        ttk.Label(section.body,text='新增参数默认0。根据 AI 皮肤区域做明暗、频率与颜色调整；保留原始细节。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=5)
        section=Section(panel,'分区域祛纹 · 当前人像',opened=False);self.wrinkle_panel=section
        ttk.Label(section.body,text='首次开启任一祛纹参数后，自动准备该人物的 AI 修补；完成后调整各区强度直接复用缓存。默认全部为0。眼周纹包含眼下细纹，保护眼球、睫毛边缘与主体头发。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(0,6))
        for name,title,lo,hi in ZONES:self.slider(section.body,title,getattr(self,name),lo,hi,self.refresh)
        lips=Section(section.body,'唇纹轻修',opened=False)
        self.slider(lips.body,'唇纹修整',self.lip_lines,0,100,self.refresh)
        ttk.Label(lips.body,text='唇纹轻修使用局部明暗平滑，强度默认0；不使用上述分区域AI祛纹模型。',style='Muted.TLabel',wraplength=270).pack(anchor='w',pady=4)
        self.build_retouch_panel(panel)
        section=Section(panel,'局部修复 · 选择工具后补选');self.repair_panel=section
        row=ttk.Frame(section.body);row.pack(fill='x')
        for title,value in [('浏览','pan'),('画笔','brush'),('圆框','circle'),('擦除','erase')]:
            b=ToolButton(row,title,value,lambda v=value:self.toggle_tool(v));b.pack(side='left',padx=2);self.controls.append(b);self.tool_buttons[value]=b
        row=ttk.Frame(section.body);row.pack(fill='x',pady=(3,0))
        for title,value in [('取消AI','exclude'),('恢复AI','restore')]:
            b=ToolButton(row,title,value,lambda v=value:self.toggle_tool(v));b.pack(side='left',padx=2);self.controls.append(b);self.tool_buttons[value]=b
        row=ttk.Frame(section.body);row.pack(fill='x',pady=(5,0))
        for title,value in [('迁移修复','heal'),('仿制','clone')]:
            b=ToolButton(row,title,value,lambda v=value:self.toggle_tool(v));b.pack(side='left',padx=2);self.controls.append(b);self.tool_buttons[value]=b
        self.diameter_label=tk.StringVar(value='16')
        self.radius_scale=self.slider(section.body,'大小 / 原图半径（像素）',self.radius,1,250,self.tool_size_changed)
        ttk.Label(section.body,text='大小只用于下一处新修复；已有迁移圆框保持原尺寸。',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=3)
        self.feather_scale=self.slider(section.body,'羽化',self.feather,0,100,self.feather_changed)
        self.patch_scale=self.slider(section.body,'迁移不透明度',self.patch_opacity,0,100,self.patch_controls_changed)
        self.patch_delete=self.button(section.body,'删除当前迁移修复',self.delete_patch)
        ttk.Label(section.body,textvariable=self.tool_hint,style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(8,4))
        self.repairbutton=self.button(section.body,'AI 修复当前选区',self.run_repair,accent=True)
        row=ttk.Frame(section.body);row.pack(fill='x',pady=(2,6))
        for title,fn in [('撤销 Ctrl+Z',self.undo),('重做 Ctrl+Y',self.redo)]:b=ttk.Button(row,text=title,command=fn);b.pack(side='left',expand=True,fill='x',padx=2);self.controls.append(b)
        ttk.Checkbutton(section.body,text='显示修复选区',variable=self.overlay,command=self.draw).pack(anchor='w',pady=4)
        ttk.Button(section.body,text='关闭工具 · 返回浏览',command=lambda:self.select_tool('pan')).pack(fill='x',pady=4)
        ttk.Label(section.body,text='取消AI / 恢复AI：涂抹修改局部，Shift＋点击处理整块自动选区；蓝色补选保留。\n右键临时擦除 · 补选后点 AI 修复\n羽化仅影响手动选区的修复边缘',style='Muted.TLabel',wraplength=275).pack(anchor='w',pady=(6,0))
        section=Section(panel,'识别与对比',opened=False);self.detection_panel=section
        self.slider(section.body,'检测阈值',self.threshold,.15,.65,lambda:None,decimals=2)
        self.button(section.body,'重新 AI 识别',self.scan);self.button(section.body,'恢复自动选区',self.reset)
        self.slider(section.body,'左原图 / 右结果',self.split,0,100,self.draw,mutating=False)
        def bind_scroll(widget):
            widget.bind('<MouseWheel>',lambda e:(scroll.yview_scroll(-int(e.delta/120),'units'),'break')[1])
            for child in widget.winfo_children():bind_scroll(child)
        bind_scroll(panel)
        center=ttk.Frame(workspace,padding=(4,0));center.pack(side='left',fill='both',expand=True)
        caption=ttk.Frame(center,padding=(8,8));caption.pack(fill='x')
        ttk.Label(caption,text='修改照片',font=('Microsoft YaHei UI',11,'bold')).pack(side='left')
        ttk.Label(caption,textvariable=self.device_summary,style='Muted.TLabel').pack(side='right')
        self.canvas=tk.Canvas(center,background=COLORS['viewport'],highlightthickness=0);self.canvas.pack(fill='both',expand=True);root._photo_canvas=self.canvas
        toolbar=ttk.Frame(center,padding=(8,7));toolbar.pack(fill='x')
        for title,fn in [('适合',self.fit),('面部',self.facefit),('100%',self.actual)]:ttk.Button(toolbar,text=title,width=6,command=fn).pack(side='left',padx=2)
        ttk.Label(toolbar,text='前后对比',style='Muted.TLabel').pack(side='left',padx=(18,7))
        ttk.Scale(toolbar,from_=0,to=100,variable=self.split,command=lambda v:self.draw(),length=180).pack(side='left')
        self.task_progress=ttk.Frame(toolbar)
        self.cancelbutton=ttk.Button(self.task_progress,text='取消处理',command=self.cancel.set,state='disabled');self.cancelbutton.pack(side='right')
        self.progressbar=ttk.Progressbar(self.task_progress,mode='indeterminate',length=80);self.progressbar.pack(side='right',padx=10)
        bottom=ttk.Frame(root,padding=(12,8));bottom.pack(side='bottom',fill='x',before=workspace)
        self.status_label=ttk.Label(bottom,textvariable=self.status,style='Muted.TLabel',wraplength=1400);self.status_label.pack(anchor='w')
        self.filmstrip=tk.Canvas(bottom,height=104,bg=COLORS['raised'],highlightthickness=0);self.filmstrip.pack(fill='x',pady=(8,0))
        self.filmstrip.bind('<MouseWheel>',lambda e:(self.filmstrip.xview_scroll(-int(e.delta/120),'units'),'break')[1])
        ttk.Scrollbar(bottom,orient='horizontal',command=self.filmstrip.xview).pack(fill='x');self.filmstrip.configure(xscrollincrement=104)
        self.filmstrip.create_text(16,48,anchor='w',text='最近打开的照片会显示在这里',fill=COLORS['muted'],font=('Microsoft YaHei UI',10))
        self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Motion>',self.hover);self.canvas.bind('<Leave>',self.pointer_leave)
        for num,kwargs in [(1,{}),(2,{'pan':True}),(3,{'erase':True})]:
            self.canvas.bind(f'<ButtonPress-{num}>',lambda e,k=kwargs:self.press(e,**k));self.canvas.bind(f'<B{num}-Motion>',self.motion);self.canvas.bind(f'<ButtonRelease-{num}>',self.release)
        root.bind('<KeyPress-space>',self.space_down);root.bind('<KeyRelease-space>',self.space_up);root.bind('<Escape>',self.close_popups);root.bind('<FocusOut>',self.focus_out,add='+')
        for key,action in [('<Control-z>',self.undo),('<Control-y>',self.redo),('<Control-Shift-Z>',self.redo),('<Control-s>',self.save_recipe),('<Control-o>',self.choose)]:
            root.bind(key,lambda e,fn=action:self.shortcut(e,fn))
        self.radius.trace_add('write',lambda *_:self.tool_size_changed());self.feather.trace_add('write',lambda *_:self.draw_tool_cursor())
        self.build_effect_panel(self.settings_panel)
        self.build_smart_mask_panel(self.settings_panel)
        self.build_creative_color_panel(self.color_workbench.panel)
        self.color_workbench.finish_build()
        self.build_creative_scene_panel(self.settings_panel)
        self.build_composition_panel(self.settings_panel)
        bind_scroll(self.settings_panel)
        self.build_settings_drawer();self.setup_categories();scale_widget_tree(root)
        for button in self.tool_buttons.values():button.paint()
        for button in self.category_buttons.values():button.paint()
        root.bind('<Configure>',self.queue_layout,add='+')
        self.layout_workspace();self.select_tool('pan');self.enable();root.after(80,self.poll)
        root.protocol('WM_DELETE_WINDOW',self.close_workspace)
        self.file_drop=FileDrop(root,self.receive_drop)
        from aura_automation import attach
        attach(self)
    def button(self,parent,title,fn,accent=False):
        b=ttk.Button(parent,text=title,command=fn,style='Accent.TButton' if accent else 'TButton');b.pack(fill='x',pady=4);self.controls.append(b);return b
    def register_mode_button(self,button,mode):
        if not hasattr(self,'mode_buttons'):self.mode_buttons=[]
        self.mode_buttons.append((button,mode,str(button.cget('text')),str(button.cget('style')) or 'TButton'))
        return button
    def mode_button(self,parent,title,mode):
        return self.register_mode_button(self.button(parent,title,lambda:self.toggle_tool(mode)),mode)
    def toggle_tool(self,mode):
        target='pan' if self.mode.get()==mode else mode
        result=self.select_tool(target)
        if target=='pan' and self.mode.get()=='pan':self.status.set('已退出工具，返回浏览；已有修改保留。')
        elif self.mode.get()==target:
            button=self.tool_buttons.get(target)
            title=button.label if button is not None else next((title for _,name,title,_ in getattr(self,'mode_buttons',[]) if name==target),'当前工具')
            self.status.set('已启用'+title+'；再次点击该按钮或按 Esc 返回浏览。')
        return result
    def change_device_preference(self,event=None):
        try:save_mode('cpu' if self.device_mode.get()=='仅 CPU' else 'auto')
        except OSError as e:self.status.set('计算模式保存失败：'+str(e));return
        self.status.set('已保存计算模式：'+self.device_mode.get()+'；下次启动生效，当前编辑继续保留。')
    def update_device_status(self):
        self.device_summary.set(RUNTIME.summary());report=RUNTIME.report()
        details='\n'.join(name+'：'+value for name,value in report['engines'].items())
        if report['gpu_name']:details=report['gpu_name']+'\n'+details
        if report['fallback_reasons']:details+='\n'+'\n'.join(report['fallback_reasons'].values())
        self.device_details.set(details or '读取照片时检查 GPU；GPU 不可用自动使用 CPU。')
    def slider(self,parent,title,var,lo,hi,command,decimals=0,mutating=True):
        apply=(lambda:self.parameter_apply(command)) if mutating else command
        control=ParameterScale(parent,title,var,lo,hi,apply,self.record,decimals,mutating,lambda:self.canvas.focus_set())
        if command in (self.color_changed,self.hsl_changed):control.preview_command=self.preview_global_color
        if mutating:self.controls.append(control)
        return control
    def preview_global_color(self):
        if getattr(self,'color_workbench',None) is not None and self.color_workbench.active:return self.color_workbench.preview_drag()
        return super().preview_global_color()
    def color_preview_display(self,bounds,size,localcut):
        if getattr(self,'color_workbench',None) is not None and self.color_workbench.active:return self.color_workbench.display_drag(bounds,size,localcut)
        return super().color_preview_display(bounds,size,localcut)
    def enable(self):
        super().enable()
        if hasattr(self,'device_summary'):self.update_device_status()
        if hasattr(self,'projectsave'):self.projectsave.configure(state='normal' if self.document and not self.busy else 'disabled')
        if hasattr(self,'raw_apply'):
            state='normal' if self.document and self.document.is_raw and not self.busy else 'disabled'
            self.raw_apply.configure(state=state);self.camera_control.configure(state=state)
            self.source_control.configure(state='readonly' if state=='normal' else 'disabled')
            self.profile_import.configure(state=state)
            embedded=self.camera_look.get() and self.camera_mode.get()=='机内预览 · 8位'
            self.profile_control.configure(state='readonly' if state=='normal' and not embedded else 'disabled')
            raw_state='normal' if state=='normal' and not embedded else 'disabled'
            self.raw_slider.configure(state=raw_state);self.wb_control.configure(state='readonly' if raw_state=='normal' else 'disabled')
        if hasattr(self,'progressbar'):
            if self.busy:
                self.task_progress.pack(side='right');self.progressbar.configure(mode='indeterminate');self.progressbar.start(14)
            else:
                self.progressbar.stop();self.task_progress.pack_forget()
        if hasattr(self,'radius_scale'):self.sync_tools()
        if hasattr(self,'person_control'):self.person_control.configure(state='readonly' if self.face_settings and not self.busy else 'disabled')
        if hasattr(self,'preset_export'):
            for control in (self.preset_export,self.preset_import):control.configure(state='normal' if self.face_settings and not self.busy else 'disabled')
        if hasattr(self,'beauty_draft_notes'):self.sync_beauty_draft_ui()
        if hasattr(self,'layer_control'):self.sync_layers()
        if hasattr(self,'reshape_cards'):self.sync_reshape_ui()
        self.sync_navigation_scope()
        for name in ('develop_process_control','point_selector','optics_combo','raw_process_control'):
            widget=getattr(self,name,None)
            if widget is not None:widget.configure(state='readonly' if self.document is not None and not self.busy else 'disabled')
        for widget in getattr(self,'_local_develop_combos',[]):widget.configure(state='readonly' if self.region_layers and not self.busy else 'disabled')
        if hasattr(self,'raw_process') and self.raw_process.get()=='专业线性显影':
            for widget in (self.camera_control,self.profile_control,self.profile_import):widget.configure(state='disabled')
        if hasattr(self,'creative_color_panel'):
            from feature_actions_ui import descendants
            for widget in descendants(self.creative_color_panel):
                if isinstance(widget,ttk.Combobox):widget.configure(state='readonly' if self.document is not None and not self.busy else 'disabled')
        self.sync_filter_ui()
        self.sync_fuji_ui()
    def poll(self):
        super().poll()
        self.consume_render()
        self.poll_color_filters()
        self.poll_feature_compare()
        self.poll_workflow()
        if self.batch and not self.busy and not getattr(self,'_raw_recovery_pending',False):
            if self.cancel.is_set():self.import_queue=[]
            if self.import_queue:self.root.after_idle(self.import_next)
            else:
                self.batch=False
                if self.batch_errors:messagebox.showwarning('部分照片未导入','\n'.join(self.batch_errors),parent=self.root)
        if self.drop_import_queue and not self.busy and not self.batch and not getattr(self,'_raw_recovery_pending',False):
            paths=self.drop_import_queue;self.drop_import_queue=[];self.import_photos(paths)
    def receive_drop(self,paths):
        accepted,ignored=photo_paths(paths,set(RAW_EXTENSIONS)|{'.jpg','.jpeg','.png','.tif','.tiff'})
        waiting={p.casefold() for p in self.drop_import_queue+self.import_queue}
        self.drop_import_queue.extend(p for p in accepted if p.casefold() not in waiting)
        if accepted:self.status.set(f'已接收 {len(accepted)} 张照片，等待导入'+(f'；忽略 {len(ignored)} 个文件或文件夹' if ignored else ''))
        else:self.status.set('请拖入 RAW、JPEG、PNG 或 TIFF 照片；暂不接受文件夹。')
    def work(self,fn,ready,cancellable=True):
        self._automation_cancellable=cancellable
        def tracked():
            try:return fn()
            except Exception as e:
                if getattr(ready,'recoverable_error',lambda:False)():raise
                if self.batch and not self.cancel.is_set():self.batch_errors.append(str(e));return ('batch-error',str(e))
                raise
        def completed(result):
            if isinstance(result,tuple) and len(result)==2 and isinstance(result[0],str) and result[0]=='batch-error':self.status.set('导入失败：'+result[1]);return
            ready(result)
        completed.on_error=getattr(ready,'on_error',None)
        return super().work(tracked,completed,cancellable)
    def choose(self):
        if self.busy:return
        paths=filedialog.askopenfilenames(title='导入照片（Ctrl / Shift 可多选）',filetypes=[('RAW 与照片','*.arw *.sr2 *.srf *.cr2 *.cr3 *.crw *.nef *.nrw *.raf *.jpg *.jpeg *.png *.tif *.tiff'),('所有文件','*.*')])
        if paths:self.import_photos(paths)
    def import_photos(self,paths):
        if self.busy or self.batch:return
        self.import_queue=list(dict.fromkeys(str(Path(p).resolve()) for p in paths));self.batch=True;self.batch_errors=[];self.import_next()
    def import_next(self):
        if self.busy or not self.batch or not self.import_queue:return
        path=self.import_queue.pop(0);self.open(path,as_shot_import=True)
    def import_profile(self):
        if not self.document or not self.document.is_raw or self.busy:return
        path=filedialog.askopenfilename(title='导入对应机型的 DCP',filetypes=[('DNG 相机配置文件','*.dcp')])
        if not path:return
        try:
            profile=camera_profiles.dcp_info(path);meta=camera_profiles.metadata(self.path)
            if camera_profiles.norm(profile['model'])!=camera_profiles.model_identity(meta):raise ValueError('此配置文件属于另一机型，不能套用。')
            if any(p['name']==profile['name'] for p in camera_profiles.matching(meta)):raise ValueError('已有同名配置。请在列表中选择，或使用不同名称的DCP。')
            destination=ROOT/'profiles'/(sha256_file(path)+'.dcp');destination.parent.mkdir(exist_ok=True)
            with destination.open('xb') as out:out.write(Path(path).read_bytes())
            camera_profiles.registry.cache_clear()
            self.profile_control.configure(values=['按拍摄风格匹配']+[p['name'] for p in camera_profiles.matching(meta)])
            self.camera_profile.set(profile['name']);self.camera_mode.set('机型配置文件 · RAW16');self.camera_look.set(True);self.enable()
            self.status.set('配置已导入，请点击「应用来源设置」。')
        except (ValueError,OSError) as e:messagebox.showerror('无法导入',str(e))
    def parameters(self):return normalized({name:float(getattr(self,name).get()) for name in NAMES})
    def skin_finish(self,gloss,clarity):
        if not self.session or self.busy:return
        self.gloss.set(gloss);self.clarity.set(clarity);self.refresh();self.record('皮肤质感选择')
    def sync_person_values(self):
        if not self.loading_face and 0<=self.active_face<len(self.face_settings):self.face_settings[self.active_face]=self.parameters()
    def person_session(self,fi):
        s=copy.copy(self.session);s.faces=[self.session.faces[fi]]
        pairs=[(spot,component) for spot,component in zip(self.session.spots,self.session.component_masks) if spot['face']==fi]
        s.spots=[dict(spot,face=0) for spot,_ in pairs];s.component_masks=[m for _,m in pairs]
        return s
    def initialize_people(self,records=None,shared=None,use_recommended=True):
        self.face_defaults=[normalized(recommend(self.person_session(i))[0]) for i in range(len(self.session.faces))]
        self.face_settings=[normalized(shared if shared is not None else values if use_recommended else neutral_values()) for values in self.face_defaults]
        if records:
            matched=set()
            for record in records:
                a,b,c,d=record['box'];scores=[]
                for f in self.session.faces:
                    e,j,k,l=f.box;area=max(0,min(c,k)-max(a,e))*max(0,min(d,l)-max(b,j));scores.append(area/max(1,(c-a)*(d-b)+(k-e)*(l-j)-area))
                index=int(np.argmax(scores)) if scores else -1
                if index<0 or scores[index]<.5 or index in matched:raise ValueError('项目的人脸位置与当前定位不同，已拒绝把设置应用到其他人。')
                matched.add(index);self.face_settings[index]=normalized(record['parameters'])
        self.active_face=0;self.person_control.configure(values=[f'人像 {i+1}' for i in range(len(self.face_settings))]);self.load_person_controls()
    def load_person_controls(self):
        self.loading_face=True
        try:
            if self.face_settings:
                self.active_face=max(0,min(self.active_face,len(self.face_settings)-1))
                self.person.set(f'人像 {self.active_face+1}')
                for name,value in self.face_settings[self.active_face].items():getattr(self,name).set(value)
            else:self.person.set('未检测到人像 · 可手动修复')
        finally:self.loading_face=False
        self.sync_reshape_ui()
        self.sync_color_ui()
        self.sync_smart_face_ui()
        self.sync_scene_ui()
    def switch_person(self,event=None):
        if self.busy or not self.face_settings:return
        selected=self.person_control.current()
        if not 0<=selected<len(self.face_settings):return
        self.flush_parameters()
        self.sync_person_values();self.commit_edit('人像参数微调');self.active_face=selected;self.load_person_controls();self.draw()
    def people_records(self):
        self.sync_person_values();return [{'box':list(f.box),'parameters':dict(v)} for f,v in zip(self.session.faces,self.face_settings)]
    def open(self,path,raw_settings=None,preserve=False,project=None,as_shot_import=False,edit_restore=None,_raw_recovery=False):
        self.end_feature_compare()
        if self.busy:return
        if self.document:self.keep_current()
        if self.busy:return
        if as_shot_import and Path(path).suffix.lower() in RAW_EXTENSIONS and raw_settings is None and project is None and not preserve:
            from photo_document import new_raw_settings
            self.recovery.backup_before_import(path)
            raw_settings=new_raw_settings(crop_mode='composition-v1')
        if raw_settings is None and project is None and not preserve and self.library.key(path) not in self.library.entries and self.try_recovery(path):return
        key=self.library.key(path)
        if raw_settings is None and project is None and not preserve and key in self.library.entries:
            if self.path==Path(path).resolve():return
            if key in self.library.hot:
                try:self.restore_photo(self.library.load(key))
                except (ValueError,OSError) as e:messagebox.showerror('无法切换照片',str(e),parent=self.root)
            else:self.status.set('正在恢复已处理照片与设置…');self.work(lambda:self.library.load(key),self.restore_photo)
            return
        if raw_settings is None and project is None and not preserve and Path(path).suffix.lower() in RAW_EXTENSIONS:
            from photo_document import new_raw_settings
            raw_settings=new_raw_settings(crop_mode='composition-v1')
        threshold=float(self.threshold.get()) if project is None else float(project[0]['threshold'])
        use_recommended=bool(self.auto_recommend.get())
        old=None
        if preserve and self.selection:old=(self.selection.mask&~self.selection.auto,self.selection.auto&~self.selection.mask,self.parameters(),self.document.metadata.get('camera_source','rgb'),self.people_records(),copy.deepcopy(self.patches),copy.deepcopy(self.region_layers),liquify.snapshot(self.liquify_state),self.liquify_settings(),copy.deepcopy(self.manual_records),self.manual_settings(),bool(self.manual_enabled.get()))
        old_extensions=self.extensions_snapshot() if preserve else {}
        retouch_engine=project[0].get('retouch_engine',1) if project else getattr(self.session,'retouch_engine',1) if preserve else 2
        protect_dark_points=project[0].get('protect_dark_points',False) if project else getattr(self.session,'protect_dark_points',False) if preserve else False
        edit_history=(list(self.edit_states),self.edit_index,list(self.history),self.project_path) if old else None
        rollback=self.capture_photo() if self.document is not None else None
        if rollback:
            for name in ('face_settings','face_defaults','history','patches','manual_records'):
                rollback[name]=copy.deepcopy(rollback[name])
            rollback['edit_states']=list(rollback['edit_states'])
        raw_failed=[False]
        self.status.set('读取原图，准备显影与 AI 检测…')
        def job():
            self.library.trim(keep=self.library.key(self.path) if self.path else None)
            t=time.perf_counter();warmup=preload_portrait_async() if Path(path).suffix.lower() in RAW_EXTENSIONS else None
            try:document=open_document(path,raw_settings,self.progress)
            except Exception:
                raw_failed[0]=Path(path).suffix.lower() in RAW_EXTENSIONS
                raise
            document.metadata['retouch_engine']=retouch_engine
            document.metadata['protect_dark_points']=protect_dark_points
            if warmup is not None:warmup.result()
            if _raw_recovery:
                from raw_recovery import validate_edit_source
                validate_edit_source(document,rollback['document'] if preserve and rollback else None,project,
                                     project[0].get('extensions',{}) if project else old_extensions)
            if project and not _raw_recovery:
                meta=project[0]
                if meta.get('camera_image_sha256')!=document.metadata.get('camera_image_sha256'):raise ValueError('项目的机内图像来源改变，无法可靠恢复。')
                if meta.get('camera_source') and meta['camera_source']!=document.metadata.get('camera_source','rgb'):raise ValueError('项目的机内/RAW 来源不匹配。')
                if meta.get('profile_sha256')!=document.metadata.get('profile_sha256'):raise ValueError('项目的DCP配置文件内容已改变。')
            if old and old[0].shape!=document.rgb.shape[:2] and (old[0].any() or old[1].any() or old[5] or old[6] or old[7] is not None or old[9]):raise ValueError('机内预览与 RAW 尺寸不同，无法保留局部修复与蒙版。请先保存项目，再重新打开照片切换来源。')
            if old and old[3]!=document.metadata.get('camera_source','rgb') and 'embedded_preview' in (old[3],document.metadata.get('camera_source','rgb')) and (old[0].any() or old[1].any() or old[5] or old[6] or old[7] is not None or old[9]):raise ValueError('机内图像可能包含镜头校正，局部修复与蒙版不能保证与 RAW 对齐。请先保存项目，再重新打开照片切换来源。')
            s=PortraitAISession(document.preview(),threshold,self.progress,retouch_engine=retouch_engine,protect_dark_points=protect_dark_points)
            if _raw_recovery and (old or project):
                from raw_recovery import validate_people
                validate_people(project[0].get('face_settings',[]) if project else old[4],s.faces)
            # Import once: establish body ownership before the default beauty
            # render. Switching photos or changing sliders uses cached masks.
            from person_masks import ensure_body_owners
            if s.faces:
                self.progress('AI 正在确认各人物的身体皮肤…');ensure_body_owners(s)
            selection=Selection(s.ai_auto_mask);small,_=small_blemishes(s);done=selection.mask.copy()
            if old and old[0].shape==selection.mask.shape:
                selection.mask=(selection.mask|old[0])&~old[1];done=selection.mask.copy()
            if project:
                meta,masks=project
                if list(selection.mask.shape)!=meta['shape']:raise ValueError('原图与项目尺寸不匹配。')
                selection.mask=masks['selected'];selection.auto=masks['automatic'];done=masks['processed'];small=masks['small'].astype(np.uint8)*255
            if project or old or use_recommended:
                generated,info=inpaint_portrait(s.original,(done>0)&~(small>0),self.progress,self.cancel,precision=True,retouch_engine=retouch_engine)
            else:
                generated=None;done=np.zeros(selection.mask.shape,bool)
                info=dict(tiles=0,repair_deferred=True,model='DAMO portrait repair')
            values=project[0]['parameters'] if project else old[2] if old else {}
            records=project[0].get('face_settings',[]) if project else old[4] if old else []
            detail_values=[normalized(records[i]['parameters'] if i<len(records) else values) for i in range(len(s.faces))]
            if any(v.get(k,0) for v in detail_values for k,_,_,_ in ADVANCED):
                layers=project[1]['region_layers'] if project else old[6] if old else []
                s.detail_cache=prepare_face_repairs(s,detail_values,layers,self.progress,self.cancel)
                if any(v.get(k,0) for v in detail_values for k,_,_,_ in BODY):prepare_body(s,detail_values,layers,self.progress,self.cancel)
            cache=None  # Retired face-shape module never prepares hidden effects.
            form_cache=prepare_forms(document.base_float(),s,detail_values,project[1]['region_layers'] if project else old[6] if old else [],self.progress,self.cancel)
            info['elapsed_seconds']=round(time.perf_counter()-t,2)
            info['gpu_warmup_parallel_with_raw']=warmup is not None
            return document,s,selection,done,small,generated,info,cache,form_cache
        def ready(result):
            self.document,self.session,self.selection,self.done_mask,self.small_mask,self.generated,self.meta,cache,self.form_cache=result
            self.protect_dark_points.set(self.session.protect_dark_points)
            # New geometry must never be drawn with the previous photo's people.
            self.face_settings=[];self.face_defaults=[];self.active_face=0
            self.output=None;self.output_float=None;self.nav_photo=None
            self.view=Viewport();self.history=[];self.historylist.delete(0,'end')
            self.slim_cache=cache or {};self.slim_ready=cache is not None
            self.reshape_cache={};self.reshape_changed=False
            self.photo_body_cache={};self.photo_body_changed=False
            self.liquify_input=None
            self.reset_retouch_state()
            self.manual_records=copy.deepcopy(project[0].get('manual_records',[]) if project else old[9] if old else [])
            self.load_manual_settings(project[0].get('manual_tools') if project else old[10] if old else None)
            self.manual_enabled.set(project[0].get('manual_enabled',True) if project else old[11] if old else True)
            self.liquify_state=project[1].get('liquify') if project else liquify.restore(old[7],self.document.rgb.shape[:2]) if old else None
            liquid=project[0].get('liquify_settings',{}) if project else old[8] if old else {}
            self.liquify_enabled.set(liquid.get('enabled',False));self.liquify_radius.set(liquid.get('radius',150));self.liquify_strength.set(liquid.get('strength',50))
            self.liquify_density.set(liquid.get('density',50));self.liquify_rate.set(liquid.get('rate',50))
            self.liquify_guide_face.set(liquid.get('guide_face',True));self.liquify_guide_body.set(liquid.get('guide_body',True));self.liquify_fix_nodes.set(liquid.get('fix_nodes',True))
            self.path=self.document.path;self.defaults,self.recommendation=recommend(self.session)
            self.load_extensions(project[0].get('extensions',{}) if project else old_extensions)
            if not project and not preserve and self.document.metadata.get('camera_crop_composition'):
                import composition
                self.workflow_extensions['composition']=composition.camera_frame(self.document.rgb.shape,self.document.metadata['camera_crop_box']);self.sync_composition_ui()
            if not project and not preserve and self.document.is_raw:
                from develop_optics import raw_defaults
                optics=raw_defaults(self.document)
                if optics:self.workflow_extensions['optics']=optics;self.sync_develop_optics()
            from fuji_profiles import base_ready
            state=self.workflow_extensions.get('color_filter',{})
            pending_source=getattr(self,'_pending_fuji_filter',None)
            planned_restore=bool(pending_source and pending_source.get('mode')=='standard' and pending_source['path']==self.path)
            if self.document.is_raw and state.get('preset',{}).get('raw_base') and state.get('amount',100)>0 and not base_ready(self.document) and not planned_restore:
                import color_presets
                self.workflow_extensions['color']=color_presets.restore_base(self.workflow_extensions.get('color',{}),state)
                self.workflow_extensions.pop('color_filter',None);self.sync_creative_color_ui()
            self.patches=copy.deepcopy(project[0].get('patches',[]) if project else old[5] if old else []);self.selected_patch=None
            self.region_layers=copy.deepcopy(project[1].get('region_layers',[]) if project else old[6] if old else [])
            self.active_layer=0 if self.region_layers else -1;self.mask_overlay.set(False);self.sync_layers()
            if project:
                tools=project[0].get('tool_settings',{'radius':8,'feather':0});self.radius.set(tools['radius']);self.feather.set(tools['feather'])
            elif not preserve:self.feather.set(0)
            values=project[0]['parameters'] if project else old[2] if old else self.defaults if use_recommended else neutral_values()
            for name,value in normalized(values).items():getattr(self,name).set(value)
            self.initialize_people(project[0].get('face_settings') if project else old[4] if old else None,values if project or old else None,use_recommended)
            self.select_tool('pan')
            self.threshold.set(threshold);self.raw_ev.set(self.document.raw_settings['exposure']);self.raw_wb.set({'camera':'机内白平衡','auto':'自动白平衡','daylight':'日光白平衡','custom':'自定义色温'}[self.document.raw_settings['white_balance']])
            self.raw_process.set('专业线性显影' if self.document.raw_settings['process']==2 else '兼容相机风格显影');self.raw_kelvin.set(self.document.raw_settings['kelvin']);self.raw_tint.set(self.document.raw_settings['tint'])
            self.camera_look.set(self.document.raw_settings['camera_look'])
            self.camera_mode.set('机内预览 · 8位' if self.document.raw_settings['camera_mode']=='embedded' else '机型配置文件 · RAW16')
            self.profile_control.configure(values=['按拍摄风格匹配']+self.document.metadata.get('profile_choices',[]))
            self.camera_profile.set('按拍摄风格匹配' if self.document.raw_settings['camera_profile']=='as_shot' else self.document.raw_settings['camera_profile'])
            self.filename.set(self.path.name);m=self.document.metadata;w,h=m['dimensions']
            details=f'{m.get("brand","")} {m["format"]} · {self.document.precision} bit\n{w:,} × {h:,} · sRGB'
            if m.get('iso'):details+=f'\nISO {m["iso"]:.0f} · f/{m["aperture"]:g}\n{m["focal_length"]:g} mm'
            if m.get('camera_model'):details+='\n'+m['camera_model']
            if m.get('camera_source')=='embedded_preview':
                details+='\n来源：RAW 内嵌机内图像\n8位源；16位导出不恢复 RAW 色阶'
                if m.get('color_profile')=='untagged_assumed_srgb':details+='\n无颜色配置：按 sRGB 显示'
                source_label=f'已保留机内渲染 · 8位\n{w:,} × {h:,}；美颜开关未确认'
            elif m.get('camera_source')=='dcp_raw':
                details+='\nRAW16 + '+m['profile_name']+'\n拍摄风格：'+m.get('camera_style','未知')
                source_label='已应用 '+m['profile_name']+'\n16位 RAW 显影；机型严格匹配'
            elif self.document.is_raw:source_label=m.get('camera_note','RAW 原始数据 → 16 位显影')
            else:source_label='RGB 照片：保留文件中已有色彩和修饰'
            if m.get('camera_import'):
                from camera_import import summary as camera_import_summary
                source_label+='\n'+camera_import_summary(m['camera_import'])
            if m.get('camera_crop_composition'):source_label+='\n机内裁切作为默认构图；完整 RAW 画幅可在构图模块恢复。'
            details+='\n皮肤引擎：'+('多尺度与细节保护' if self.session.retouch_engine==2 else '旧项目兼容模式')
            self.fileinfo.set(details);self.raw_label.configure(text=source_label)
            if edit_history:
                self.edit_states,self.edit_index,self.history,self.project_path=edit_history
                self.historylist.delete(0,'end')
                for entry in self.history:self.historylist.insert('end',entry)
            else:self.project_path=None;self.edit_states=[];self.edit_index=-1
            if edit_restore:
                index,verb,states=edit_restore;self.edit_states=states
                self.restore_edit(index,verb);self.fit();self.update_recent();return
            self.refresh();self.fit();self.update_recent()
            if not (old and getattr(self,'_pending_fuji_filter',None)):
                self.record('应用来源设置' if old else '打开项目' if project else '打开 '+m['format'])
        def commit(result):
            try:ready(result)
            except Exception:
                if rollback:
                    self.restore_photo(rollback)
                    self.keep_current()
                raise
        def recover(error):
            if not raw_failed[0]:return False
            from raw_recovery import offer
            from photo_document import validate_raw_settings
            failed_settings=validate_raw_settings(raw_settings)
            def resume(settings,changed):
                # A source change is a new edit, not completion of an undo whose
                # target still requests the failed engine/profile.
                self.open(path,settings,preserve=preserve,project=project,edit_restore=None if changed else edit_restore,
                          _raw_recovery=_raw_recovery or changed)
            return offer(self,path,failed_settings,error,resume)
        commit.on_error=recover
        commit.recoverable_error=lambda:raw_failed[0]
        self.work(job,commit)
    def redevelop(self):
        if not self.document or not self.document.is_raw or self.busy:return
        settings={'exposure':float(self.raw_ev.get()),'white_balance':{'机内白平衡':'camera','自动白平衡':'auto','日光白平衡':'daylight','自定义色温':'custom'}[self.raw_wb.get()],'camera_crop':self.document.raw_settings.get('camera_crop',True),'camera_look':bool(self.camera_look.get()),'camera_mode':'embedded' if self.camera_mode.get()=='机内预览 · 8位' else 'profile','camera_profile':'as_shot' if self.camera_profile.get()=='按拍摄风格匹配' else self.camera_profile.get(),'process':2 if self.raw_process.get()=='专业线性显影' else 1,'kelvin':self.raw_kelvin.get(),'tint':self.raw_tint.get()}
        settings['baseline_mode']=self.document.raw_settings.get('baseline_mode','legacy')
        settings['crop_mode']=self.document.raw_settings.get('crop_mode','source')
        settings['raw_engine']=self.document.raw_settings.get('raw_engine','rawtherapee')
        if settings['raw_engine']=='libraw-compat' and settings['camera_look']:settings['raw_engine']='rawtherapee'
        self.open(self.path,settings,preserve=True)
    def refresh(self):
        if not self.document or not self.session:return
        self.sync_person_values()
        if self.drag and self.drag.get('mode')=='beauty_paint':self.finish_beauty_paint()
        if self.photo_body_requested() and self.mode.get()!="pan" and not self.mode.get().startswith('beauty_'):self.select_tool("pan")
        if self.photo_body_requested() and not self.photo_body_cache.get("analysis"):
            self.prepare_photo_body();return
        self.end_feature_compare()
        self.invalidate_feature_cache()
        from relight_settings import active as light_active
        has_geometric_light=any(item.get('relight') is not None and light_active(item['relight']) for item in self.workflow_extensions.get('people',{}).values())
        if self._parameter_apply or has_geometric_light:
            self.queue_parameter_render();return
        self.invalidate_parameter_render()
        self.sync_person_values();self.update_device_status()
        self._render_pixels();self.finish_refresh()
    def _render_pixels(self):
        from gpu_render import render_automatic
        return render_automatic(self,App._render_pixels_cpu)
    def _render_pixels_cpu(self):
        from region_masks import load_beauty_includes
        load_beauty_includes(self.session,self.workflow_extensions)
        output=self.document.base_float()
        from mobile_cached_patches import apply as apply_mobile_cached
        output=apply_mobile_cached(output,self.workflow_extensions)
        accepted=self.selection.mask&(self.done_mask>0) if self.done_mask is not None else self.selection.mask
        effect_input=self.effect_before('repair',output)
        points=cv2.findNonZero(accepted.astype(np.uint8))
        if points is not None and self.generated is not None:
            a,b,w,h=cv2.boundingRect(points);mask=accepted[b:b+h,a:a+w].astype(np.uint8)
            alpha=self.selection.repair_alpha(mask,self.feather.get(),origin=(a,b))
            strengths=np.full(mask.shape,float(self.repair.get())/100,np.float32)
            for fi,(f,values) in enumerate(zip(self.session.faces,self.face_settings)):
                x,y,z,t=f.box;x0,y0,x1,y1=max(a,x),max(b,y),min(a+w,z),min(b+h,t)
                if x0<x1 and y0<y1:
                    face_region=(self.session.semantic_skin[fi][y0-y:y1-y,x0-x:x1-x]>0)&(f.protected[y0-y:y1-y,x0-x:x1-x]==0)
                    strengths[y0-b:y1-b,x0-a:x1-a][face_region]=values['repair']/100
            alpha*=strengths
            delta=self.generated[b:b+h,a:a+w].astype(np.float32)-self.session.original[b:b+h,a:a+w].astype(np.float32)
            output[b:b+h,a:a+w]+=delta*alpha[:,:,None]
        output=apply_face_repairs(output,self.document.base_float(),self.session,self.face_settings,self.region_layers,self.selection.auto&~self.selection.mask)
        output=self.effect_after('repair',effect_input,output);effect_input=self.effect_before('skin',output)
        skin_reference=output
        small=None if self.small_mask is None else (self.small_mask>0)&self.selection.mask
        self.output_float=render_skin(output,self.session,self.smooth.get(),self.whiten.get(),self.texture.get(),small,face_settings=self.face_settings or None)
        self.output_float=enhance_skin(self.output_float,self.session,self.face_settings)
        self.output_float=self.effect_after('skin',effect_input,self.output_float);effect_input=self.effect_before('wrinkles',self.output_float)
        self.output_float=wrinkle_and_circles(self.output_float,self.session,self.wrinkles.get(),self.dark_circles.get(),face_settings=self.face_settings or None)
        self.output_float=self.effect_after('wrinkles',effect_input,self.output_float);effect_input=self.effect_before('details',self.output_float)
        self.output_float=apply_face_details(self.output_float,self.document.base_float(),self.session,self.face_settings)
        self.output_float=self.effect_after('details',effect_input,self.output_float);effect_input=self.effect_before('face_color',self.output_float)
        self.output_float=apply_skin_color(self.output_float,self.session,self.face_settings,self.region_layers,mode='face')
        self.output_float=self.effect_after('face_color',effect_input,self.output_float);effect_input=self.effect_before('volume',self.output_float)
        self.output_float=apply_face_volume(self.output_float,self.session,self.face_settings)
        self.output_float=self.effect_after('volume',effect_input,self.output_float);effect_input=self.effect_before('body',self.output_float)
        self.output_float=apply_body(self.output_float,self.document.base_float(),self.session,self.face_settings,self.region_layers)
        self.output_float=apply_skin_color(self.output_float,self.session,self.face_settings,self.region_layers,mode='body')
        from skin_junction import blend_junction
        self.output_float=blend_junction(self.output_float,skin_reference,self.session,self.region_layers)
        self.output_float=chin_shadow(self.output_float,self.session,self.face_settings,self.region_layers)
        self.output_float=self.effect_after('body',effect_input,self.output_float);effect_input=self.effect_before('local',self.output_float)
        self.output_float=apply_layers(self.output_float,self.region_layers)
        self.output_float=self.effect_after('local',effect_input,self.output_float)
        self.output_float=protect_face_details(self.output_float,self.document.base_float(),self.session,self.face_settings)
        effect_input=self.effect_before('patches',self.output_float)
        self.output_float=apply_patches(self.output_float,self.patches)
        self.output_float=self.effect_after('patches',effect_input,self.output_float)
        self.manual_input=self.output_float
        effect_input=self.effect_before('manual',self.output_float)
        self.output_float=manual_retouch.apply(self.manual_input,self.manual_records,self.manual_enabled.get())
        self.output_float=self.effect_after('manual',effect_input,self.output_float)
        self.output_float=self.creative_render(self.output_float)
        self.slim_changed=None
        self.output_float,self.form_changed=apply_forms(self.output_float,self.session,self.face_settings,self.region_layers,self.form_cache)
        self.output_float,self.reshape_changed=face_reshape.apply(self.output_float,self.face_settings,self.reshape_cache)
        self.output_float,self.photo_body_changed,self.photo_body_message,self.photo_body_cache=photo_body.apply(self.output_float,self.session,self.face_settings,self.photo_body_values(),self.photo_body_cache)
        self.liquify_input=self.output_float
        if self.liquify_enabled.get():self.output_float=liquify.apply(self.liquify_input,self.liquify_state)
        from develop_output import preview
        from develop_optics import apply as optical_correction
        self.output_float=optical_correction(self.output_float,self.workflow_extensions.get('optics',{}))
        self.output=preview(self.output_float,self.workflow_extensions.get('output',{}))
    def _render_color_pixels(self):
        from gpu_render import render_automatic
        return render_automatic(self,App._render_color_pixels_cpu)
    def _render_color_pixels_cpu(self):
        before=self.effect_before('creative',self.creative_input)
        self.output_float=self.apply_creative_color(self.color_input)
        self.output_float=self.effect_after('creative',before,self.output_float);self.creative_output=self.output_float
        self.output_float,self.form_changed=apply_forms(self.output_float,self.session,self.face_settings,self.region_layers,self.form_cache)
        self.output_float,self.reshape_changed=face_reshape.apply(self.output_float,self.face_settings,self.reshape_cache)
        self.output_float,self.photo_body_changed,self.photo_body_message,self.photo_body_cache=photo_body.apply(self.output_float,self.session,self.face_settings,self.photo_body_values(),self.photo_body_cache)
        self.liquify_input=self.output_float
        if self.liquify_enabled.get():self.output_float=liquify.apply(self.liquify_input,self.liquify_state)
        from develop_output import preview
        from develop_optics import apply as optical_correction
        self.output_float=optical_correction(self.output_float,self.workflow_extensions.get('optics',{}))
        self.output=preview(self.output_float,self.workflow_extensions.get('output',{}))
    def finish_refresh(self):
        self.photo_body_note.set(getattr(self,"photo_body_message","身体美型未启用。"))
        self.schedule_feature_compare()
        pending=self.repair_pending();self.summary.set(f'{len(self.session.faces)} 张脸 · {len(self.session.spots)} 处 AI 候选\n'+('有新选区等待 AI 修复' if pending else '已生成美颜版本，可微调'))
        if not self.session.faces:self.summary.set('未定位到可靠人脸，未自动美颜。\n可手动补选修复；遮挡、模糊或极小脸仍可能漏检。')
        elif all(v==neutral_values() for v in self.face_settings):self.summary.set(f'{len(self.session.faces)} 张脸 · 已完成识别，尚未应用美颜\n点击“使用推荐参数”或应用配置文件。')
        if self.creative_is_active():self.summary.set(f'{len(self.session.faces)} 张脸 · 已应用调色 / 创作参数\n可在效果管理中检查强度与范围。')
        source='机内图像 · 8位（TIFF 不恢复 RAW 色阶）' if self.document.metadata.get('camera_source')=='embedded_preview' else f'{self.document.precision} 位源图'
        self.status.set(f'{self.path.name}  /  {source}  /  祛痘 {self.repair.get():.0f} · 磨皮 {self.smooth.get():.0f} · 美白 {self.whiten.get():.0f} · 纹理 {self.texture.get():.0f}'+('  /  补选后请执行 AI 修复' if pending else ''))
        if self.shape_pending():self.status.set(self.status.get()+' / 面部重塑待校准与生成')
        if forms_pending(self.session,self.face_settings,self.region_layers,self.form_cache):self.status.set(self.status.get()+' / 局部形变待处理或部位不可见：请检查实验组。')
        if face_repairs_pending(self.session,self.face_settings,self.region_layers):self.status.set(self.status.get()+' / 有细节候选待处理：请点 AI 应用面部细节修复。')
        if body_pending(self.session,self.face_settings,self.region_layers):self.status.set(self.status.get()+' / 身体祛瑕待处理：请点 AI 应用身体祛瑕 / 修复。')
        notices=body_notices(self.session,self.face_settings,self.region_layers)
        notices+=face_reshape.notices(self.reshape_cache,self.face_settings)
        if self.photo_body_requested():notices.append(self.photo_body_note.get())
        if notices:self.status.set(self.status.get()+' / '+'；'.join(notices))
        self.sync_color_ui()
        self.sync_reshape_ui()
        if np.any(self.selection.auto&~self.selection.mask):self.status.set(self.status.get()+'  /  已保留手动取消的 AI 选区')
        if self.patches:self.status.set(self.status.get()+f'  /  {len(self.patches)} 处迁移修复')
        self.make_navigation();self.draw_histogram();self.draw()
        self.mark_draft()
        if not self.busy and eye_wrinkle_pending(self.session,self.face_settings):
            # Prepare fixed protections in the worker. The DAMO blend map is
            # keyed to current pre-wrinkle RGB; strength-only edits reuse it.
            session=self.session;values=copy.deepcopy(self.face_settings)
            self.commit_edit('面部祛纹参数')
            def ready(cache):
                session.eye_wrinkle_cache=cache
                if self.session is session:self.refresh();self.update_recent()
            self.work(lambda:prepare_eye_wrinkles(session,values,self.progress,self.cancel),ready)
        elif not self.busy and self.shape_pending():self.prepare_reshape_controls()
    def prepare_shape(self):
        self.prepare_reshape_controls()
    def shape_pending(self):
        return not face_reshape.ready(self.reshape_cache,self.face_settings)
    def run_repair(self):
        if not self.session or self.busy:return
        mask=self.selection.mask.copy()
        def ready(result):self.generated,self.meta=result;self.done_mask=mask;self.small_mask=np.zeros(mask.shape,np.uint8);self.refresh();self.record('AI 修复当前选区')
        self.work(lambda:inpaint_portrait(self.session.original,mask,self.progress,self.cancel,precision=True,retouch_engine=getattr(self.session,'retouch_engine',1)),ready)
    def repair_pending(self):
        # Deferred AI candidates do not block a manual-only export when that
        # person's repair strength is zero. Explicit manual AI selections do.
        pending=self.selection.mask.copy()
        if self.done_mask is not None:pending &= ~(self.done_mask>0)
        if np.any(pending & ~self.selection.auto):return True
        if not self.face_settings:return bool(np.any(pending)) and self.repair.get()>0
        for face,values in zip(self.session.faces,self.face_settings):
            if values.get('repair',0)>0:
                a,b,c,d=face.box
                if np.any(pending[b:d,a:c]):return True
        return False
    def scan(self):
        if not self.session or self.busy:return
        threshold=float(self.threshold.get());s=self.session
        def job():s.scan_ai(threshold,self.progress);return s.ai_auto_mask.copy()
        def ready(mask):self.selection.rescan(mask);self.small_mask,_=small_blemishes(s);self.defaults,self.recommendation=recommend(s);self.refresh();self.record('重新 AI 识别')
        self.work(job,ready)
    def toggle_dark_point_protection(self):
        if not self.session or self.busy or self.session.retouch_engine!=2:
            self.protect_dark_points.set(getattr(self.session,'protect_dark_points',False))
            if self.session and self.session.retouch_engine==1:self.status.set('当前为旧项目兼容模式；新导入照片支持可选深色点保护。')
            return
        enabled=bool(self.protect_dark_points.get());s=self.session;previous=s.protect_dark_points;threshold=float(self.threshold.get())
        self.flush_parameters();self.commit_edit('深色点保护调整前')
        def job():
            s.protect_dark_points=enabled
            try:s.scan_ai(threshold,self.progress)
            except Exception:
                s.protect_dark_points=previous;s.scan_ai(s.confidence);raise
            return s.ai_auto_mask.copy()
        def ready(mask):
            self.document.metadata['protect_dark_points']=enabled
            self.selection.rescan(mask);self.small_mask,_=small_blemishes(s)
            self.refresh();self.record('开启深色点保护' if enabled else '关闭深色点保护')
        self.work(job,ready)
    def select_tool(self,mode):
        if mode!='pan' and not mode.startswith('beauty_') and self.photo_body_requested():
            self.status.set('绘制、取样或液化前，请先重置照片身体美型，保持编辑坐标一致。');return 'break'
        self.end_feature_compare()
        if mode in ('mask_add','mask_subtract') and not 0<=self.active_layer<len(self.region_layers):return 'break'
        # Commit an active edit before switching so one stroke remains one undo step.
        if self.drag and self.drag['mode']!='pan':self.finish_stroke()
        self.drag=None;self.mode.set(mode)
        self.crop_straighten=False
        if mode=='liquify_face':
            self.liquify_guide_face.set(True)
            if not self.smart_face_panel.opened:self.smart_face_panel.toggle()
            self.root.after_idle(lambda:self.focus_section(self.smart_face_panel) if self.mode.get()=='liquify_face' else None)
        if mode in ('mask_add','mask_subtract','smart_add','smart_subtract'):self.mask_overlay.set(True);self.overlay.set(False)
        elif mode=='sample' or mode.startswith(('liquify_','retouch_','effect_','creative_','beauty_','develop_')):self.overlay.set(False);self.mask_overlay.set(False)
        elif mode!='pan':self.overlay.set(True);self.mask_overlay.set(False)
        if mode.startswith('liquify_'):self.reshape_overlay.set(False)
        if not mode.startswith('retouch_'):self.manual_pick_source=False
        self.sync_tools();self.draw();return 'break'
    def sync_tools(self):
        active=self.mode.get()!='pan'
        for name,button in self.tool_buttons.items():button.set_active(name==self.mode.get())
        for button,mode,title,style in getattr(self,'mode_buttons',[]):
            if button.winfo_exists():
                on=self.crop_straighten if mode=='crop_straighten' else self.mode.get()==mode
                button.configure(text=title+' · 开' if on else title,style='Accent.TButton' if on else style)
        state='normal' if active and self.mode.get()!='sample' and not self.mode.get().startswith(('liquify_','retouch_')) and not self.busy else 'disabled'
        self.radius_scale.configure(state=state);self.feather_scale.configure(state=state)
        patch_mode=self.mode.get() in ('heal','clone')
        self.patch_scale.configure(state='normal' if patch_mode and not self.busy else 'disabled')
        self.patch_delete.configure(state='normal' if patch_mode and self.selected_patch is not None and not self.busy else 'disabled')
        hint={'pan':'浏览：拖动平移 · Ctrl＋滚轮缩放','circle':'圆框：按住左键拖动，固定大小沿路径连续补选；右键拖动擦除。','mask_add':'添加当前部位蒙版；右键临时减去','mask_subtract':'减去当前部位蒙版','exclude':'取消AI：涂抹取消局部，Shift＋点击取消整块','restore':'恢复AI：涂抹恢复局部，Shift＋点击恢复整块','heal':'点击新增修复；拖动＋取样圆调整复制来源，拖动修复圆调整目标。松开应用，右键删除。','clone':'点击新增仿制；拖动＋取样圆调整复制来源，拖动修复圆调整目标。松开应用，右键删除。'}.get(self.mode.get(),'补选：Ctrl＋滚轮调大小')
        if self.mode.get()=='sample':hint='吸管：点击原显影图取样，强度不自动增加'
        if self.mode.get().startswith('liquify_'):hint='液化：向前变形拖动推拉；重建、径向与平滑画笔可按住累积。右键临时重建。'
        if self.mode.get()=='liquify_push_left':hint='左推：上拖向左，下拖向右；Alt 反向。'
        if self.mode.get() in ('liquify_nodes','liquify_face'):hint='拖动结果侧辅助线节点直接微调；智能参数在右侧。'
        if self.mode.get().startswith('retouch_'):hint='手动修饰：按住涂画，Alt＋点击取样；右键恢复手动效果。'
        if self.mode.get().startswith('beauty_'):
            action='补选漏识别皮肤' if self.mode.get().endswith('_add') else '局部恢复原AI范围' if self.mode.get().endswith('_restore') else '擦除AI和手动美颜范围'
            hint='美颜范围：'+action+'；右键临时擦除。松开后应用当前参数。'
        suffix='\n再次点击工具退出 · 空格平移 · Esc 退出'
        suffix+='\nCtrl＋滚轮缩放' if self.mode.get()=='sample' else '\nCtrl＋滚轮调大小'
        self.tool_hint.set(hint if not active else hint+suffix)
        self.sync_manual_ui()
        self.sync_liquify_ui()
        if hasattr(self,'canvas'):self.canvas.configure(cursor='fleur' if self.space or not active else 'arrow' if self.busy else 'none');self.draw_tool_cursor()
    def brushradius(self):
        try:return max(1,min(250,round(float(self.radius.get()))))
        except (ValueError,tk.TclError):return 8
    def tool_size_changed(self):
        self.diameter_label.set(str(self.brushradius()*2));self.draw_tool_cursor()
    def feather_changed(self):
        self.draw_tool_cursor()
        self.patch_controls_changed()
        if self.document and not self.busy:self.refresh()
    def patch_controls_changed(self):
        if self.loading_patch or not self.document or self.busy or self.mode.get() not in ('heal','clone'):return
        if self.selected_patch is not None and self.selected_patch<len(self.patches):
            p=self.patches[self.selected_patch];p.update(feather=float(self.feather.get()),opacity=float(self.patch_opacity.get()))
            self.refresh()
    def load_patch_controls(self,index):
        self.selected_patch=index;self.loading_patch=True
        try:
            p=self.patches[index];self.feather.set(p['feather']);self.patch_opacity.set(p['opacity'])
        finally:self.loading_patch=False
        self.sync_tools()
    def delete_patch(self):
        if self.busy or self.selected_patch is None:return
        del self.patches[self.selected_patch];self.selected_patch=None;self.refresh();self.record('删除迁移修复');self.sync_tools()
    def patch_hit(self,point):
        # Keep tiny handles easy to grab at fit zoom; resolve overlapping disks
        # by the nearest center instead of the most recently created patch.
        hits=[]
        for i in reversed(range(len(self.patches))):
            p=self.patches[i]
            for role in ('source','target'):
                distance=np.linalg.norm(np.array(point)-p[role])*self.view.scale
                if distance<=max(p['radius']*self.view.scale,12):hits.append((distance,i,role))
        return min(hits,key=lambda hit:hit[0])[1:] if hits else None
    def mask_for_display(self,mask,bounds,localcut=0):
        from develop_optics import geometry_active
        if not geometry_active(self.workflow_extensions.get('optics',{})):return super().mask_for_display(mask,bounds,localcut)
        a,b,c,d=bounds;result=np.zeros((d-b,c-a),bool)
        for top in range(b,d,128):
            end=min(d,top+128);yy,xx=np.mgrid[top:end,a:c].astype(np.float32);p=np.stack([xx,yy],2);q=self.original_points(p.reshape(-1,2)).reshape(end-top,c-a,2)
            result[top-b:end-b]=cv2.remap(mask.astype(np.uint8),q[:,:,0],q[:,:,1],cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)>0
        if localcut:result[:,:localcut]=False
        return result
    def hover(self,event):
        self.pointer=(event.x,event.y)
        if self.mode.get() in ('liquify_nodes','liquify_face'):self.draw_liquify_guides()
        self.draw_tool_cursor()
    def pointer_leave(self,event):
        self.pointer=None;self.canvas.delete('tool_cursor')
        if self.mode.get() in ('liquify_nodes','liquify_face'):self.draw_liquify_guides()
        if self.mode.get() in ('heal','clone') and not self.space:self.canvas.configure(cursor='none')
    def draw_tool_cursor(self):
        if not hasattr(self,'canvas'):return
        self.canvas.delete('tool_cursor')
        if self.pointer is None or not self.session or self.mode.get()=='pan' or self.space or self.busy:return
        if self.drag and self.drag['mode']=='pan':return
        x,y=self.pointer;px,py=self.view.to_image(x,y,self.size());h,w=self.session.original.shape[:2]
        if not (0<=px<w and 0<=py<h):return
        if self.mode.get()=='sample':
            self.canvas.create_line(x-8,y,x+8,y,fill='#f1f5fa',tags='tool_cursor');self.canvas.create_line(x,y-8,x,y+8,fill='#f1f5fa',tags='tool_cursor');return
        if self.mode.get().startswith('retouch_'):self.draw_manual_cursor(x,y,px,py);return
        if self.mode.get().startswith('beauty_'):
            r=self.brushradius()*self.view.scale;self.canvas.create_oval(x-r,y-r,x+r,y+r,outline='#2dcdb9',width=2,tags='tool_cursor');return
        if self.mode.get().startswith('effect_'):
            r=self.effect_radius.get()*self.view.scale
            self.canvas.create_oval(x-r,y-r,x+r,y+r,outline='#3289df',width=2,tags='tool_cursor');return
        if self.mode.get().startswith('smart_'):
            r=self.smart_radius.get()*self.view.scale
            self.canvas.create_rectangle(x-r,y-r,x+r,y+r,outline='#3289df',dash=(3,3),tags='tool_cursor')
            self.canvas.create_line(x-5,y,x+5,y,fill='#3289df',tags='tool_cursor');self.canvas.create_line(x,y-5,x,y+5,fill='#3289df',tags='tool_cursor');return
        if self.mode.get()=='creative_clean':
            r=self.clean_radius.get()*self.view.scale;self.canvas.create_oval(x-r,y-r,x+r,y+r,outline='#d45d4b',width=2,tags='tool_cursor');return
        if self.mode.get() in ('heal','clone'):
            handle=self.patch_hit((px,py))
            if self.drag and self.drag['mode']=='patch_move':self.canvas.configure(cursor='fleur');return
            self.canvas.configure(cursor='hand2' if handle else 'none')
            if handle:return
        if self.mode.get().startswith('liquify_'):
            active=self.drag if self.drag and self.drag['mode'].startswith('liquify_') else None
            if self.mode.get() in ('liquify_nodes','liquify_face') and (active is None or active['mode']=='liquify_node'):
                hit=self.liquify_node_hit((px,py));self.canvas.configure(cursor='fleur' if active else 'hand2' if hit else 'arrow')
                if active:
                    nx,ny=self.view.to_canvas(*active['actual'],self.size());r=active['r']*self.view.scale
                    self.canvas.create_oval(nx-r,ny-r,nx+r,ny+r,outline='#f0c678',dash=(3,3),tags='tool_cursor')
                if hit:self.canvas.create_text(x+dp(self.root,10),y+dp(self.root,10),text=hit['name'],anchor='nw',fill='#ffffff',font=ui_font(self.root,10),tags='tool_cursor')
                return
            r=(active['r'] if active else float(self.liquify_radius.get()))*self.view.scale
            for color,width in [('#202b3c',3),('#58bef8' if self.mode.get()=='liquify_freeze' else '#ffffff',1)]:
                self.canvas.create_oval(x-r,y-r,x+r,y+r,outline=color,width=width,tags='tool_cursor')
            density=active['density'] if active else float(self.liquify_density.get())
            inner=r*density*.009
            if inner>2:self.canvas.create_oval(x-inner,y-inner,x+inner,y+inner,outline='#ffffff',dash=(3,3),tags='tool_cursor')
            return
        radius=self.drag['r'] if self.drag and 'r' in self.drag else self.brushradius()
        r=radius*self.view.scale;color='#f69aa5' if self.mode.get()=='exclude' else '#a1e4bf' if self.mode.get()=='restore' else '#ffcf96' if self.mode.get()=='erase' or self.drag and self.drag['mode']=='erase' else '#dce9f9'
        for delta,outline,width in [(1,'#171b20',3),(0,color,1)]:
            self.canvas.create_oval(x-r-delta,y-r-delta,x+r+delta,y+r+delta,outline=outline,width=width,tags='tool_cursor')
        if self.feather.get()>0:
            inner=r*(1-self.feather.get()/100);self.canvas.create_oval(x-inner,y-inner,x+inner,y+inner,outline=color,dash=(3,3),tags='tool_cursor')
        self.canvas.create_line(x-3,y,x+3,y,fill=color,tags='tool_cursor');self.canvas.create_line(x,y-3,x,y+3,fill=color,tags='tool_cursor')
    def space_down(self,event):
        if not isinstance(self.root.focus_get(),(tk.Entry,ttk.Entry,ttk.Spinbox)):
            if self.drag and self.drag['mode']!='pan':self.finish_stroke()
            self.space=True;self.sync_tools();return 'break'
    def space_up(self,event):self.space=False;self.sync_tools();return 'break'
    def focus_out(self,event):
        # Losing the app focus must never leave temporary pan latched on.
        def check():
            if self.root.focus_get() is None:
                if self.drag and self.drag['mode']!='pan':self.finish_stroke()
                self.drag=None;self.space=False;self.sync_tools()
        self.root.after_idle(check)
    def wheel(self,event):
        if not self.session:return 'break'
        self.pointer=(event.x,event.y)
        if not event.state&0x0004:return 'break'
        if self.drag:return 'break'
        if self.mode.get().startswith('retouch_') and not self.space:
            if not self.busy:self.manual_radius.set(max(1,min(1000,round(self.manual_radius.get()*1.15**(event.delta/120)))))
        elif self.mode.get().startswith('liquify_') and not self.space:
            if not self.busy:self.liquify_radius.set(max(5,min(1000,round(self.liquify_radius.get()*1.15**(event.delta/120)))))
        elif self.mode.get().startswith('smart_') and not self.space:
            if not self.busy:self.smart_radius.set(max(20,min(4000,round(self.smart_radius.get()*1.15**(event.delta/120)))))
        elif self.mode.get().startswith('effect_') and not self.space:
            if not self.busy:self.effect_radius.set(max(1,min(500,round(self.effect_radius.get()*1.15**(event.delta/120)))))
        elif self.mode.get()=='creative_clean' and not self.space:
            if not self.busy:self.clean_radius.set(max(1,min(300,round(self.clean_radius.get()*1.15**(event.delta/120)))))
        elif self.mode.get() not in ('pan','sample') and not self.space:
            if not self.busy:
                old=self.brushradius();new=round(old*1.15**(event.delta/120))
                if new==old and event.delta:new=old+(1 if event.delta>0 else -1)
                self.radius.set(max(1,min(250,new)))
                if self.mode.get() in ('heal','clone'):self.status.set('圆框大小只用于下一处新修复；已建立的修复区域保持不变。')
        else:self.view.zoom(1.2**(event.delta/120),event.x,event.y,self.size());self.draw()
        self.draw_tool_cursor();return 'break'
    def press(self,event,pan=False,erase=False,sampling=False):
        self.end_feature_compare()
        if getattr(self,'active_category',None)=='构图' and not pan and not self.space:
            self.start_crop_drag(event);return
        self.close_popups()
        if not self.session:return
        self.canvas.focus_set();self.pointer=(event.x,event.y)
        if pan or self.space or self.mode.get()=='pan':
            self.drag={'mode':'pan','screen':(event.x,event.y)};self.canvas.delete('tool_cursor');return
        if self.busy:return
        if self.photo_body_changed and not self.mode.get().startswith('beauty_'):
            self.status.set("绘制、取样或液化前，请先将照片身体美型四项归零，保持编辑坐标一致。");return
        if self.mode.get().startswith('beauty_'):
            if self._render_pending and (self.reshape_changed or self.liquify_active() or self.photo_body_changed or self.photo_body_requested()):
                self.status.set('请等待形变画面更新完成后绘制范围。');return
            self.start_beauty_paint(event,erase);return
        self.wait_parameter_render()
        if self.busy:return
        if self.mode.get()=='creative_clean':self.start_clean_paint(event,erase);return
        if self.mode.get()=='creative_light':self.place_light(event);return
        if self.mode.get() in ('develop_wb','develop_point','develop_hsl'):self.develop_pick(event);return
        if self.mode.get() in ('develop_linear','develop_radial'):self.begin_develop_gradient(event);return
        if self.mode.get()=='develop_range':self.sample_local_range(event);return
        if self.mode.get().startswith('smart_'):self.click_smart_mask(event,erase);return
        if self.mode.get().startswith('effect_'):self.start_effect_paint(event,erase);return
        if self.mode.get().startswith('liquify_'):self.start_liquify(event,erase);return
        if self.mode.get().startswith('retouch_'):
            if self.shape_pending() or self.form_changed is not None and self.form_changed.any():
                self.status.set('请等待脸型校准；实验身体形变需先暂时关闭。');return
            self.start_manual(event,erase,sampling);return
        if self.liquify_active():self.status.set('编辑原图选区或取样前，请在“手动液化”中暂时关闭液化。');return
        if self.reshape_changed or self.form_changed is not None and self.form_changed.any():
            self.status.set('补选或取样前请在面部重塑选择“无”，并将双下巴及腋下形变暂调为0，保持原图坐标一致。');return
        if self.mode.get()=='sample':self.take_skin_sample(event);return
        p=self.point(event);h,w=self.selection.mask.shape
        if not (0<=p[0]<w and 0<=p[1]<h):return
        if self.mode.get() in ('mask_add','mask_subtract'):
            self.commit_edit('部位蒙版编辑前');mode='mask_subtract' if erase else self.mode.get()
            self.drag={'mode':mode,'start':p,'last':p,'r':self.brushradius()};self.paint_stroke(p,p,self.drag['r'],mode);self.draw();return
        if self.mode.get() in ('heal','clone'):
            p=(int(np.clip(round(p[0]),0,w-1)),int(np.clip(round(p[1]),0,h-1)))
            hit=self.patch_hit(p)
            if hit:
                self.commit_edit('移动取样前')
                index,role=hit;self.load_patch_controls(index)
                if erase:self.delete_patch();return
                self.drag={'mode':'patch_move','index':index,'role':role,'last':p,
                    'start':p,'original':list(self.patches[index][role])}
                self.draw();return
            if erase:return
            if len(self.patches)>=500:self.status.set('单图最多500处迁移修复。');return
            allowed=np.zeros((h,w),bool)
            for f in self.session.faces:
                a,b,c,d=f.box;allowed[b:d,a:c]|=f.mask>.8
            try:source=choose_source(self.output_float,p,self.brushradius(),allowed if allowed[p[1],p[0]] else None)
            except ValueError as e:self.status.set(str(e));return
            self.patches.append({'target':list(p),'source':source,'radius':self.brushradius(),'feather':float(self.feather.get()),'opacity':float(self.patch_opacity.get()),'mode':self.mode.get()})
            self.selected_patch=len(self.patches)-1;self.refresh();self.record('新增迁移修复' if self.mode.get()=='heal' else '新增仿制');self.sync_tools();return
        mode='erase' if erase else self.mode.get()
        if mode in ('exclude','restore') and event.state&0x0001:
            px,py=map(lambda v:int(round(v)),p)
            if not (0<=px<w and 0<=py<h) or not self.selection.auto[py,px]:return
            self.selection.checkpoint();self.selection.set_auto_region(p,mode=='restore');self.refresh()
            self.record('取消整块 AI 选区' if mode=='exclude' else '恢复整块 AI 选区');return
        self.selection.checkpoint()
        self.drag={'mode':mode,'start':p,'last':p,'r':self.brushradius()}
        self.paint_stroke(p,p,self.drag['r'],mode)
        self.draw()
    def paint_stroke(self,p0,p1,r,mode):
        if mode in ('mask_add','mask_subtract'):self.paint_layer(p0,p1,r,mode);return
        self.selection.stroke(p0,p1,r,erase=mode in ('erase','exclude'),auto_only=mode in ('exclude','restore'))
    def motion(self,event):
        if self.drag and self.drag.get('mode')=='develop_gradient':self.update_develop_gradient(event);return
        if self.drag and self.drag['mode']=='crop_edit':self.update_crop_drag(event);return
        self.pointer=(event.x,event.y)
        if not self.drag:self.draw_tool_cursor();return
        d=self.drag;p=self.point(event)
        if d['mode']=='beauty_paint':self.update_beauty_paint(p);return
        if d['mode']=='clean_select':self.update_clean_paint(p);return
        if d['mode']=='effect_paint':self.update_effect_paint(p);return
        if d['mode'].startswith('liquify_'):self.update_liquify(p);return
        if d['mode'].startswith('retouch_'):self.update_manual(p);return
        if d['mode']=='patch_move':
            h,w=self.selection.mask.shape
            moved=np.array(d['original'])+np.array(p)-np.array(d['start'])
            self.patches[d['index']][d['role']]=[int(np.clip(round(moved[0]),0,w-1)),int(np.clip(round(moved[1]),0,h-1))]
            d['last']=p
            # Dragging only updates handles. Re-render once on release, so RAW
            # compositing cannot block the pointer or repeatedly run beauty.
            self.draw_patch_handles();self.draw_tool_cursor();return
        if d['mode']=='pan':
            x,y=d['screen'];self.view.pan(event.x-x,event.y-y);d['screen']=(event.x,event.y);self.draw();return
        # Each segment joins successive pointer positions, including sparse
        # motion events. The radius belongs to this stroke, never its length.
        self.paint_stroke(d['last'],p,d['r'],d['mode'])
        d['last']=p;self.draw()
    def finish_stroke(self):
        d=self.drag
        if d['mode']=='beauty_paint':self.finish_beauty_paint();return
        if d['mode']=='clean_select':self.finish_clean_paint();return
        if d['mode']=='effect_paint':self.finish_effect_paint();return
        if d['mode'].startswith('retouch_'):self.finish_manual();return
        if d['mode'].startswith('liquify_'):self.finish_liquify();return
        if d['mode']=='patch_move':
            changed=self.patches[d['index']][d['role']]!=d['original'];self.drag=None
            if changed:
                self.refresh();self.record('移动复制来源' if d['role']=='source' else '移动修复目标')
            else:self.draw()
            return
        self.drag=None;self.refresh();self.record({'mask_add':'添加部位蒙版','mask_subtract':'减去部位蒙版','erase':'排除选区','exclude':'取消部分 AI 选区','restore':'恢复部分 AI 选区'}.get(d['mode'],'手动补选'))
    def release(self,event):
        if self.drag and self.drag.get('mode')=='develop_gradient':self.finish_develop_gradient(event);return
        if self.drag and self.drag['mode']=='crop_edit':self.finish_crop_drag(event);return
        self.pointer=(event.x,event.y)
        if not self.drag:return
        if self.drag['mode']=='beauty_paint':self.update_beauty_paint(self.point(event));self.finish_beauty_paint();return
        if self.drag['mode']=='clean_select':self.update_clean_paint(self.point(event));self.finish_clean_paint();return
        if self.drag['mode']=='effect_paint':self.update_effect_paint(self.point(event));self.finish_effect_paint();return
        if self.drag['mode'].startswith('retouch_'):self.update_manual(self.point(event),force=True);self.finish_manual();return
        if self.drag['mode'].startswith('liquify_'):self.update_liquify(self.point(event));self.finish_liquify();return
        if self.drag['mode']=='pan':self.drag=None;self.draw();return
        if self.drag['mode']=='patch_move':self.motion(event);self.finish_stroke();return
        self.paint_stroke(self.drag['last'],self.point(event),self.drag['r'],self.drag['mode'])
        self.drag['last']=self.point(event);self.finish_stroke()
    def record(self,text):
        automation=getattr(self,'automation',None)
        if automation:automation.notify_changed()
        self.mark_draft()
        self.commit_edit(text)
        self.history.append(text);self.history=self.history[-20:]
        self.historylist.delete(0,'end')
        for text in reversed(self.history):self.historylist.insert('end',text)
    def shortcut(self,event,action):
        # Leave native text editing shortcuts to editable fields and dialogs.
        if isinstance(event.widget,(tk.Entry,tk.Text,ttk.Entry,ttk.Combobox)):return
        action();return 'break'
    def show_shortcuts(self):
        messagebox.showinfo('快捷键', 'Ctrl＋K：搜索功能与参数\nCtrl＋Z：撤销选区或美颜参数调整\nCtrl＋Y / Ctrl＋Shift＋Z：重做\nCtrl＋O：打开照片\nCtrl＋S：保存项目\nEsc：返回浏览（搜索中关闭搜索）\n空格＋拖动 / 中键拖动：临时平移\n浏览时 Ctrl＋滚轮：缩放照片\n修复时 Ctrl＋滚轮：调整工具大小\n取消AI / 恢复AI 时 Shift＋点击：处理整块自动选区',parent=self.root)
    def focus_section(self,section):
        if self.color_workbench.owns(section):
            self.color_workbench.focus_section(section);return
        top=section
        while top.master is not self.settings_panel and top.master is not None:
            top=top.master
        for key,sections in self.category_sections.items():
            if top in sections:
                if getattr(self,'active_category',None)!=key:self.select_category(key)
                break
        chain=[];parent=section
        while parent is not self.settings_panel and parent is not None:
            if isinstance(parent,Section):chain.append(parent)
            parent=parent.master
        for parent in reversed(chain):
            if not parent.opened:parent.toggle()
        self.root.update_idletasks()
        offset=section.winfo_rooty()-self.settings_panel.winfo_rooty()
        self.settings_scroll.yview_moveto(max(0,offset)/max(1,self.settings_panel.winfo_height()))
        self.schedule_feature_compare(section)
    def show_groups(self):
        self.show_feature_menu()
    def edit_snapshot(self):
        if not self.selection:return None
        self.sync_person_values()
        return {'protect_dark_points':bool(self.document.metadata.get('protect_dark_points',False)),'raw_settings':copy.deepcopy(self.document.raw_settings),'selection':self.selection.snapshot(),'parameters':self.parameters(),'people':copy.deepcopy(self.face_settings),'active_face':self.active_face,'threshold':float(self.threshold.get()),'feather':float(self.feather.get()),'patches':copy.deepcopy(self.patches),'selected_patch':self.selected_patch,'layers':packed_layers(self.region_layers),'active_layer':self.active_layer,'liquify':liquify.snapshot(self.liquify_state),'liquify_enabled':bool(self.liquify_enabled.get()),'manual_records':copy.deepcopy(self.manual_records),'manual_enabled':bool(self.manual_enabled.get()),'extensions':packed_state(self.extensions_snapshot())}
    def commit_edit(self,label):
        if self.restoring_edit:return
        state=self.edit_snapshot()
        if state is None:return
        if self.edit_index>=0:
            old=self.edit_states[self.edit_index][0]
            if state.get('protect_dark_points',False)==old.get('protect_dark_points',False) and state.get('raw_settings')==old.get('raw_settings') and equal_state(state.get('extensions'),old.get('extensions')) and state['manual_records']==old.get('manual_records',[]) and state['manual_enabled']==old.get('manual_enabled',True) and state['liquify_enabled']==old.get('liquify_enabled',False) and liquify.equal(state['liquify'],old.get('liquify')) and equal_layers(state['layers'],old.get('layers',[])) and state['patches']==old['patches'] and state['people']==old['people'] and (state['people'] or state['parameters']==old['parameters']) and state['threshold']==old['threshold'] and state['feather']==old['feather'] and all(np.array_equal(a,b) for a,b in zip(state['selection'],old['selection'])):return
        self.edit_states=self.edit_states[:self.edit_index+1]+[(state,label)]
        while len(self.edit_states)>21 or (len(self.edit_states)>2 and sum(sum(a.nbytes for a in s['selection'])+sum(l['mask'].nbytes+(l['mask_alpha'].nbytes if 'mask_alpha' in l else 0) for l in s.get('layers',[]))+sum(a.nbytes for a in s.get('extensions',{}).get('arrays',{}).values())+liquify.nbytes(s.get('liquify')) for s,_ in self.edit_states)>128*1024*1024):self.edit_states.pop(0)
        self.edit_index=len(self.edit_states)-1
    def restore_edit(self,index,verb):
        state,label=self.edit_states[index]
        settings=state.get('raw_settings')
        if settings is not None and self.document.is_raw and settings!=self.document.raw_settings:
            self.open(self.path,settings,preserve=True,edit_restore=(index,verb,list(self.edit_states)));return
        self.restoring_edit=True
        try:
            protection=state.get('protect_dark_points',False)
            if getattr(self.session,'protect_dark_points',False)!=protection:
                self.session.protect_dark_points=protection;self.session.scan_ai(float(state['threshold']))
            self.protect_dark_points.set(protection);self.document.metadata['protect_dark_points']=protection
            self.load_extensions(restore_state(state.get('extensions'),self.selection.mask.shape))
            self.selection.restore(state['selection'])
            self.manual_records=copy.deepcopy(state.get('manual_records',[]));self.manual_enabled.set(state.get('manual_enabled',True))
            self.liquify_state=liquify.restore(state.get('liquify'),self.selection.mask.shape);self.liquify_enabled.set(state.get('liquify_enabled',False))
            self.patches=copy.deepcopy(state.get('patches',[]));self.selected_patch=state.get('selected_patch')
            self.region_layers=unpacked_layers(state.get('layers',[]),self.selection.mask.shape);self.active_layer=state.get('active_layer',-1);self.sync_layers()
            self.face_settings=[normalized(v) for v in state['people']];self.active_face=state['active_face']
            for name,value in normalized(state['parameters']).items():getattr(self,name).set(value)
            self.load_person_controls()
            self.threshold.set(state['threshold']);self.feather.set(state['feather']);self.edit_index=index;self.refresh()
            if self.selected_patch is not None:self.load_patch_controls(self.selected_patch)
            else:self.sync_tools()
        finally:self.restoring_edit=False
        self.status.set(self.status.get()+'  /  '+verb+'：'+label)
    def undo(self):
        if self.busy or self.drag or not self.selection:return
        self.commit_edit('参数微调')
        if self.edit_index>0:self.restore_edit(self.edit_index-1,'撤销后')
    def redo(self):
        if self.busy or self.drag or not self.selection:return
        self.commit_edit('参数微调')
        if self.edit_index+1<len(self.edit_states):self.restore_edit(self.edit_index+1,'重做')
    def reset(self):
        if self.selection and not self.busy:self.selection.reset();self.refresh();self.record('恢复自动选区')
    def apply_defaults(self):
        if not self.session or self.busy:return
        values=self.face_defaults[self.active_face] if self.face_defaults else self.defaults
        self.apply_beauty_values(values,False,'使用当前人像推荐参数')
    def change_recommend_preference(self):
        try:save_auto_recommend(bool(self.auto_recommend.get()))
        except OSError as e:
            self.auto_recommend.set(auto_recommend_enabled());messagebox.showerror('无法保存全局设置',str(e),parent=self.root);return
        self.status.set('后续新导入照片：'+('自动使用推荐美颜' if self.auto_recommend.get() else '仅识别，暂不应用美颜；可点击使用推荐参数'))
    def export_beauty_preset(self):
        if not self.session or not self.face_settings or self.busy:return
        self.flush_parameters();self.sync_person_values()
        path=filedialog.asksaveasfilename(title='导出当前人像美颜配置',defaultextension='.portrait.json',filetypes=[('人像美颜配置','*.portrait.json')],initialfile=f'{self.path.stem}-人像{self.active_face+1}.portrait.json')
        if not path:return
        try:write_preset(path,self.face_settings[self.active_face],f'{self.path.stem} 人像 {self.active_face+1}')
        except (OSError,ValueError) as e:messagebox.showerror('无法导出配置',str(e),parent=self.root);return
        self.status.set('已导出美颜配置：'+path+'；复用参数，不复制照片选区或人物位置。')
    def import_beauty_preset(self):
        if not self.session or not self.face_settings or self.busy:return
        path=filedialog.askopenfilename(title='应用美颜配置到当前照片',filetypes=[('人像美颜配置','*.portrait.json'),('JSON 配置','*.json')])
        if not path:return
        try:values,name=read_preset(path)
        except (OSError,ValueError,TypeError) as e:messagebox.showerror('无法读取配置',str(e),parent=self.root);return
        self.apply_beauty_values(values,self.preset_all.get(),'应用配置：'+name)
    def apply_beauty_values(self,values,all_people=False,label='应用美颜参数'):
        if not self.session or not self.face_settings or self.busy:return
        self.flush_parameters();self.sync_person_values();values=normalized(values)
        targets=list(range(len(self.face_settings))) if all_people else [self.active_face]
        if self.liquify_state is not None and (self.liquify_state['flow'].any() or self.liquify_state['freeze'].any()):
            if any(any(values[k]!=self.face_settings[i].get(k,0) for k in SHAPE_KEYS) for i in targets):
                self.status.set('配置会改变已有形变的坐标基础。请先恢复画笔形变并清除冻结保护，再应用此配置。');return
        self.commit_edit('应用美颜参数前')
        for i in targets:self.face_settings[i]=normalized(values)
        self.load_person_controls()
        wanted=np.zeros(self.selection.mask.shape,bool)
        for i in targets:
            if self.face_settings[i]['repair']<=0:continue
            f=self.session.faces[i];a,b,c,d=f.box
            wanted[b:d,a:c]|=self.selection.mask[b:d,a:c]&self.selection.auto[b:d,a:c]&self.session.repair_safe[i]
        needed=wanted&~(self.done_mask>0) if self.done_mask is not None else wanted
        if not needed.any():
            self.refresh();self.record(label);self.update_recent();return
        session=self.session;small=self.small_mask.copy();previous=self.generated;old_done=self.done_mask.copy()
        def job():
            generated,info=inpaint_portrait(session.original,needed&~(small>0),self.progress,self.cancel,precision=True,retouch_engine=getattr(session,'retouch_engine',1))
            if previous is not None:
                merged=previous.copy();merged[needed]=generated[needed];generated=merged
            return generated,old_done|needed,info
        def ready(result):
            self.generated,self.done_mask,info=result;self.meta.update(info)
            self.refresh();self.record(label);self.update_recent()
        self.work(job,ready)
    def make_navigation(self):
        if self.output is None:return
        nw=max(dp(self.root,120),self.navigator.winfo_width());nh=int(self.navigator.cget('height'))
        from gpu_render import thumbnail,record_cpu_recovery
        try:im=thumbnail(self.output,(nw-dp(self.root,8),max(1,nh-dp(self.root,12))))
        except Exception as error:
            record_cpu_recovery('导航图',error);im=Image.fromarray(self.output);im.thumbnail((nw-dp(self.root,8),max(1,nh-dp(self.root,12))),Image.Resampling.LANCZOS)
        self.nav_photo=ImageTk.PhotoImage(im)
        self.nav_box=((nw-im.width)/2,(nh-im.height)/2,im.width,im.height)
    def fit(self):
        if self.session is None:return
        if self.document and self.document.metadata.get('camera_crop_composition') and getattr(self,'active_category',None)!='构图':
            import composition
            h,w=self.document.rgb.shape[:2];data=composition.checked(self.workflow_extensions.get('composition',{}))
            if not data['rotation'] and not data['quarter']:
                self.view.fit(composition.rectangle(w,h,data),self.size());self.draw();return
        super().fit()

    def draw(self):
        if hasattr(self,'color_workbench') and self.color_workbench.draw_preview():self.draw_camera_frame();return
        if self.session is None or self.output is None:
            if hasattr(self,'canvas'):
                self.canvas.delete('all');w,h=self.size()
                self.canvas.create_text(w/2,h/2-dp(self.root,32),text='让每一张人像，自然出彩',width=max(80,w-dp(self.root,24)),justify='center',fill=COLORS['text'],font=ui_font(self.root,16))
                self.canvas.create_text(w/2,h/2+dp(self.root,34),text='将照片拖入此处，或 文件 → 导入照片    ·    Ctrl＋O',width=max(80,w-dp(self.root,24)),justify='center',fill=COLORS['muted'],font=ui_font(self.root,11))
            return
        compared=getattr(self,'feature_compare_output',None)
        if self.draw_live_crop(compared,self.feature_compare_crop):return
        if compared is not None:
            if self.draw_fast_feature_compare():return
            actual=self.output;self.output=compared
            try:super().draw()
            finally:self.output=actual
            self.canvas.create_text(dp(self.root,15),dp(self.root,15),text='本功能关闭对比 · '+self.feature_compare_id.title,anchor='nw',fill=COLORS['accent'],font=ui_font(self.root,11,'bold'));return
        super().draw()
        self.draw_camera_frame()
        self.draw_liquify_guides()
        self.draw_composition_guides()
        self.draw_reshape_contour()
        if self.face_settings and len(self.session.faces)>1 and 0<=self.active_face<len(self.session.faces):
            f=self.session.faces[self.active_face];a,b,c,d=f.box;x,y=self.view.to_canvas(a,b,self.size());z,t=self.view.to_canvas(c,d,self.size())
            self.canvas.create_rectangle(x,y,z,t,outline=COLORS['accent'],dash=(4,3));self.canvas.create_text(x,y-9,anchor='sw',text=f'人像 {self.active_face+1}',fill=COLORS['accent'])
        self.draw_patch_handles();self.draw_tool_cursor()
        self.color_workbench.draw_default_compare()
        if hasattr(self.color_workbench,'mask_ui'):self.color_workbench.mask_ui.draw_handles()
        if self.nav_photo and self.document:
            x,y,w,h=self.nav_box;self.navigator.delete('all');self.navigator.create_image(x,y,anchor='nw',image=self.nav_photo)
            H,W=self.output.shape[:2];cw,ch=self.size();a,b=self.view.to_image(0,0,(cw,ch));c,d=self.view.to_image(cw,ch,(cw,ch))
            self.navigator.create_rectangle(x+max(0,a)/W*w,y+max(0,b)/H*h,x+min(W,c)/W*w,y+min(H,d)/H*h,outline='#b8c7db',width=1)
    def draw_patch_handles(self):
        self.canvas.delete('patch_handles')
        if self.session and self.mode.get() in ('heal','clone') and not self.space:
            for i,p in enumerate(self.patches):
                color='#a7dcff' if i==self.selected_patch else '#9da9b9';r=p['radius']*self.view.scale
                sx,sy=self.view.to_canvas(*p['source'],self.size());tx,ty=self.view.to_canvas(*p['target'],self.size())
                self.canvas.create_line(sx,sy,tx,ty,fill=color,dash=(4,3),tags='patch_handles')
                for x,y in [(sx,sy),(tx,ty)]:self.canvas.create_oval(x-r,y-r,x+r,y+r,outline=color,width=2,tags='patch_handles')
                self.canvas.create_text(sx,sy,text='+',font=('Segoe UI',14,'bold'),fill=color,tags='patch_handles')
                self.canvas.create_oval(tx-3,ty-3,tx+3,ty+3,fill=color,outline='#171b20',tags='patch_handles')
                if i==self.selected_patch:
                    for x,y,label in [(sx,sy,'取样'),(tx,ty,'修复')]:
                        self.canvas.create_text(x+1,y-max(r,12)-9+1,text=label,fill='#171b20',tags='patch_handles')
                        self.canvas.create_text(x,y-max(r,12)-9,text=label,fill=color,tags='patch_handles')
    def nav_click(self,event):
        if not self.nav_box or self.output is None:return
        x,y,w,h=self.nav_box
        if x<=event.x<=x+w and y<=event.y<=y+h:
            H,W=self.output.shape[:2];self.view.cx=(event.x-x)/w*W;self.view.cy=(event.y-y)/h*H;self.draw()
    def draw_histogram(self):
        if self.output is None:return
        self.histogram.delete('all');w=max(250,self.histogram.winfo_width());h=92
        from gpu_render import histogram,record_cpu_recovery
        try:values=histogram(self.output)
        except Exception as error:
            record_cpu_recovery('直方图采样',error);small=cv2.resize(self.output,(320,240));values=[np.histogram(small[:,:,i],bins=64,range=(0,256))[0] for i in range(3)]
        peak=max(1,max(np.percentile(v,98) for v in values))
        for hist,color in zip(values,['#b67876','#83a487','#779dc2']):
            points=[]
            for i,v in enumerate(hist):points.extend([i/63*w,h-4-min(h-8,v/peak*(h-8))])
            self.histogram.create_line(*points,fill=color,width=1.4)
    def update_recent(self):
        self.keep_current();self.draw_filmstrip()
    def capture_photo(self):
        self.sync_person_values()
        names=('document','session','selection','path','output','output_float','generated','done_mask','meta','defaults','recommendation','small_mask','view','project_path','slim_cache','slim_ready','slim_changed','form_cache','form_changed','reshape_cache','reshape_changed','photo_body_cache','photo_body_changed','photo_body_message','liquify_state','liquify_input','manual_records','manual_input','manual_source','manual_offset','manual_anchor','history','edit_states','edit_index','face_settings','face_defaults','active_face','patches','selected_patch','region_layers','active_layer','creative_input','creative_output','color_input')
        state={name:getattr(self,name) for name in names}
        state['vars']={name:getattr(self,name).get() for name in NAMES+('threshold','radius','feather','patch_opacity','mask_overlay','overlay','split','raw_ev','raw_wb','raw_process','raw_kelvin','raw_tint','camera_look','camera_mode','camera_profile','filename','fileinfo','summary','status','liquify_enabled','liquify_radius','liquify_strength','liquify_density','liquify_rate','liquify_guide_face','liquify_guide_body','liquify_fix_nodes')+MANUAL_VARS}
        state['raw_label']=self.raw_label.cget('text');state['workflow_extensions']=self.extensions_snapshot();return state
    def keep_current(self):
        if not self.document or self.output is None:return
        self.flush_parameters()
        from gpu_render import thumbnail,record_cpu_recovery
        try:thumb=thumbnail(self.output,(240,222))
        except Exception as error:
            record_cpu_recovery('照片缩略图',error);thumb=Image.fromarray(self.output);thumb.thumbnail((240,222),Image.Resampling.LANCZOS)
        self.library.remember(self.path,self.capture_photo(),thumb.copy())
    def flush_parameters(self):
        if self.drag and self.drag['mode'].startswith('retouch_'):self.finish_manual()
        if self.drag and self.drag['mode'].startswith('liquify_'):self.finish_liquify()
        # Render a keyboard-debounced adjustment before export or photo caching.
        for control in self.controls:
            if isinstance(control,ParameterScale) and control.dirty and control.mutating:
                control.cancel_pending();control.commit()
        self.wait_parameter_render()
    def restore_photo(self,state):
        self.end_feature_compare()
        self.invalidate_feature_cache()
        self.invalidate_parameter_render()
        # Reject incomplete states left by the old import callback before making
        # any live assignment. Healthy cached photos never trigger inference.
        count=len(state['session'].faces)
        if len(state['face_settings'])!=count:
            raise ValueError('旧缓存的人像设置不完整，请将该图移出视图区再重新导入；原照片未改变。')
        self.form_cache={};self.form_changed=None
        self.reshape_cache={};self.reshape_changed=False
        self.photo_body_cache={};self.photo_body_changed=False;self.photo_body_message='身体美型已关闭。'
        self.liquify_state=None;self.liquify_input=None;self.liquify_enabled.set(False)
        self.liquify_density.set(50);self.liquify_rate.set(50)
        self.liquify_guide_face.set(True);self.liquify_guide_body.set(True);self.liquify_fix_nodes.set(True)
        self.reset_retouch_state();self.load_manual_settings();self.manual_enabled.set(True)
        for name,value in state.items():
            if name not in ('vars','raw_label'):setattr(self,name,value)
        retired=any(v.get(k,0) for v in self.face_settings for k in ('wrinkles','dark_circles','slim','double_chin','armpit_left','armpit_right'))
        self.face_settings=[normalized(v) for v in self.face_settings]
        self.active_face=max(0,min(self.active_face,len(self.face_settings)-1)) if self.face_settings else 0
        self.loading_face=True
        for key in ('body_slim','waist_slim','leg_slim','leg_length'):getattr(self,key).set(state['vars'].get(key,0))
        for name,value in state['vars'].items():getattr(self,name).set(value)
        self.protect_dark_points.set(getattr(self.session,'protect_dark_points',False))
        self.loading_face=False;self.raw_label.configure(text=state['raw_label']);self.load_person_controls()
        if state.get('_recovery_manual_tools'):self.load_manual_settings(state['_recovery_manual_tools'])
        self.load_extensions(state.get('_recovery_extensions',state.get('workflow_extensions',{})))
        self.sync_layers()
        self.person_control.configure(values=[f'人像 {i+1}' for i in range(len(self.face_settings))])
        self.profile_control.configure(values=['按拍摄风格匹配']+self.document.metadata.get('profile_choices',[]))
        self.historylist.delete(0,'end')
        for text in reversed(self.history):self.historylist.insert('end',text)
        # One-time ownership upgrade of existing v18 caches uses the cached
        # head parser, not another full pose or face-detection model pass.
        beauty_upgrade=any((getattr(f,'beauty_mask_key',None) or (0,))[0]!=21 for f in self.session.faces)
        if getattr(self,'_filter_lut_repaired',False):state=dict(state,_recovery_render=True)
        if state.get('_recovery_render') or retired or beauty_upgrade or self.shape_pending() or eye_wrinkle_pending(self.session,self.face_settings) or (getattr(self.session,'body_revision',None)==18 and (getattr(self.session,'head_skin_revision',None)!=19 or getattr(self.session,'ownership_revision',None)!=19)):self.refresh()
        self.photo_body_note.set(self.photo_body_message)
        self.drag=None;self.select_tool('pan');self.make_navigation();self.draw_histogram();self.draw_filmstrip();self.draw();self.enable()
        self.status.set(self.status.get()+'  /  已恢复缓存与参数')
    def draw_filmstrip(self):
        self.filmstrip.delete('all');self.film_photos=[]
        for i,(key,entry) in enumerate(self.library.entries.items()):
            path,thumb=entry['path'],entry['thumb'];active=path==self.path
            x=12+i*104;image=thumb.copy();image.thumbnail((dp(self.root,80),dp(self.root,74)))
            photo=ImageTk.PhotoImage(image);self.film_photos.append(photo)
            tag=f'photo{i}';self.filmstrip.create_rectangle(dp(self.root,x),dp(self.root,4),dp(self.root,x+94),dp(self.root,98),fill=COLORS['selected'] if active else COLORS['panel'],outline=COLORS['accent'] if active else COLORS['border'],tags=tag)
            self.filmstrip.create_image(dp(self.root,x+47),dp(self.root,43),image=photo,tags=tag)
            self.filmstrip.create_text(dp(self.root,x+47),dp(self.root,87),text=path.name[:13],fill=COLORS['text'],font=ui_font(self.root,9),tags=tag)
            self.filmstrip.tag_bind(tag,'<Button-1>',lambda e,p=path:self.open(p))
            self.filmstrip.tag_bind(tag,'<Button-3>',lambda e,k=key:self.film_menu(e,k))
        self.filmstrip.configure(scrollregion=(0,0,dp(self.root,max(1,len(self.library.entries)*104+24)),dp(self.root,104)))
    def film_menu(self,event,key):
        if self.busy:return
        menu=tk.Menu(self.root,tearoff=False,bg=COLORS['panel'],fg=COLORS['text'])
        menu.add_command(label='进入照片设置',command=lambda:self.open(self.library.entries[key]['path']))
        menu.add_command(label='复制当前人像美颜参数',command=lambda:self.copy_settings(key))
        state='normal' if self.settings_clipboard else 'disabled'
        menu.add_command(label='粘贴美颜参数到当前人像',state=state,command=lambda:self.paste_settings(key,False))
        menu.add_command(label='粘贴美颜参数到全部人像',state=state,command=lambda:self.paste_settings(key,True))
        menu.add_separator();menu.add_command(label='从视图区移除（保留原文件）',command=lambda:self.remove_photo(key))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
    def copy_settings(self,key):
        if self.document:self.keep_current()
        def ready(state):self.settings_clipboard={name:state['vars'][name] for name in NAMES};self.status.set('已复制美颜参数（不复制 RAW 配置或选区）')
        if key in self.library.hot:ready(self.library.hot[key])
        else:self.work(lambda:self.library.load(key),ready)
    def paste_settings(self,key,all_people):
        if not self.settings_clipboard:return
        if self.document:self.keep_current()
        values=dict(self.settings_clipboard)
        def ready(state):
            self.restore_photo(state)
            if all_people and self.face_settings:self.face_settings=[dict(values) for _ in self.face_settings];self.load_person_controls()
            else:
                for name,value in values.items():getattr(self,name).set(value)
            self.refresh();self.record('粘贴美颜参数到全部人像' if all_people else '粘贴当前人像美颜参数');self.update_recent()
        if key in self.library.hot:ready(self.library.hot[key])
        else:self.work(lambda:self.library.load(key),ready)
    def remove_photo(self,key):
        if self.busy:return
        if self.document:self.keep_current()
        self.library.remove(key)
        if self.path and self.library.key(self.path)==key:
            if self.library.entries:
                next_key=next(iter(self.library.entries));self.document=self.session=self.selection=self.output=self.output_float=None;self.path=None;self.open(self.library.entries[next_key]['path']);return
            self.document=self.session=self.selection=self.output=self.output_float=None;self.path=None;self.face_settings=[];self.region_layers=[];self.active_layer=-1;self.sync_layers();self.canvas.delete('all');self.navigator.delete('all');self.histogram.delete('all');self.filename.set('尚未打开照片');self.fileinfo.set('Sony / Canon / Nikon / Fujifilm');self.person.set('尚未识别人像');self.person_control.configure(values=[]);self.status.set('已移出视图区，原文件仍保留。')
        self.draw_filmstrip();self.enable()
    def export(self):
        if not self.document or self.busy:return
        self.flush_parameters()
        if self.repair_pending():messagebox.showinfo('选区待处理','请先点击 AI 修复当前选区。');return
        if self.shape_pending():messagebox.showinfo('面部重塑待处理','请等待校准与形变完成；取消后可点击“重新校准轮廓”重试。');return
        if self.busy:return
        from develop_output import checked
        settings=checked(self.workflow_extensions.get('output',{}))
        label='TIFF · HDR浮点32位 '+settings['space'] if settings['hdr'] else 'TIFF · 16位 '+settings['space']
        if self.document.metadata.get('camera_source')=='embedded_preview':label+=' / 8位机内源'
        path=filedialog.asksaveasfilename(initialdir=str(ROOT),initialfile=self.path.stem+'-AURA.tif',defaultextension='.tif',filetypes=[(label,'*.tif'),('PNG · 8位','*.png'),('JPEG · 高质量','*.jpg')])
        if not path:return
        image=self.prepare_export_image(self.output_float.copy())
        def ready(_):self.status.set('已导出：'+path);self.record('导出 '+Path(path).suffix.upper())
        options=copy.deepcopy(self.workflow_extensions.get('output',{}))
        self.work(lambda:export_document(path,image,depth=16,options=options),ready,cancellable=False)
    def save_recipe(self):
        if not self.document or self.busy:return
        self.flush_parameters()
        if self.shape_pending():messagebox.showinfo('面部重塑待处理','请等待校准与形变完成后保存；取消后可点击“重新校准轮廓”重试。');return
        if self.busy:return
        path=filedialog.asksaveasfilename(initialdir=str(ROOT),initialfile=self.path.stem+'.beauty',defaultextension='.beauty',filetypes=[('本地美颜项目','*.beauty')])
        if not path:return
        document=self.document;parameters=self.parameters();threshold=float(self.threshold.get());selection=self.selection;done=self.done_mask;small=self.small_mask;defaults=self.defaults.copy();tools={'radius':self.brushradius(),'feather':float(self.feather.get())}
        def ready(_):self.project_path=Path(path);self.status.set('项目已保存：'+path);self.record('保存项目')
        people=self.people_records()
        patches=copy.deepcopy(self.patches)
        layers=copy.deepcopy(self.region_layers)
        liquid=liquify.snapshot(self.liquify_state);liquid_settings=self.liquify_settings()
        manual=copy.deepcopy(self.manual_records);manual_tools=self.manual_settings();manual_enabled=bool(self.manual_enabled.get())
        extensions=self.extensions_snapshot()
        self.work(lambda:save_project(path,document,parameters,threshold,selection,done,small,defaults,tools,people,patches,layers,liquid,liquid_settings,manual,manual_tools,manual_enabled,extensions=extensions),ready,cancellable=False)
    def choose_project(self):
        if self.busy:return
        path=filedialog.askopenfilename(filetypes=[('AURA照片项目','*.beauty *.aura-mobile.zip'),('本地美颜项目','*.beauty'),('安卓照片项目','*.aura-mobile.zip')])
        if path:self.load_recipe(path)
    def load_recipe(self,path):
        if self.busy:return
        def job():
            meta,masks=read_project(path);source=Path(meta['source'])
            if not source.exists():return meta,masks,None
            if sha256_file(source)!=meta['source_sha256']:raise ValueError('原图内容已改变，不能可靠恢复此项目。')
            return meta,masks,source
        def ready(result):
            meta,masks,source=result
            if source is None:
                chosen=filedialog.askopenfilename(title='原图已移动，请选择项目对应的原图')
                if not chosen:return
                source=Path(chosen)
                if sha256_file(source)!=meta['source_sha256']:messagebox.showerror('原图不匹配','所选文件内容与项目记录不符。');return
            self.open(source,meta['raw_settings'],project=(meta,masks))
        self.work(job,ready)

def main():
    enable_dpi();root=tk.Tk();app=App(root)
    if len(sys.argv)>1:
        path=filedialog.askopenfilename() if sys.argv[1]=='--demo' else sys.argv[1]
        if path:
            root.after(250,lambda:app.load_recipe(path) if str(path).lower().endswith('.beauty') else app.open(path,as_shot_import=True))
    root.mainloop()
if __name__=='__main__':main()
