"""t-feb26a46d9 / t-cb431765fc: design review fit screenshots + overflow measures on a PRIVATE board.

    .venv/Scripts/python.exe scripts/reader_walk.py before|after

Seeds an epic with a long design doc (headings, a wide table, a long code line) as its design_ref, then
scripts/reader_walk.mjs shoots the design in its own tab (/ui/doc/<id>?source=<epic>) and in the pop-up
(the epic page's Design link) at four viewports, rail expanded and collapsed, and measures what overflows.
The board is scripts/adversary_repro.py's harness with its own tokens.json (EDP8_TOKENS); the fleet
v8/tokens.json mtime is checked before and after. Writes docs/evidence/s-adv/design-overflow/ (was s-sme-surface/reader/ for t-feb26a46d9).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

V8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(V8 / "scripts"))
import adversary_repro as H  # noqa: E402
from topic_walk import start_pool  # noqa: E402

OUT = V8 / "docs" / "evidence" / "s-adv" / "design-overflow"
OWNER_SECRET = "walk-owner-secret"
ARCH, ARCH_SECRET = "architect.reader", "walk-architect-secret"

SECTIONS = "\n\n".join(
    f"## {i}. Section {i}\n\nThe board keeps one record per decision; this section explains part {i} of the "
    f"design in enough prose to fill the reader column and make the outline worth having.\n\n"
    f"### {i}.1 Detail\n\n- a bullet about part {i}\n- another bullet about part {i}"
    for i in range(1, 9))
BODY = (
    "# Reader mode sample design\n\nA long design used to measure the review layout.\n\n"
    "| column one | column two | column three | column four | column five | column six |\n"
    "|---|---|---|---|---|---|\n"
    "| a fairly long cell value | another long cell value | third cell | fourth cell | fifth cell | sixth cell |\n\n"
    "```\n" + "a_long_code_line_without_breaks_" * 8 + "\n```\n\n" + SECTIONS)


def main(mode: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fleet = V8 / "tokens.json"
    fleet_mtime = fleet.stat().st_mtime if fleet.exists() else None
    home = Path(tempfile.mkdtemp(prefix="reader-walk-"))
    tokens = home / "tokens.json"
    tokens.write_text(json.dumps({"owner": OWNER_SECRET, "agents": {ARCH: ARCH_SECRET}}), encoding="utf-8")
    _pool, pool_url = start_pool()
    for k in H._STRIP:
        os.environ.pop(k, None)
    os.environ.update(EDP_POOL_URL=pool_url, EDP8_HOME=str(home), EDP8_TOKENS=str(tokens),
                      EDP8_PAIN_FILE=str(home / "pain-points.jsonl"))
    proc, base = H.start_board(home, pool_url)
    print(f"private board pid={proc.pid} {base} home={home}", flush=True)
    http = httpx.Client(base_url=base, timeout=60)
    owner = {"X-Participant": "owner", "X-Token": OWNER_SECRET}
    arch = {"X-Participant": ARCH, "X-Token": ARCH_SECRET}

    def call(headers: dict, method: str, path: str, **kw):
        body = http.request(method, path, headers=headers, **kw).json()
        assert body.get("ok"), (path, body)
        return body["value"]

    try:
        for pid, role, typ in [("owner", "owner", "human"), (ARCH, "architect", "agent")]:
            http.post("/v1/participants", headers={"X-Admin": H.ADMIN}, json={"id": pid, "handle": pid, "role": role, "type": typ})
        epic = call(owner, "POST", "/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Reader mode epic"})["id"]
        call(owner, "PATCH", f"/v1/tickets/{epic}", json={"assignee": ARCH})
        doc = call(arch, "POST", "/v1/docs", json={"doc_type": "design", "title": "Reader mode sample design",
                                                   "scope": epic, "body_md": BODY})["id"]
        call(arch, "PATCH", f"/v1/tickets/{epic}", json={"design_ref": doc})
        print(f"seeded epic={epic} design={doc}", flush=True)
        p = subprocess.run(["node", str(V8 / "scripts" / "reader_walk.mjs"), mode, base, str(OUT), epic, doc], cwd=str(V8),
                           env={**os.environ, "WALK_OWNER_TOKEN": OWNER_SECRET}, capture_output=True, text=True,
                           encoding="utf-8", timeout=300)
        out = (p.stdout + p.stderr).strip()
        print(out, flush=True)
        (OUT / f"measure-{mode}.txt").write_text(out + "\n", encoding="utf-8")
        if p.returncode:
            return p.returncode
    finally:
        proc.kill()
        after = fleet.stat().st_mtime if fleet.exists() else None
        print(f"fleet tokens.json mtime unchanged: {after == fleet_mtime}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "before"))
