"""Cold, dependency-free asset inventory/security/provenance/determinism checks."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import build_assets as build

root = Path(__file__).resolve().parent
mapping = json.loads((root / 'runtime-mapping.json').read_text())
expected_states = {'drafted', 'designed', 'signed_off', 'ready', 'in_progress', 'in_review', 'blocked', 'done', 'partial', 'dropped'}
assert set(mapping['statuses']) == expected_states
assert len(mapping['icons']) == 45
assert len(mapping['bots']) == 11
assert mapping['preserve_humans'] == [f'human-{n:02}' for n in range(1, 9)]
assert {'decisions', 'epics', 'seats', 'library', 'find', 'add', 'close', 'chevron', 'copy', 'external'} <= mapping['icons'].keys()
allowed_tags = {'svg', 'g', 'path', 'rect', 'circle'}
allowed_attrs = {'xmlns', 'viewBox', 'width', 'height', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'aria-hidden', 'role', 'aria-label', 'd', 'x', 'y', 'rx', 'cx', 'cy', 'r', 'stroke-dasharray'}
for family in ('icons', 'bots'):
    for name, relative in mapping[family].items():
        path = root / relative
        text = path.read_text()
        assert text.strip() == (build.icon_svg(name) if family == 'icons' else build.bot_svg(name)), f'drift: {name}'
        svg = ET.fromstring(text)
        for el in svg.iter():
            assert el.tag.split('}')[-1] in allowed_tags, name
            assert set(el.attrib) <= allowed_attrs, (name, el.attrib)
            assert all('url(' not in val.lower() for val in el.attrib.values()), name
        assert svg.attrib['viewBox'] == ('0 0 24 24' if family == 'icons' else '0 0 36 36')
        if family == 'icons':
            assert svg.attrib['stroke'] == 'currentColor'
            assert svg.attrib['stroke-width'] == '2'
            assert svg.attrib['aria-hidden'] == 'true'
        else:
            assert svg.attrib['aria-label'] == f'{name.title()} avatar'
assert set(mapping['statuses'].values()) <= mapping['icons'].keys()
assert len(set(mapping['statuses'].values())) == 10
png = root / 'reference-art/board-family-contact-sheet.png'
assert png.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
print('PASS: 45 glyphs, 11 identities, ten exhaustive distinct status mappings, human IDs, XML allowlist, safe local geometry and deterministic vector outputs.')
print('Generated source SHA256:', hashlib.sha256(png.read_bytes()).hexdigest())
print('NOT CHECKED: built app, theme contrast pairs, human runtime dispatch or owner visual acceptance.')
