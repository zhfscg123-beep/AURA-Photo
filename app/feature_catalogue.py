"""Explicit navigation ownership and a dependency-free local feature search."""
from dataclasses import dataclass
import re,unicodedata

@dataclass(frozen=True)
class Group:
    key:str
    icon:str
    scope:str
    purpose:str
    sections:tuple

GROUPS=(
    Group('调色','color','整张照片','打开独立调色工作台，调整全局影调与RAW显影。',('color_entry','global_color','raw','histogram','reference')),
    Group('美颜','person','当前人物','推荐参数、肤色、肤质、祛瑕、祛纹与人像补光。',('portrait','skin_color','skin_texture','face_details','wrinkles','volume','light')),
    Group('身体','body','身体皮肤 / 单人照片的身体轮廓','身体美肤、瑕疵，以及照片模式的瘦身、瘦腰、瘦腿和拉腿。',('body','photo_body')),
    Group('塑形','shape','当前人物 / 手动形变区域','脸型预设、智能五官与液化画笔 / 悬停节点。',('reshape','liquify')),
    Group('妆发','makeup','当前人物','唇色、腮红与发色，强度默认关闭。',('makeup',)),
    Group('衣物','clothes','当前人物的衣物','淡化衣物细褶皱、调整衣物颜色。',('fabric','clothes_color')),
    Group('背景','background','背景区域','调整背景颜色与柔化；可查看和修正背景范围。',('background',)),
    Group('蒙版','mask','当前人物 / 当前蒙版','识别部位、合并或分别生成范围，补选、修边与局部调色。',('parts','smart_mask')),
    Group('修复','repair','手动选区 / 所选处理阶段','修饰画笔、迁移仿制、AI清理与效果擦回。',('manual','repair','detection','clean','effects')),
    Group('构图','crop','整张照片的导出取景','裁剪、水平校正和旋转；可用当前人物作为取景中心。',('composition',)),
)

