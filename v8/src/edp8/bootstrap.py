"""Register the default participants on a fresh board (idempotent)."""

from __future__ import annotations

import argparse
import sys

import httpx

DEFAULTS = [
    ("owner", "owner", "human"),
    ("coordinator", "coordinator", "agent"),
    ("architect", "architect", "agent"),
    ("sme", "sme", "agent"),
    ("engineer", "engineer", "agent"),
    ("reviewer", "reviewer", "agent"),
    ("qa", "qa", "agent"),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="http://127.0.0.1:9400")
    ap.add_argument("--admin", default="dev")
    ap.add_argument("--owner", default="owner")
    a = ap.parse_args(argv)
    made = []
    for pid, role, typ in DEFAULTS:
        handle = a.owner if role == "owner" else pid
        r = httpx.post(f"{a.board}/v1/participants", headers={"X-Admin": a.admin},
                       json={"id": pid, "role": role, "type": typ, "handle": handle}, timeout=10)
        if r.status_code == 200 and r.json().get("ok"):
            made.append(pid)
    sys.stdout.write(f"registered: {made or 'nothing new'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
