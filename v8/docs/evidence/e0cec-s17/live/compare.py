"""Per-story chars read and judge scores: lab codex full-orig / full-pyr vs the S17 live run."""
import json, os, pathlib, sys
LAB = pathlib.Path(os.environ['LAB_ROOT'] + '/presults')
LIVE = pathlib.Path(__file__).parent / 'plans'  # the committed live calls and judge files
def chars(d, sid):
    f = d / f'{sid}.calls.jsonl'
    return sum(json.loads(x)['chars'] for x in f.read_text(encoding='utf-8').splitlines()) if f.exists() else None
def score(d, sid):
    f = d / f'{sid}.judge-claude.json'
    if not f.exists():
        return None
    g = json.loads(f.read_text(encoding='utf-8'))
    ok = lambda sec, good: sum(1 for x in g.get(sec, {}).values() if x['v'] == good)
    n = lambda sec: len(g.get(sec, {}))
    return f"{ok('must','present')}/{n('must')} {ok('must_not','ok')}/{n('must_not')} {ok('order','kept')}/{n('order')}"
rows, tot = [], {'orig': 0, 'pyr': 0, 'live': 0}
for sid in ['A1', 'A2', 'A3', 'B1', 'B2', 'B3']:
    e = sid[0]
    o, p = chars(LAB / f'p1-codex-full-{e}-orig', sid), chars(LAB / f'p1-codex-full-{e}-pyr', sid)
    l = chars(LIVE, sid)
    for k, v in (('orig', o), ('pyr', p), ('live', l)):
        tot[k] += v or 0
    rows.append((sid, o, p, l, score(LAB / f'p1-codex-full-{e}-orig', sid), score(LAB / f'p1-codex-full-{e}-pyr', sid),
                 score(LIVE, sid)))
print('| Story | lab full-orig | lab full-pyr | live | live vs orig | live vs pyr | score orig | score pyr | score live |')
print('|---|---:|---:|---:|---:|---:|---|---|---|')
pct = lambda a, b: f'{(a - b) / b * 100:+.0f}%' if a and b else '—'
for sid, o, p, l, so, sp, sl in rows:
    print(f'| {sid} | {o:,} | {p:,} | {l:,} | {pct(l, o)} | {pct(l, p)} | {so} | {sp} | {sl} |' if l else
          f'| {sid} | {o:,} | {p:,} | — | — | — | {so} | {sp} | — |')
print(f"| total | {tot['orig']:,} | {tot['pyr']:,} | {tot['live']:,} | {pct(tot['live'], tot['orig'])} | {pct(tot['live'], tot['pyr'])} | | | |")