# Stable section IDs point to explicitly assigned UI attributes, never title prefixes.
SECTIONS={
 'color_entry':('color_entry_panel','独立调色工作台','独立窗口中调整影调、曲线、颜色、分级、细节与RAW；应用后继续编辑，返回时可处理未应用调整。','Camera Raw 工作台 独立窗口 调色'),
 'portrait':('portrait_panel','推荐与基础美颜','基础磨皮、美白与纹理覆盖脸、耳、颈及身体皮肤；面部漏识别可用美颜范围画笔补选，祛痘检测独立。','人像 皮肤 推荐 自动美颜 漏选 刘海 发丝 下巴 羽化 手动补选 portrait beauty'),
 'skin_color':('color_panel','肤色取样与肤色方案','先取样，再调整面部或身体的肤色匹配强度。','吸管 肤色 取色 skin tone eyedropper'),
 'skin_texture':('texture_panel','皮肤质感与肤色微调','明暗、频率、光泽及肤色微调。','肤质 磨皮 哑光 水光 缎面 skin texture'),
 'face_details':('face_detail_panel','面部祛瑕','面部候选瑕疵的细分、AI修复，以及质感、胡须与妆容保护。','瑕疵 痘痘 去痘 acne blemish'),
 'wrinkles':('wrinkle_panel','分区域祛纹','额头、眼周和法令纹等采用DAMO混合图层局部祛纹，保留眼球、睫毛与痣点；不追加美白。','去皱 去纹 眼下 DAMO quzhou wrinkles'),
 'volume':('volume_panel','光影立体与局部丰盈','通过亮暗调整视觉体积、眼袋或下颌阴影，不移动脸部边缘。','光影 丰盈 面中 额头 volume contour'),
 'light':('light_panel','几何柔光与多光源','深度和法线估计驱动当前人物补光；多灯、调色、轮廓光及可见深度遮挡。','打光 柔光 补光 灯 多光源 轮廓光 深度 法线 light relight'),
 'body':('body_panel','身体磨皮、肤色与祛瑕','身体参数作用于全部已确认或手动补选身体皮肤；可擦除AI范围、恢复并预览。','脖子 脖颈 颈部 耳朵 手臂 补选 擦除 恢复 范围 body skin neck'),
 'photo_body':('photo_body_panel','自动身体美型 · 照片','自动瘦身、瘦腰、瘦腿、拉腿；当前仅开放单人照片。','瘦身 瘦腰 瘦腿 长腿 拉腿 美体 身材 body shape waist legs slim'),
 'reshape':('reshape_panel','脸型预设与轮廓调整','移动脸部轮廓；人物左右按人物自身区分。','瘦脸 小脸 V脸 下巴 脸型 shoulian reshape face'),
 'liquify':('liquify_panel','手动液化与智能五官','液化画笔、冻结保护、辅助线节点及智能五官。','眼睛 鼻子 嘴巴 PS 五官 liquify push freeze thaw'),
 'makeup':('makeup_panel','唇色、腮红与发色','按人物调整唇色、腮红和发色，保留原纹理。','化妆 口红 头发 染发 makeup lips hair'),
 'fabric':('fabric_panel','衣物褶皱整理','淡化浅细褶皱；复杂折痕可在“修复”中选区AI清理。','衣服 褶皱 布料 fabric clothes'),
 'clothes_color':('clothes_color_panel','衣物改色','只调整当前人物衣物区域的颜色。','衣服 服装 换色 染色 recolor clothing'),
 'background':('background_panel','背景颜色与柔化','先查看背景范围，再调整曝光、颜色和均匀柔化。','虚化 背景 模糊 background blur'),
 'histogram':('histogram_panel','直方图','查看全图RGB明暗分布。','histogram RGB 高光 阴影'),
 'raw':('raw_panel','RAW显影与相机风格','选择RAW来源、白平衡、曝光补偿及相机风格。','相机 机内 配置 白平衡 camera raw develop'),
 'global_color':('creative_color_panel','专业调色与显影工具','成品滤镜、实拍预览、收藏与个人风格；浮点影调、白平衡、曲线、HSL、分级和显影。','滤镜 成品 预设 收藏 人像 日系 胶片 电影 黑白 filters presets 曝光 曲线 饱和度 白平衡 色温 点颜色 分级 降噪 锐化 镜头 透视 软打样 ICC HDR 调色 curves HSL LUT color'),
 'reference':('reference_panel','参考图追色','按指定区域分别匹配颜色和影调。','参考图 追色 色彩匹配 reference match'),
 'parts':('mask_panel','AI部位蒙版','按人物选择面部、身体皮肤和五官等范围，合并或分别生成。','选区 部位 自动蒙版 mask selection'),
 'smart_mask':('smart_mask_panel','智能补选与蒙版修边','补全或减去范围，扩展、收缩、羽化及调整强度；部位蒙版支持渐变和颜色/亮度范围。','漏选 补全 边缘 智能选区 线性渐变 径向渐变 颜色范围 亮度范围 refine feather'),
 'manual':('manual_panel','手动修饰画笔','减淡、加深、修复画笔、仿制和恢复，可连续涂画。','磨皮 手工 修饰 PS dodge burn clone heal brush'),
 'repair':('repair_panel','选区修复与迁移仿制','补选后AI修复，或移动圆框取样做迁移、仿制。','圆框 迁移 修补 仿制 stamp healing'),
 'detection':('detection_panel','AI候选识别与前后对比','重扫瑕疵候选、调整阈值、恢复自动选区和对比结果。','检测 识别 阈值 对照 前后 compare threshold'),
 'clean':('clean_panel','衣物与背景AI清理','明确选择衣物或背景对象，再涂抹要清理的范围。','消除 去物 擦除 毛球 灰尘 remove cleanup inpaint'),
 'effects':('effect_panel','效果开关与局部擦回','对所选处理阶段隐藏、减弱或局部擦回。','效果管理 图层 隐藏 撤销 擦回 layers effects'),
 'composition':('composition_panel','裁剪、比例与水平校正','主画面实时拖动裁剪框及旋转，导出保留完整精度；编辑坐标保持原图。','裁切 构图 裁剪 校正 straighten rotate crop'),
}
LEGACY={'人像':'美颜','肤色':'美颜','瑕疵':'美颜','祛纹':'美颜','创作':'背景','显影':'调色'}

@dataclass
class Feature:
    key:str
    title:str
    path:str
    description:str
    aliases:str=''
    target:object=None
    section:object=None
    location:str='panel'

def normalized(text):
    return re.sub(r'[^\w\u4e00-\u9fff]+',' ',unicodedata.normalize('NFKC',text).casefold()).strip()

def search(features,query,limit=60):
    for old,new in (('去眼周纹','眼周纹'),('去眼纹','眼周纹'),('眼纹','眼周纹'),('去皱纹','祛纹'),('去痘','祛痘'),('变白','美白')):
        query=query.replace(old,new)
    for old in ('脖子美白','脖颈美白','颈部美白'):query=query.replace(old,'身体美白')
    query=normalized(query);tokens=query.split()
    if not tokens:
        ordered=[f for f in features if f.key.startswith('module:') or f.location=='action']
        ordered+=[f for f in features if f not in ordered]
        return ordered[:limit]
    ranked=[]
    for order,item in enumerate(features):
        from i18n import tr
        title=normalized(item.title+' '+tr(item.title,'en_US'));path=normalized(item.path+' '+tr(item.path,'en_US'));aliases=normalized(item.aliases)
        content=' '.join((title,path,aliases))
        if not all(token in content or token in content.replace(' ','') for token in tokens):continue
        score=100 if query==title else 65 if query in title else 35 if all(t in title for t in tokens) else 15
        if item.location=='file':score+=20
        if item.location=='section':score+=4
        ranked.append((-score,order,item))
    return [item for _,_,item in sorted(ranked)[:limit]]
