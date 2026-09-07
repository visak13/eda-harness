import sys
sys.dont_write_bytecode=True
from pathlib import Path
from PIL import Image
import json
from build_concepts import THEMES, contrast
root=Path(__file__).resolve().parent
checks=[]
for k,t in THEMES.items():
    ratios={name:round(contrast(t[name], '#FFFFFF'),2) for name in ('text','secondary','muted','brand','brand_hover','brand_active','control','link')}
    ratios.update({name+'_pair':round(contrast(t[name], t[name+'_bg']),2) for name in ('success','danger','progress','review')})
    assert all(v>=4.5 for n,v in ratios.items() if n!='control'),ratios
    assert ratios['control']>=3,ratios
    ratios['orange_on_selected']=round(contrast(t['brand'],t['tint']),2)
    assert ratios['orange_on_selected']>=4.5
    for color in ('text','secondary','muted','link'):
        assert contrast(t[color],t['panel'])>=4.5,(k,color)
    areas={}
    for p in ('inbox','epics','tiles'):
        im=Image.open(root/f'concept-{k}-{p}.png')
        assert im.size==((1200,900) if p=='tiles' else (1440,900))
        assert im.getpixel((1100,95))[:3]==(255,255,255) if p!='tiles' else True
        if p!='tiles':
            colors=im.convert('RGB').getcolors(im.width*im.height)
            orange=sum(n for n,(r,g,b) in colors if r>90 and r>g*1.6 and g>b*1.35 and r-b>60)
            areas[p]=round(100*orange/(im.width*im.height),3)
            assert areas[p]<2,(k,p,areas[p])
    checks.append({'concept':k,'contrast':ratios,'saturated_orange_area_percent':areas})
geometry=json.loads((root/'render-checks.json').read_text())
for item in geometry:
    assert item['documentWidth']==item['width']
    if 'lastRow' in item: assert item['lastRow']['bottom']<=900
    if 'composer' in item: assert item['composer']['right']==1136 and item['composer']['top']==786
    if 'tileFooter' in item: assert item['tileFooter']['bottom']<=900
for p in ('inbox','epics','tiles'):
    w=720 if p!='tiles' else 600
    h=450
    board=Image.new('RGB',(w*3,h),'white')
    for i,k in enumerate('ABC'):
        board.paste(Image.open(root/f'concept-{k}-{p}.png').resize((w,h)),(w*i,0))
    board.save(root/f'qa-{p}.jpg',quality=95)
(root/'contrast-checks.json').write_text(json.dumps(checks,indent=2))
print(json.dumps(checks,indent=2))
