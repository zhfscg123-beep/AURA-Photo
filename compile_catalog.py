"""Build the reviewed offline catalog; numeric IDs refer to the frozen extraction."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parent
sources=list(json.loads((ROOT/'localization/messages.json').read_text(encoding='utf8')))
entries={}
for path in sorted((ROOT/'localization').glob('english-*.tsv')):
    for line in path.read_text(encoding='utf8').splitlines():
        if not line:continue
        index,value=line.split('\t',1);index=int(index)
        assert index not in entries,(path,index)
        assert value.strip(),index
        entries[index]=value.replace('\\n','\n')
assert set(entries)==set(range(len(sources))),set(range(len(sources)))-set(entries)
catalog={source:entries[index] for index,source in enumerate(sources)}
catalog.update({
    '语言 / Language':'Language',
    '简体中文':'简体中文',
    '立即切换界面语言，保留当前照片和编辑状态。':'Switch the interface language immediately, keeping the current photo and edits.',
    '无法保存语言设置':'Could not save language preference',
    '语言':'Language',
    '独立静态照片版':'Standalone still photo edition',
    '安装器可选择中文或英文，设置中可随时更改。':'Choose Chinese or English during setup; change it anytime in Settings.',
    '使用 AURA Photo 安装包更新，保留本版设置。':'Update with an AURA Photo installer to keep this edition\'s settings.',
    '平整':'Evenness','提亮':'Brighten',
})
for cn,en in [('额头','Forehead'),('面中','Midface'),('鼻基底','Nasal base'),('下巴','Chin')]:
    catalog[cn+'丰盈']=en+' volume'
# These hints are assembled from several adjacent runtime fragments.
for region,description in [('面部','Paint visible skin missed near bangs and hair, then update to apply face adjustments. Eyeballs remain protected. Only the current person\'s face is affected; hair is not removed automatically.'),('身体','Paint missed skin on the neck, arms and other body areas, then update to apply body adjustments. The face and other confirmed people remain protected.')]:
    source=('绿色为自动范围，青色为补选，红色为已擦除。'+('补画刘海、发丝附近漏识别的可见皮肤，再点击更新应用面部参数。眼球保持保护；只作用于当前人物面部范围，不会自动去除头发。' if region=='面部' else '补画脖颈、手臂等漏识别皮肤，再点击更新应用身体参数。面部与其他已确认人物保持保护。')+'擦除可排除AI自动范围；恢复画笔局部恢复原自动范围。边缘自动渐淡。右键临时擦除，Ctrl＋滚轮调大小，空格平移，Esc返回浏览。')
    catalog[source]='Green: automatic area; cyan: added; red: erased. '+description+' Erase excludes automatic selections; Restore restores them locally. Edges fade automatically. Right button: erase · Ctrl + wheel: size · Space: pan · Esc: browse.'
templates=json.loads((ROOT/'localization/templates-en_US.json').read_text(encoding='utf8'))
source_templates=json.loads((ROOT/'localization/templates.json').read_text(encoding='utf8'))
assert templates.keys()==source_templates.keys(),source_templates.keys()-templates.keys()
for source,target in templates.items():
    assert sorted(re.findall(r'\{\d+\}',source))==sorted(re.findall(r'\{\d+\}',target)),source
out=ROOT/'app/locales';out.mkdir(exist_ok=True)
(out/'en_US.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8')
(out/'templates-en_US.json').write_text(json.dumps(templates,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'messages':len(catalog),'templates':len(templates)}))
