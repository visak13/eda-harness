"""Render a real slice of kg.db to PNG with PIL (no graphviz dependency).

Two pictures (S13 slice 6):
  - one module slice:  render.py module src/edp8/slack_bridge.py  out.png
  - the epic top level: render.py epic                            out.png

Nodes are laid out in type layers (module -> ticket -> design_part/problem ->
decision/check/lesson/evidence), edges drawn with their relation label. The
node set and edges come straight from kg.db via walk(), so the picture is the
graph, not a hand drawing.
"""
from __future__ import annotations

import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

import db
import walk

# palette echoes the architect's reference diagram
COLORS = {
    "module": (240, 176, 96), "ticket": (140, 190, 235), "design_part": (150, 205, 150),
    "problem": (230, 200, 150), "decision": (245, 205, 110), "check": (140, 210, 190),
    "evidence": (240, 170, 200), "lesson": (150, 190, 235),
}
LAYER = {"module": 0, "ticket": 1, "problem": 2, "design_part": 2,
         "decision": 3, "check": 3, "lesson": 3, "evidence": 3}
BOX_W, BOX_H, H_GAP, V_GAP, MARGIN = 248, 104, 30, 150, 60


def _font(sz):
    for p in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def _slice(conn, start, limit=15):
    _, _, sel = walk.walk(start, conn=conn)
    sel = sel[:limit]
    ids = set(sel)
    nodes = {r["id"]: r for r in conn.execute(
        "SELECT * FROM node WHERE id IN (%s)" % ",".join("?" * len(ids)), tuple(ids))}
    edges = [(e["from_id"], e["to_id"], e["rel"]) for e in conn.execute(
        "SELECT from_id, to_id, rel FROM edge WHERE rel!='came_from' AND from_id IN (%s) AND to_id IN (%s)"
        % (",".join("?" * len(ids)), ",".join("?" * len(ids))), tuple(ids) + tuple(ids))]
    return [nodes[i] for i in sel if i in nodes], edges


def _epic_slice(conn, epic="epic-44a0576511"):
    """The epic's structural top level: problem -> its stories (part_of) + the
    epic design_part (must_follow render) + a few recent live decisions."""
    ids = [f"problem:{epic}"]
    ids += [r["id"] for r in conn.execute(
        "SELECT id FROM node WHERE type='ticket' ORDER BY created_at LIMIT 9")]
    ids += [r["id"] for r in conn.execute(
        "SELECT n.id FROM edge e JOIN node n ON n.id=e.from_id "
        "WHERE e.rel='must_follow' LIMIT 1")]  # the render must_follow target's source part
    ids += ["ref:revision3-clean"]
    ids += [r["id"] for r in conn.execute(
        "SELECT id FROM node WHERE type='decision' AND status='live' ORDER BY created_at DESC LIMIT 3")]
    ids = list(dict.fromkeys(ids))
    nodes = {r["id"]: r for r in conn.execute(
        "SELECT * FROM node WHERE id IN (%s)" % ",".join("?" * len(ids)), tuple(ids))}
    edges = [(e["from_id"], e["to_id"], e["rel"]) for e in conn.execute(
        "SELECT from_id, to_id, rel FROM edge WHERE rel!='came_from' AND from_id IN (%s) AND to_id IN (%s)"
        % (",".join("?" * len(ids)), ",".join("?" * len(ids))), tuple(ids) + tuple(ids))]
    return [nodes[i] for i in ids if i in nodes], edges


def render(conn, start, out, title, limit=15, epic_mode=False):
    nodes, edges = _epic_slice(conn) if epic_mode else _slice(conn, start, limit)
    layers = {}
    for n in nodes:
        layers.setdefault(LAYER.get(n["type"], 3), []).append(n)
    for L in layers.values():
        L.sort(key=lambda n: n["id"])
    nrows = max(layers) + 1 if layers else 1
    width = max(len(L) for L in layers.values()) if layers else 1
    W = MARGIN * 2 + width * (BOX_W + H_GAP)
    Ht = MARGIN * 2 + 60 + nrows * (BOX_H + V_GAP)
    img = Image.new("RGB", (W, Ht), (250, 244, 236))
    d = ImageDraw.Draw(img)
    f_title, f_tag, f_txt = _font(30), _font(14), _font(15)
    d.text((MARGIN, 20), title, fill=(150, 45, 30), font=f_title)

    pos = {}
    for L, row in sorted(layers.items()):
        y = MARGIN + 60 + L * (BOX_H + V_GAP)
        row_w = len(row) * (BOX_W + H_GAP) - H_GAP
        x0 = (W - row_w) // 2
        for i, n in enumerate(row):
            x = x0 + i * (BOX_W + H_GAP)
            pos[n["id"]] = (x + BOX_W // 2, y, x, y)
    # edges first (under boxes)
    for a, b, rel in edges:
        if a in pos and b in pos:
            ax, ay, _, _ = pos[a]; bx, by, _, _ = pos[b]
            d.line([(ax, ay + BOX_H // 2), (bx, by + BOX_H // 2)], fill=(190, 120, 90), width=2)
            mx, my = (ax + bx) // 2, (ay + by) // 2 + BOX_H // 2
            d.text((mx + 3, my - 8), rel, fill=(150, 90, 60), font=f_tag)
    # boxes
    for n in nodes:
        cx, y, x, _ = pos[n["id"]]
        col = COLORS.get(n["type"], (210, 210, 210))
        stale = n["type"] == "module" and False  # simple render: mark via label
        d.rectangle([x, y, x + BOX_W, y + BOX_H], fill=col, outline=(90, 70, 60), width=2)
        d.rectangle([x, y, x + BOX_W, y + 20], fill=tuple(max(0, c - 35) for c in col))
        d.text((x + 6, y + 3), n["type"].upper(), fill=(40, 30, 25), font=f_tag)
        txt = textwrap.fill(n["text"][:104], width=32)
        d.multiline_text((x + 6, y + 24), txt, fill=(20, 20, 20), font=f_txt, spacing=1)
    d.text((MARGIN, Ht - 34),
           "Real slice from kg.db via walk(). Boxes = nodes (one sentence). Arrows = typed edges.",
           fill=(110, 90, 80), font=f_tag)
    img.save(out)
    print(f"wrote {out}: {len(nodes)} nodes, {len(edges)} edges, {W}x{Ht}")


if __name__ == "__main__":
    conn = db.connect()
    mode = sys.argv[1] if len(sys.argv) > 1 else "epic"
    if mode == "module":
        start, out = sys.argv[2], sys.argv[3]
        render(conn, start, out, f"KG slice: module {start}", limit=15)
    else:
        out = sys.argv[2] if len(sys.argv) > 2 else "epic.png"
        render(conn, "epic-44a0576511", out, "KG slice: epic-44a0576511 (Board UI improvements) — top level",
               epic_mode=True)
