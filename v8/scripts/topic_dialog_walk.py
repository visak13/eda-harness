"""t-f5bf848f0f: the Open-topic pop-up beside the New-epic pop-up, on a PRIVATE board.

    .venv/Scripts/python.exe scripts/topic_dialog_walk.py before|after

scripts/topic_dialog_walk.mjs shoots both pop-ups (empty, filled, footer) at CSS 1684x875 (the owner's
1852x962 @110%) and 1280x800; `after` also opens a topic with two experts (one-time links) and lands on its
page. This script then pastes each epic shot and its topic twin side by side (compare-<mode>-<state>-<WxH>.png).
The board is scripts/adversary_repro.py's harness with its own tokens.json (EDP8_TOKENS) and a fake pool; the
fleet v8/tokens.json mtime is checked before and after. Writes docs/evidence/s-adv/topic-dialog/.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

V8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V8 / "scripts"))
import adversary_repro as H  # noqa: E402
from topic_walk import start_pool  # noqa: E402

OUT = V8 / "docs" / "evidence" / "s-adv" / "topic-dialog"
OWNER_SECRET = "walk-owner-secret"


def side_by_side(mode: str) -> list[str]:
    made = []
    for epic in sorted(OUT.glob(f"{mode}-epic-*.png")):
        twin = OUT / epic.name.replace("-epic-", "-topic-")
        if not twin.exists():
            continue
        a, b = Image.open(epic), Image.open(twin)
        gap, band = 16, 34
        c = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height) + band), "white")
        c.paste(a, (0, band))
        c.paste(b, (a.width + gap, band))
        d = ImageDraw.Draw(c)
        d.text((12, 10), "New epic (Epics -> New epic)", fill="black")
        d.text((a.width + gap + 12, 10), "Open topic (Library -> Topics -> Open topic)", fill="black")
        name = epic.name.replace(f"{mode}-epic-", f"compare-{mode}-")
        c.save(OUT / name)
        made.append(name)
    return made


def main(mode: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fleet = V8 / "tokens.json"
    fleet_mtime = fleet.stat().st_mtime if fleet.exists() else None
    home = Path(tempfile.mkdtemp(prefix="topic-dialog-walk-"))
    tokens = home / "tokens.json"
    tokens.write_text(json.dumps({"owner": OWNER_SECRET, "agents": {}}), encoding="utf-8")
    _pool, pool_url = start_pool()
    for k in H._STRIP:
        os.environ.pop(k, None)
    os.environ.update(EDP_POOL_URL=pool_url, EDP8_HOME=str(home), EDP8_TOKENS=str(tokens),
                      EDP8_PAIN_FILE=str(home / "pain-points.jsonl"))
    proc, base = H.start_board(home, pool_url)
    print(f"private board pid={proc.pid} {base} home={home}", flush=True)
    http = httpx.Client(base_url=base, timeout=60)
    try:
        http.post("/v1/participants", headers={"X-Admin": H.ADMIN},
                  json={"id": "owner", "handle": "owner", "role": "owner", "type": "human"})
        p = subprocess.run(["node", str(V8 / "scripts" / "topic_dialog_walk.mjs"), mode, base, str(OUT)], cwd=str(V8),
                           env={**os.environ, "WALK_OWNER_TOKEN": OWNER_SECRET}, capture_output=True, text=True,
                           encoding="utf-8", timeout=300)
        out = (p.stdout + p.stderr).strip()
        print(out, flush=True)
        made = side_by_side(mode)
        print(f"side by side: {', '.join(made)}", flush=True)
        (OUT / f"walk-{mode}.txt").write_text(out + "\n" + f"side by side: {', '.join(made)}\n", encoding="utf-8")
        if p.returncode:
            return p.returncode
    finally:
        proc.kill()
        after = fleet.stat().st_mtime if fleet.exists() else None
        print(f"fleet tokens.json mtime unchanged: {after == fleet_mtime}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "before"))
