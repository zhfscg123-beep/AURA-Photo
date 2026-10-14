"""AURA's revised photographic looks; explicit fading is kept to retro film.

Black and white endpoints stay anchored in bright/clean styles. Channel
curves and selective colors distinguish looks without a blanket gray veil.
"""

CLEAN=[[0,0],[.10,.075],[.25,.245],[.5,.55],[.75,.79],[.93,.95],[1,1]]
NATURAL=[[0,0],[.12,.105],[.35,.375],[.65,.685],[.90,.915],[1,1]]
FILM=[[0,.008],[.12,.095],[.35,.36],[.65,.68],[.90,.93],[1,.99]]
DEEP=[[0,0],[.15,.105],[.38,.34],[.65,.70],[.9,.945],[1,1]]
WARM_R=[[0,0],[.2,.205],[.5,.515],[.8,.81],[1,1]]
WARM_B=[[0,0],[.2,.205],[.5,.485],[.8,.785],[1,1]]
COOL_R=[[0,0],[.2,.18],[.5,.485],[.8,.8],[1,1]]
COOL_B=[[0,0],[.2,.225],[.5,.515],[.8,.8],[1,1]]

def build(preset):
    return [
      preset('portrait-natural','自然人像','人像','干净肤色、自然明暗与轻微暖色；保留背景层次。',
        dict(contrast=4,highlights=-30,shadows=4,vibrance=8,skin_protect=20),{'橙':[0,-5,6],'红':[0,-3,2]}, {'rgb':NATURAL}),
      preset('portrait-cream','奶油柔肤','人像','柔暖亮部与细腻中间调；保留黑位，适合窗边和婚礼。',
        dict(contrast=2,highlights=-30,shadows=5,saturation=-4,clarity=-2,highlight_hue=70,highlight_color=5,skin_protect=25),{'橙':[-2,-5,7],'绿':[0,-10,0]}, {'rgb':NATURAL,'r':WARM_R,'b':WARM_B}),
      preset('portrait-clean','清透白皙','人像','清爽明亮肤色、干净白色与有层次的背景。',
        dict(contrast=6,shadows=3,highlights=-30,whites=2,blacks=-2,vibrance=8,skin_protect=20),{'橙':[-2,-8,9],'黄':[-4,-14,0],'蓝':[-6,-5,-2]}, {'rgb':CLEAN,'b':[[0,0],[.25,.252],[.65,.66],[1,1]]}),
      preset('portrait-warm','暖阳人像','人像','暖金高光、自然肤色与沉稳背景；适合逆光和傍晚。',
        dict(contrast=5,highlights=-30,shadows=4,blacks=-2,vibrance=6,highlight_hue=65,highlight_color=10,shadow_hue=220,shadow_color=3,skin_protect=28),{'橙':[-3,-4,5],'黄':[-7,-8,0]}, {'rgb':NATURAL,'r':WARM_R,'b':WARM_B}),
      preset('japan-air','日系清透','日系','自然明亮、干净肤色、背景有层次；保留清晰黑白端点。',
        dict(contrast=5,highlights=-30,shadows=3,whites=2,blacks=-2,saturation=-3,vibrance=9,clarity=1,dehaze=1,skin_protect=22),{'橙':[-2,-5,7],'黄':[-6,-12,1],'绿':[-12,-12,-3],'蓝':[-8,-5,-3]}, {'rgb':CLEAN}),
      preset('japan-sage','森系青绿','日系','青绿植被与暖肤色分离；保留叶片、树干和阴影层次。',
        dict(contrast=8,highlights=-30,shadows=3,whites=2,blacks=-3,saturation=-4,vibrance=5,clarity=2,dehaze=2,skin_protect=25),{'橙':[-2,-4,6],'黄':[12,-18,-2],'绿':[-22,-20,-6],'青':[-6,-12,-3],'蓝':[-8,-8,-4]}, {'rgb':CLEAN}),
      preset('japan-peach','蜜桃晴天','日系','浅蜜桃肤色、柔暖亮部与清爽绿色；适合花园和写真。',
        dict(contrast=4,highlights=-30,shadows=3,whites=2,blacks=-2,saturation=-3,vibrance=6,highlight_hue=55,highlight_color=6,skin_protect=22),{'橙':[-5,-6,8],'红':[-3,-3,3],'黄':[-8,-10,0],'绿':[-10,-16,-3]}, {'rgb':CLEAN,'r':WARM_R,'b':WARM_B}),
      preset('film-gold','金色胶片','胶片','金黄、暖红与收敛青绿；轻颗粒、扎实黑位的旅行胶片感。',
        dict(contrast=8,highlights=-30,shadows=5,saturation=-6,grain=9,grain_model=1,grain_size=2.5,highlight_hue=65,highlight_color=10,shadow_hue=210,shadow_color=5,skin_protect=22),{'红':[4,7,0],'橙':[-3,3,5],'黄':[-12,8,0],'绿':[15,-22,-5],'蓝':[-8,-15,-5]}, {'rgb':FILM,'r':WARM_R,'b':WARM_B}),
      preset('film-retro','复古褪色','胶片','明确的褪色雾面风格，低饱和与细颗粒；适合复古街拍。',
        dict(contrast=4,saturation=-20,highlights=-30,grain=14,grain_model=1,grain_size=2.5,shadow_hue=85,shadow_color=5,highlight_hue=60,highlight_color=6,skin_protect=18),{'绿':[15,-22,-4],'蓝':[-8,-15,0]}, {'rgb':[[0,.04],[.15,.145],[.5,.51],[.8,.81],[1,.98]],'r':WARM_R,'b':WARM_B}),
      preset('film-blue','冷调胶片','胶片','青蓝暗部、安静色彩与自然肤色；适合城市和雨天。',
        dict(contrast=7,saturation=-10,highlights=-30,shadows=3,grain=8,grain_model=1,grain_size=2.2,shadow_hue=220,shadow_color=11,highlight_hue=70,highlight_color=4,skin_protect=30),{'蓝':[-14,-12,-4],'青':[-6,-8,-2],'绿':[-12,-16,-5]}, {'rgb':FILM,'r':COOL_R,'b':COOL_B}),
      preset('film-amber','琥珀暮色','胶片','琥珀亮部与深暖色彩，保留暗部层次；适合夕阳和室内。',
        dict(contrast=10,highlights=-30,shadows=3,saturation=-8,grain=8,grain_model=1,grain_size=2.3,highlight_hue=65,highlight_color=13,shadow_hue=280,shadow_color=4,skin_protect=25),{'黄':[-15,-8,0],'绿':[15,-25,-6],'蓝':[-5,-18,-5]}, {'rgb':DEEP,'r':WARM_R,'b':WARM_B}),
      preset('cinema-teal','青橙电影','电影','青色环境与暖肤色分离，明确的电影色彩和扎实暗部。',
        dict(contrast=13,highlights=-30,shadows=3,saturation=-7,shadow_hue=205,shadow_color=18,midtone_hue=50,midtone_color=3,highlight_hue=55,highlight_color=12,vignette=-6,skin_protect=30),{'绿':[-38,-28,-6],'蓝':[-20,-16,-5],'橙':[-2,-3,5]}, {'rgb':DEEP,'r':COOL_R,'b':COOL_B}),
      preset('cinema-night','城市夜色','电影','蓝青阴影、霓虹色彩和自然肤色；适合夜景环境人像。',
        dict(contrast=13,highlights=-30,shadows=5,blacks=-3,vibrance=8,shadow_hue=240,shadow_color=16,highlight_hue=45,highlight_color=6,vignette=-5,skin_protect=35),{'蓝':[-15,6,-5],'青':[-8,8,-3],'洋红':[0,10,2],'绿':[-15,-20,-4]}, {'rgb':DEEP,'r':COOL_R,'b':COOL_B}),
      preset('cinema-muted','低饱和叙事','电影','收敛环境色彩、保留肤色与明暗层次；适合纪实写真。',
        dict(contrast=10,saturation=-18,highlights=-30,shadows=4,shadow_hue=220,shadow_color=8,highlight_hue=65,highlight_color=6,skin_protect=25),{'绿':[-12,-20,-5],'蓝':[-8,-15,-4],'橙':[0,2,4]}, {'rgb':DEEP}),
      preset('landscape-clear','通透风光','风光','干净的天空、植被与景物层次；适合晴天旅行。',
        dict(contrast=10,highlights=-30,shadows=5,vibrance=18,dehaze=5,clarity=4,blacks=-3,skin_protect=35),{'蓝':[-6,10,-6],'绿':[-5,5,-4]}, {'rgb':NATURAL}),
      preset('landscape-coast','晴空海岸','风光','清澈青蓝、明亮浅色与自然肤色；适合海边度假。',
        dict(contrast=6,highlights=-30,shadows=3,vibrance=10,blacks=-2,skin_protect=25),{'青':[-12,8,3],'蓝':[-18,8,-2],'黄':[-5,-14,0],'橙':[0,-4,5]}, {'rgb':CLEAN}),
      preset('landscape-autumn','秋日暖棕','风光','金黄暖棕与收敛绿蓝色，背景有深浅层次。',
        dict(contrast=8,highlights=-30,shadows=3,saturation=-5,highlight_hue=65,highlight_color=8,skin_protect=25),{'黄':[-25,3,0],'绿':[-45,-28,-6],'蓝':[-8,-18,-3]}, {'rgb':FILM,'r':WARM_R,'b':WARM_B}),
      preset('bw-soft','柔和黑白','黑白','明亮肤色、柔和中间调与完整黑白端点；适合肖像。',
        dict(bw=1,contrast=3,highlights=-30,shadows=4,skin_protect=0),points={'rgb':NATURAL},bw_mix={'橙':14,'红':5,'蓝':-10}),
      preset('bw-classic','经典黑白','黑白','深黑、清晰对比和立体层次；适合街拍与建筑。',
        dict(bw=1,contrast=14,highlights=-30,shadows=2,clarity=3,skin_protect=0),points={'rgb':DEEP},bw_mix={'橙':8,'蓝':-18,'绿':-4}),
      preset('bw-film','银盐颗粒','黑白','银盐灰阶、柔和高光与细颗粒；适合复古肖像。',
        dict(bw=1,contrast=8,highlights=-30,shadows=3,grain=18,grain_model=1,grain_size=2.5,skin_protect=0),points={'rgb':FILM},bw_mix={'橙':12,'蓝':-14}),
    ]
