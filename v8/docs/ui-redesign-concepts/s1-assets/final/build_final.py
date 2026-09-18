"""Final candidate assets: agreed contextual semantics, not image-generated SVG.
S2 integrates only after architect/owner direction; no runtime files are edited here.
"""
from pathlib import Path
import importlib.util
import json
import re
import sys

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('historical_geometry', ROOT.parent / 'build_assets.py')
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
# Retain only conventional primitive controls, never rejected status/robot mappings.
PATHS = {k: v for k, v in legacy.PATHS.items() if not k.startswith('status-')}
PATHS.update({
 'epics': 'M6 7h15v14H6ZM17 7V3H3v14h3M10 12h7m-7 4h5',
 'work': 'M3 3h18v18H3ZM7 8h.01M11 8h6M7 12h.01M11 12h6M7 16h.01M11 16h4',
 'files': 'M3 8V5h7l3 3h8v12H3ZM3 11h18',
 'design': 'M5 2h9l5 5v15H5ZM14 2v6h5M8 12h8m-8 4h8',
 'history': 'M3 10a9 9 0 1 1 1 8M3 4v6h6M12 6v6l4 2',
 'review-request': 'M3 4h18v13H9l-6 4ZM7 8h10M7 12h7',
 'status-drafted': 'M11 21H4V3h12v7M7 7h5M7 11h3m2 5 7-7 3 3-7 7-4 1Z',
 'status-designed': 'M4 2h16v20H4ZM8 6h8M8 10h3v3H8ZM13 16h3v3h-3ZM9 13v4h4',
 'status-signed_off': 'M4 2h16v20H4ZM8 6h8m-9 8 3 3 7-7',
 'status-ready': 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z',
 'status-in_progress': 'M12 3a9 9 0 1 1-9 9M3.5 7h.01M7 3.5h.01',
 'status-in_review': 'M10 21H4V2h14v7M8 6h6M10 11h12v8h-7l-5 3ZM13 15h6',
 'status-blocked': 'M8 2h8l6 6v8l-6 6H8l-6-6V8ZM7 12h10',
 'status-done': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM7 12l3 3 7-7',
 'status-partial': 'm3 6 2 2 4-4M12 6h9M3 14h6v6H3ZM12 17h9',
 'status-dropped': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM5 19 19 5',
})
# Monoline all assets: deliberately no filled partial circle/progress percentage.
LABELS = {'drafted':'Drafted','designed':'Designed','signed_off':'Signed off','ready':'Ready','in_progress':'In progress','in_review':'In review','blocked':'Blocked','done':'Done','partial':'Partial','dropped':'Dropped'}
STATUS = {k: f'status-{k}' for k in LABELS}
COLORS = {'architect':'#5865F2','engineer':'#168B68','reviewer':'#8B5CF6','adversary':'#D95C5C','qa':'#168AAD','sme':'#AC7215','owner':'#7C3AED','coordinator':'#64748B'}


def icon(key):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="{PATHS[key]}"/></svg>'


def bot_body(key):
    if key in COLORS:
        # Familiar spark from existing avatar, quieter padding; remove conflicting costume/background motifs.
        spark = '<g fill="#FFF3D8">'
        for x,y,angle in [(18,11,0),(18,25,0),(12,14.5,-60),(24,21.5,-60),(24,14.5,60),(12,21.5,60)]:
            transform = f' transform="rotate({angle} {x} {y})"' if angle else ''
            spark += f'<ellipse cx="{x}" cy="{y}" rx="2.7" ry="5"{transform}/>'
        return f'<rect width="36" height="36" rx="8" fill="{COLORS[key]}"/>{spark}</g>'
    if key == 'consultant':
        return '<rect width="36" height="36" rx="8" fill="#172554"/><circle cx="18" cy="18" r="5" fill="#FBBF24"/><path d="M6 20c4-10 17-14 25-7M9 27c8 3 19-2 21-10" fill="none" stroke="#93C5FD" stroke-width="2" stroke-linecap="round"/><circle cx="29" cy="13" r="2" fill="#F7F5F8"/>'
    if key == 'system':
        return '<rect width="36" height="36" rx="8" fill="#30313A"/><rect x="8" y="7" width="20" height="6" rx="2" fill="#B8B3BE"/><rect x="8" y="16" width="20" height="6" rx="2" fill="#B8B3BE"/><rect x="8" y="25" width="20" height="5" rx="2" fill="#B8B3BE"/><path d="M11 19h4l2-3 3 7 2-4h3" fill="none" stroke="#36C5F0" stroke-width="1.8" stroke-linejoin="round"/>'
    return '<rect width="36" height="36" rx="8" fill="#30313A"/><path d="M13 12c0-7 13-7 12 0-1 5-7 4-7 10m0 5h.01" fill="none" stroke="#F7F5F8" stroke-width="2.5" stroke-linecap="round"/>'

BOTS = [*COLORS, 'consultant', 'system', 'unknown']
def avatar_label(key):
    # Existing runtime labels retained; visible participant/model text remains authoritative.
    return 'Board system' if key in ('system','unknown') else f'{key.title()} avatar'

def bot(key):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" width="36" height="36" role="img" aria-label="{avatar_label(key)}">{bot_body(key)}</svg>'


def main():
    for family, names, render in [('icons',PATHS,icon),('bots',BOTS,bot)]:
        (ROOT/family).mkdir(exist_ok=True)
        for key in names:
            (ROOT/family/f'{key}.svg').write_text(render(key)+'\n',encoding='utf-8')
    (ROOT/'icon-paths.ts').write_text('// Hand-authored contextual adaptations; not image-generated SVG.\nexport const ICON_PATHS = '+json.dumps(PATHS,indent=2)+' as const;\nexport type IconName = keyof typeof ICON_PATHS;\nexport const STATUS_ICONS = '+json.dumps(STATUS,indent=2)+' as const;\nexport const STATUS_LABELS = '+json.dumps(LABELS,indent=2)+' as const;\n',encoding='utf-8')
    (ROOT/'bot-templates.json').write_text(json.dumps({k:{'body':bot_body(k),'label':avatar_label(k)} for k in BOTS},indent=2)+'\n',encoding='utf-8')
    (ROOT/'runtime-mapping.json').write_text(json.dumps({'state':'candidate; internal direction agreed m-61dd21edf0, owner/QA not yet accepted','icons':{k:f'icons/{k}.svg' for k in PATHS},'statuses':STATUS,'status_labels':LABELS,'bots':{k:f'bots/{k}.svg' for k in BOTS},'human_ids_preserved':[f'human-{i:02}' for i in range(1,9)],'dispatch':'human first; otherwise consultant OR model contains gpt -> consultant; existing role -> same role; unknown -> system unknown. Text identity/model never inferred from illustration.','source':'See provenance.md; prior rejected sheet is historical, not approved source.'},indent=2)+'\n',encoding='utf-8')
    print(f'Final candidate: {len(PATHS)} functional/status glyphs, {len(BOTS)} continuity-first bot templates; runtime untouched.')

if __name__=='__main__':
    main()
