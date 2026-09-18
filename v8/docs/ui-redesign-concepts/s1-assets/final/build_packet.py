"""Render-ready contextual packet from agreed composition + final candidate geometry."""
from pathlib import Path
import re
import html
import build_final as assets
ROOT=Path(__file__).resolve().parent
source=(ROOT.parent/'contextual/sample.html').read_text(encoding='utf-8')
aliases={'epic':'epics','people':'seats','alert':'decisions','progress':'status-in_progress','doc':'design','clip':'attach','clock':'history','chev':'chevron','at':'mention','work-list':'work','file-folder':'files','past-events':'history'}
for symbol in re.findall(r'<symbol id="([^"]+)"',source):
    key=aliases.get(symbol,symbol)
    if key not in assets.PATHS:continue
    source=re.sub(rf'<symbol id="{re.escape(symbol)}"[^>]*>.*?</symbol>',lambda _:f'<symbol id="{symbol}" viewBox="0 0 24 24"><path d="{assets.PATHS[key]}"/></symbol>',source)
source=source.replace('src="../../specimen-architect.svg"','src="bots/architect.svg"')
source=source.replace('EXISTING AVATARS PRESERVED','HUMAN AVATARS PRESERVED · AGENT EMBLEM REFINED')
source=source.replace('The document opens Design; the folder collects Files &amp; evidence. History shows earlier events; Work opens the task list.','Here’s the revised design. The review stays beside the conversation; your feedback returns to this thread.')
source=source.replace('</style>','''
.work-context{display:none}.work-view .conversation{display:none}.work-view .work-context{display:block;flex:1;min-height:0;padding-top:16px}.work-context h2{margin:0 0 8px;font-size:20px}.work-context p{font-size:13px;margin-bottom:8px;color:inherit}.work-table{width:100%;border-collapse:collapse;font-size:14px}.work-table th{text-align:left;font-size:12px;color:inherit;font-weight:600}.work-table td,.work-table th{padding:5px 8px;border-bottom:1px solid #c7bfae}.work-table td:first-child{width:42%}.work-person{display:flex;align-items:center;gap:8px}.work-person img{width:24px;height:24px;border-radius:6px}.state-label{display:inline-flex;align-items:center;gap:7px;border:1px solid currentColor;border-radius:6px;padding:2px 6px;font-size:13px;white-space:nowrap}.state-label svg{width:16px;height:16px;flex-shrink:0}.work-table .muted{font-size:12px}body.dark .work-table td,body.dark .work-table th{border-color:#706a60}body.dark .work-table .muted{color:#c8c1b6}@media(max-width:600px){.work-table,.work-table tbody,.work-table tr,.work-table td{display:block}.work-table thead{display:none}.work-table td{border:0;padding:3px}.work-table td:first-child{width:auto;font-weight:600}.work-table tr{padding:8px 0;border-bottom:1px solid #c7bfae}.work-view .work-context{overflow:visible}}
</style>''')
titles=['Write accessibility brief','Map review workflow','Confirm theme plan','Wire title field','Refine document viewer','Review attachment handling','Resolve provider access','Preserve human selections','Migrate historical links','Retire old exploration']
roles=['owner','architect','reviewer','engineer','engineer','qa','coordinator','qa','sme','adversary']
rows=[]
for (state,label),title,role in zip(assets.LABELS.items(),titles,roles):
    rows.append(f'<tr><td>{title}</td><td><span class="state-label">{assets.icon(assets.STATUS[state])}{label}</span></td><td><span class="work-person"><img src="bots/{role}.svg" alt=""><span>{role}<span class="muted"> · role label</span></span></span></td></tr>')
work='<section class="work-context"><h2>Work <span style="font-size:13px;font-weight:400">Linked tasks</span></h2><p>Synthetic work records for status/identity inspection. These words are stored states, not inferred progress.</p><table class="work-table"><thead><tr><th>Task</th><th>Status</th><th>Assigned</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></section>'
source=source.replace('<div class="composer"><div class="composer-top">',work+'<div class="composer"><div class="composer-top">',1)
(ROOT/'packet.html').write_text(source,encoding='utf-8')
# Appendix for cold QA size/theme inspection, secondary to contextual packet.
sections=[]
for theme in ['light','dark','hc']:
    cells=[]
    for key in assets.PATHS:
        cells.append('<div class="cell">'+html.escape(key)+'<div class="sizes">'+''.join(f'<span style="width:{s}px;height:{s}px">{assets.icon(key)}</span>' for s in [16,18,24])+'</div></div>')
    for key in assets.BOTS:
        cells.append('<div class="cell">'+key+'<div class="sizes">'+''.join(f'<span style="width:{s}px;height:{s}px">{assets.bot(key)}</span>' for s in [16,18,24])+'</div></div>')
    sections.append(f'<section class="{theme}"><h2>{theme} — final candidate size appendix</h2><div class="grid">'+''.join(cells)+'</div></section>')
(ROOT/'sizes.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Final candidate size appendix (not application)</title><style>*{box-sizing:border-box}body{margin:0;font:13px/1.5 system-ui}.light{background:#faf4e8;color:#29251f}.dark{background:#171717;color:#eeeae2}.hc{background:#000;color:#fff}section{padding:20px}.grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px}.cell{border:1px solid currentColor;border-radius:6px;padding:8px;min-height:76px}.sizes{display:flex;gap:18px;align-items:center;margin-top:8px}.sizes span{display:inline-flex}.sizes svg{width:100%;height:100%}</style>'''+''.join(sections)+'</html>',encoding='utf-8')
print('Wrote packet.html (epic/review/Work contexts) and secondary sizes appendix.')
