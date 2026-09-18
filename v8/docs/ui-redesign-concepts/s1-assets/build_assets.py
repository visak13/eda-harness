"""Deterministic manual vector adaptations of reference-art, not image generation.
Run from any directory: python docs/ui-redesign-concepts/s1-assets/build_assets.py
"""
from pathlib import Path
import json
import html

ROOT = Path(__file__).resolve().parent
# Explicit authored geometry, adapted from generated silhouettes; no raster tracing.
PATHS = {
    'decisions': 'M10 3Q12 1 14 3L21 10Q23 12 21 14L14 21Q12 23 10 21L3 14Q1 12 3 10ZM12 7v6m0 4h.01',
    'epics': 'M6 3h12q3 0 3 3v12q0 3-3 3H6q-3 0-3-3V6q0-3 3-3ZM7 8h.01M11 8h6M7 15h.01M11 15h6',
    'seats': 'M8 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM17 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM3 20v-4a5 5 0 0 1 10 0v4ZM14 12a5 5 0 0 1 8 4v4h-6',
    'library': 'M3 4h18v4H3ZM5 8v12h14V8M10 12h4',
    'find': 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM15 15l6 6',
    'add': 'M12 4v16M4 12h16', 'close': 'M5 5l14 14M19 5 5 19',
    'chevron': 'm5 9 7 7 7-7', 'copy': 'M8 7V3h13v14h-4M3 7h14v14H3Z',
    'external': 'M14 3h7v7M21 3 11 13M10 5H4v15h15v-6',
    'back': 'M20 12H4m7-7-7 7 7 7', 'forward': 'M4 12h16m-7-7 7 7-7 7',
    'history': 'M3 11a9 9 0 1 1 2 7M3 5v6h6M12 7v6l4 3',
    'files': 'M3 7q0-3 3-3h4l3 4h5q3 0 3 3v7q0 3-3 3H6q-3 0-3-3Z',
    'design': 'M5 3h9l5 5v13H5ZM14 3v6h5',
    'work': 'M3 14 6 5h12l3 9v6H3ZM3 14h5l2 3h4l2-3h5M9 10l2 2 4-4',
    'reply': 'm10 5-7 7 7 7M3 12h11q7 0 7 8',
    'expand': 'M14 3h7v7M21 3l-7 7M3 14v7h7M3 21l7-7',
    'collapse': 'M3 9h6V3M9 9 3 3M15 21v-6h6M15 15l6 6',
    'attach': 'm9 16 8-8a3 3 0 0 0-4-4L4 13a5 5 0 0 0 7 7l9-9M7 14l8-8',
    'mention': 'M16 8v7q4 3 5-3a9 9 0 1 0-4 8M16 9a5 5 0 1 0 0 6',
    'help': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM9 8q1-4 5-2t-1 6l-1 2m0 4h.01',
    'send': 'M3 10 21 3l-7 18-4-7ZM10 14 21 3M10 14v6l3-2',
    'preferences': 'M9 3h6l1 4 4 1 1 6-4 2-1 4-6 1-2-4-4-1-1-6 4-2ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
    'usage': 'M3 14h4v7H3ZM10 9h4v12h-4ZM17 3h4v18h-4Z',
    'refresh': 'M3 9a9 9 0 0 1 16-4l2 3M21 3v5h-5M21 15a9 9 0 0 1-16 4l-2-3M3 21v-5h5',
    'filter': 'M3 4h18l-7 9v8l-4-2v-6Z',
    'sort': 'M7 21V3m-4 4 4-4 4 4M17 3v18m-4-4 4 4 4-4',
    'edit': 'm3 21 2-7L16 3q2-2 5 1l-1 3L9 19ZM5 14l4 5M14 5l5 5',
    'check': 'm4 12 5 5L20 6',
    'warning': 'M10 4q2-3 4 0l8 15q1 2-2 2H4q-3 0-2-2ZM12 9v5m0 4h.01',
    'more': 'M5 12h.01M12 12h.01M19 12h.01',
    'download': 'M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5',
    'link': 'm9 15 6-6M9 7l3-3a5 5 0 0 1 8 6l-4 4M8 10l-4 4a5 5 0 0 0 7 7l4-4',
    'play': 'M6 3 21 12 6 21Z',
    'status-drafted': 'M12 21H4V3h10l4 4v3M14 3v5h4M7 8h3M7 12h5m0 5 7-7 3 3-7 7-4 1Z',
    'status-designed': 'M4 3v18h17ZM9 12v4h4Z',
    'status-signed_off': 'M12 2 15 4l4 1 1 4 2 3-2 3-1 4-4 1-3 2-3-2-4-1-1-4-2-3 2-3 1-4 4-1ZM7 12l3 3 7-7',
    'status-ready': 'M4 22V3q5-2 10 0h7l-3 5 3 5h-7q-5-2-10 0',
    'status-in_progress': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM12 6v7l4 2',
    'status-in_review': 'M2 12q10-15 20 0-10 15-20 0ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
    'status-blocked': 'M8 2h8l6 6v8l-6 6H8l-6-6V8ZM7 12h10',
    'status-done': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM7 12l3 3 7-7',
    'status-partial': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM12 2v20',
    'status-dropped': 'M5 3h14q2 0 2 2v14q0 2-2 2H5q-2 0-2-2V5q0-2 2-2ZM7 7l10 10M17 7 7 17',
}
STATES = {key.removeprefix('status-'): key for key in PATHS if key.startswith('status-')}
# Small flat robot portraits on a 36 grid. Color decorative only; contour/motif distinguish roles.
BOTS = {
 'owner': ('#EBC569', '<rect x="5" y="11" width="26" height="21" rx="6"/><path d="M18 11V5m0 0h7m-3 0v3"/>'),
 'coordinator': ('#8DC0B0', '<rect x="3" y="14" width="30" height="18" rx="6"/><path d="M7 14V6h22v8M18 6v8"/><circle cx="7" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="29" cy="6" r="2"/>'),
 'architect': ('#ECA78D', '<path d="M5 14h26v14q0 4-4 4H9q-4 0-4-4Z"/><path d="M2 14 18 2l16 12Z"/>'),
 'engineer': ('#BBB1D8', '<path d="m7 12-5 10 6 10h20l6-10-5-10M12 3v8q6 6 12 0V3l5 4v7q-11 12-22 0V7Z"/>'),
 'reviewer': ('#EEE6CC', '<circle cx="18" cy="19" r="14"/><circle cx="13" cy="20" r="7"/><path d="m8 25-4 5M18 5V2"/>'),
 'adversary': ('#83B5A5', '<path d="M4 6 18 11 32 6v19L18 34 4 25ZM4 12l14 6 14-6"/>'),
 'qa': ('#E8E3CF', '<rect x="3" y="11" width="30" height="21" rx="5"/><path d="m22 5 4 4 7-7"/>'),
 'sme': ('#EBC569', '<path d="M18 12q-6-6-15-4v24q9-2 15 2 6-4 15-2V8q-9-2-15 4ZM18 12v22"/>'),
 'consultant': ('#ECA78D', '<path d="M8 7h21q5 0 5 5v15q0 5-5 5H13l-8 3 2-6q-5 0-5-5V12q0-5 6-5Z"/>'),
 'system': ('#83B5A5', '<rect x="3" y="4" width="30" height="9" rx="4"/><rect x="3" y="16" width="30" height="17" rx="5"/><circle cx="18" cy="24" r="3"/>'),
 'unknown': ('#E8E3CF', '<rect x="3" y="4" width="30" height="29" rx="6" stroke-dasharray="4 4"/><path d="M14 12q1-5 6-3t-1 8l-1 3m0 5h.01"/>'),
}

