"""Dependency-free cold checks; does not claim app behavior or visual acceptance."""
from pathlib import Path
import ast
import hashlib
import json
import xml.etree.ElementTree as ET
import build_final as a
ROOT=Path(__file__).resolve().parent
mapping=json.loads((ROOT/'runtime-mapping.json').read_text())
assert set(mapping['statuses'])=={'drafted','designed','signed_off','ready','in_progress','in_review','blocked','done','partial','dropped'}
assert len(set(mapping['statuses'].values()))==10
assert set(mapping['icons'])==set(a.PATHS)
assert set(mapping['bots'])==set(a.BOTS)
assert mapping['human_ids_preserved']==[f'human-{i:02}' for i in range(1,9)]
for family,expected,render in [('icons',a.PATHS,a.icon),('bots',a.BOTS,a.bot)]:
 for key in expected:
  text=(ROOT/family/f'{key}.svg').read_text().strip()
  assert text==render(key),(key,'geometry drift')
  svg=ET.fromstring(text)
  for node in svg.iter():
   assert node.tag.split('}')[-1] in {'svg','path','rect','circle','g','ellipse'}
   for attr,val in node.attrib.items():
    assert attr in {'viewBox','width','height','fill','stroke','stroke-width','stroke-linecap','stroke-linejoin','aria-hidden','focusable','role','aria-label','d','x','y','rx','ry','cx','cy','r','transform'},(key,attr)
    assert 'url(' not in val.lower() and 'http' not in val.lower()
  if family=='icons':
   assert svg.attrib['stroke']=='currentColor' and svg.attrib['viewBox']=='0 0 24 24'
  else:
   assert svg.attrib['viewBox']=='0 0 36 36'
# Preserve runtime human behavior without importing/serving the board.
backend=ROOT.parents[3]/'src/edp8/avatars.py'
module=ast.parse(backend.read_text(encoding='utf-8'))
names={'HUMAN_AVATAR_IDS','_HUMAN_NAMES','_HUMAN_COLORS','human_avatar_svg','avatar_id_for'}
fingerprints={}
for node in module.body:
 name=getattr(node,'name',None)
 if isinstance(node,ast.Assign):name=getattr(node.targets[0],'id',None)
 if name in names:fingerprints[name]=hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
assert fingerprints==json.loads((ROOT/'human-preservation.json').read_text()),'human runtime source changed; inspect, never auto-bless'
def luminance(hex):
 rgb=[int(hex[i:i+2],16)/255 for i in [1,3,5]]
 rgb=[v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in rgb]
 return sum(v*w for v,w in zip(rgb,[.2126,.7152,.0722]))
def ratio(x,y):
 lo,hi=sorted([luminance(x),luminance(y)])
 return (hi+.05)/(lo+.05)
for name,fg,bg in [('light','#29251f','#faf4e8'),('dark','#eeeae2','#171717'),('hc','#ffffff','#000000')]:
 score=ratio(fg,bg)
 assert score >= (7 if name=='hc' else 4.5)
 print(f'{name} specimen ink/ground contrast: {score:.2f}:1')
for role,color in a.COLORS.items():
 score=ratio('#FFF3D8',color)
 print(f'{role} spark/background: {score:.2f}:1')
 assert score>=3,(role,'motif contrast')
print('PASS: exhaustive state/geometry/safe SVG checks; human functions/constants unchanged; specimen pairs and spark contrast. NOT built-app or acceptance proof.')
