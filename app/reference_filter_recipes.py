"""Original AURA recipes inspired by six user-selected public tutorials.

Values are fitted to AURA's own color engine, not copied Adobe/PixelCake
renderings. Per-photo exposure/WB, sky masks and portrait retouch stay separate.
"""
import hashlib,json

ANIME=[[0,0],[.07,.072],[.2,.255],[.42,.53],[.65,.735],[.84,.875],[.95,.95],[1,.985]]
PASTEL=[[0,.003],[.1,.115],[.3,.365],[.52,.6],[.75,.825],[.93,.958],[1,1]]
FILM_GREEN=[[0,.008],[.10,.09],[.25,.27],[.5,.55],[.75,.795],[.94,.96],[1,.995]]
SUN=[[0,0],[.12,.10],[.3,.30],[.5,.54],[.73,.80],[.93,.96],[1,1]]
SOFT_LIGHT=[[0,0],[.06,.07],[.18,.225],[.4,.485],[.65,.725],[.87,.92],[1,1]]
MINT=[[0,0],[.08,.08],[.22,.275],[.45,.55],[.68,.77],[.9,.955],[1,1]]

def build(preset):
    specs=[
      ('xhs-anime-cyan','动漫晴空','69e34167000000001b0005ce','壮壮Sight · 日系动漫感调色思路',
       '清青蓝色、鲜活草地与自然肤色；中间调提亮、高光柔和收束。适合晴天户外，人物与天空的亮度仍需按照片分区调整。',
       dict(contrast=6,highlights=-32,shadows=12,whites=-4,blacks=-3,saturation=-4,vibrance=24,clarity=2,dehaze=2,curve_saturation=45,shadow_hue=230,shadow_color=5,highlight_hue=230,highlight_color=3,grading_blend=70,grading_balance=15,skin_protect=35),
       {'橙':[-2,-7,2],'黄':[12,-6,4],'绿':[18,10,8],'青':[-6,14,4],'蓝':[-24,30,0]},
       {'rgb':ANIME,'r':[[0,0],[.2,.187],[.55,.55],[1,1]],'b':[[0,0],[.2,.21],[.55,.558],[1,1]]}),
      ('xhs-pastel-blue','粉蓝通透','69a6dcd2000000001a025fa1','LeoX香吉士 · 摩天轮通透感',
       '浅青天空、柔和白色与轻暖中间调；适合旅行、建筑和高光比场景。',
       dict(contrast=-3,highlights=-44,shadows=15,whites=-2,blacks=-3,texture=4,clarity=-2,dehaze=1,saturation=-9,vibrance=20,shadow_hue=226,shadow_color=5,midtone_hue=48,midtone_color=3,highlight_hue=48,highlight_color=3,cal_red_hue=8,cal_green_hue=6,cal_blue_hue=-7,skin_protect=32),
       {'橙':[1,-5,6],'黄':[-5,-12,0],'绿':[9,-8,-2],'青':[-8,10,8],'蓝':[-24,-8,12]},
       {'rgb':PASTEL,'b':[[0,0],[.18,.195],[.5,.515],[.85,.865],[1,1]]}),
      ('xhs-film-green','晴日胶片绿','68502f690000000003039fdc','蛋黄 · 日系胶片感',
       '低饱和深青绿、橘暖肤色与奶蓝天空；保留扎实黑位和细颗粒。',
       dict(contrast=3,highlights=-36,shadows=9,whites=0,blacks=-5,saturation=-7,vibrance=12,shadow_hue=150,shadow_color=8,midtone_hue=70,midtone_color=5,highlight_hue=207,highlight_color=5,cal_red_sat=6,cal_green_sat=-5,cal_blue_sat=8,grain=8,grain_model=1,grain_size=2.2,skin_protect=30),
       {'红':[10,10,3],'橙':[-1,1,8],'黄':[-22,-22,2],'绿':[12,-38,-14],'青':[7,-10,0],'蓝':[-12,-10,-4]},
       {'rgb':FILM_GREEN}),
      ('xhs-sun-negative','阳光负片','69030e1e000000000703781e','白榆川Ycc · 数码仿胶片',
       '偏青环境、自然亮肤与有厚度的暗部；适合有阳光的街头人像。',
       dict(contrast=3,highlights=-40,shadows=5,whites=-2,blacks=-3,saturation=-5,shadow_hue=221,shadow_color=7,highlight_hue=38,highlight_color=2,grain=10,grain_model=1,grain_size=2.4,skin_protect=30),
       {'红':[8,-5,5],'橙':[4,-8,7],'黄':[5,-16,0],'绿':[16,-20,-4],'青':[0,-12,0],'蓝':[-5,-18,-10],'紫':[0,-40,0],'洋红':[0,-40,0]},
       {'rgb':SUN,'r':[[0,0],[.25,.235],[.5,.52],[.78,.83],[1,1]],'g':[[0,0],[.25,.235],[.5,.515],[.78,.83],[1,1]],'b':[[0,0],[.2196,.19],[.5,.51],[.78,.84],[1,1]]}),
      ('xhs-soft-toplight','顶光柔色','6a609795000000002201a10a','星川明 · 顶光日系清新',
       '提亮暗部肤色、清青蓝色与轻暖高光。这里只套用调色，原帖的美颜和AI追色需另做。',
       dict(contrast=-3,highlights=-36,shadows=19,whites=0,blacks=-3,saturation=-3,vibrance=8,clarity=-1,shadow_hue=236,shadow_color=3,midtone_hue=224,midtone_color=3,highlight_hue=45,highlight_color=4,skin_protect=30),
       {'橙':[5,-14,10],'黄':[0,-10,0],'绿':[5,-6,-2],'蓝':[-16,8,5]},
       {'rgb':SOFT_LIGHT}),
      ('xhs-mint-fresh','薄荷小清新','6729a223000000001b02de44','雨雨修图分享 · 日系小清新',
       '明亮肤色、青绿植被与完整黑位；适合树荫、逆光和自然环境人像。',
       dict(contrast=4,highlights=-40,shadows=13,whites=-1,blacks=-4,vibrance=14,saturation=-3,midtone_luma=10,skin_protect=30),
       {'橙':[0,-7,7],'红':[0,-4,2],'黄':[5,-12,0],'绿':[16,7,-9],'青':[-6,8,1],'蓝':[-10,8,-3]},
       {'rgb':MINT}),
    ]
    result=[]
    for key,name,note,author,description,values,hsl,points in specs:
        item=preset(key,name,'日系参考',description,values,hsl,points)
        item['source']=dict(label='小红书参考 · '+author,url='https://www.xiaohongshu.com/explore/'+note,
          license='AURA原创配方（帖子风格参考）',sha256=hashlib.sha256(json.dumps(dict(note=note,recipe=item['recipe']),ensure_ascii=False,sort_keys=True).encode()).hexdigest())
        result.append(item)
    return result