def icon_body(key):
    fill = '<path d="M12 2a10 10 0 0 0 0 20Z" fill="currentColor" stroke="none"/>' if key == 'status-partial' else ''
    return fill + f'<path d="{PATHS[key]}"/>'

def icon_svg(key):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{icon_body(key)}</svg>'

def bot_svg(key):
    color, body = BOTS[key]
    eyes = '' if key in ('system', 'unknown') else '<circle cx="13" cy="23" r="1.8" fill="#242323" stroke="none"/><circle cx="23" cy="23" r="1.8" fill="#242323" stroke="none"/>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" width="36" height="36" role="img" aria-label="{key.title()} avatar"><g fill="{color}" stroke="#242323" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}{eyes}</g></svg>'

def main():
    for kind, values, renderer in [('icons', PATHS, icon_svg), ('bots', BOTS, bot_svg)]:
        (ROOT / kind).mkdir(exist_ok=True)
        for key in values:
            (ROOT / kind / f'{key}.svg').write_text(renderer(key) + '\n', encoding='utf-8')
    mapping = {'source_run': '20260918T092338Z-2fd0ecba', 'adaptation': 'Hand-authored vector adaptation, not generated SVG', 'icons': {k: f'icons/{k}.svg' for k in PATHS}, 'statuses': STATES, 'bots': {k: f'bots/{k}.svg' for k in BOTS}, 'preserve_humans': [f'human-{i:02}' for i in range(1, 9)]}
    (ROOT / 'runtime-mapping.json').write_text(json.dumps(mapping, indent=2) + '\n', encoding='utf-8')
    # Portable typed geometry module, copied/imported into runtime only by S2.
    (ROOT / 'icon-paths.ts').write_text('// Manual adaptations; generated deterministically by build_assets.py.\nexport const ICON_PATHS = ' + json.dumps(PATHS, indent=2) + ' as const;\nexport type IconName = keyof typeof ICON_PATHS;\nexport const STATUS_ICONS = ' + json.dumps(STATES, indent=2) + ' as const satisfies Record<string, IconName>;\nexport const ICON_FILLS: Partial<Record<IconName, string>> = {"status-partial": "M12 2a10 10 0 0 0 0 20Z"};\n', encoding='utf-8')
    panels = []
    for theme in ('light', 'dark', 'hc'):
        cells = ''.join(f'<div class="cell"><span>{html.escape(k)}</span><div class="sizes">' + ''.join(f'<span class="size s{s}">{icon_svg(k)}</span>' for s in (16,18,24)) + '</div></div>' for k in PATHS)
        bots = ''.join(f'<div class="cell"><span>{k}</span><div class="sizes">' + ''.join(f'<span class="size s{s}">{bot_svg(k)}</span>' for s in (16,18,24)) + '</div></div>' for k in BOTS)
        panels.append(f'<section class="{theme}"><h2>{theme}: controls / states / bot identities</h2><div class="grid">{cells}{bots}</div></section>')
    (ROOT / 'specimen.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>S1 asset specimens — not runtime app</title><style>
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui}h1,p{margin:20px}section{padding:20px}.light{background:#faf8f2;color:#242323}.dark{background:#17191e;color:#f3eee5}.hc{background:#000;color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.cell{min-height:80px;border:1px solid currentColor;border-radius:8px;padding:8px}.sizes{display:flex;align-items:center;gap:18px;margin-top:10px}.size{display:inline-flex}.size svg{width:100%;height:100%;overflow:visible}.s16{width:16px;height:16px}.s18{width:18px;height:18px}.s24{width:24px;height:24px}</style><h1>S1 vector adaptation specimens</h1><p>Reference specimen, NOT built-app evidence. Each row shows 16 / 18 / 24 CSS px. Text labels carry semantics. Bot colors are decorative. Runtime uses actual theme tokens, authenticated avatar fetch and role/model labels.</p>''' + ''.join(panels) + '</html>', encoding='utf-8')
    print(f'Wrote {len(PATHS)} control/state vectors, {len(BOTS)} bot vectors, mapping, typed geometry and specimen.')

if __name__ == '__main__':
    main()
