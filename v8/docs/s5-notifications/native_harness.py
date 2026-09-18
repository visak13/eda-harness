"""Opt-in isolated integrated-board native trial harness. Never opens a browser or prompts permission.
Run from v8 with .venv/Scripts/python.exe; Ctrl-C stops only this foreground server.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen


def call(origin, path, body, actor="owner"):
    request = Request(origin + path, data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json", "X-Participant": actor})
    with urlopen(request, timeout=15) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(result)
    return result["value"]


def serve(args):
    # Dedicated home/database, loopback only. No fixture tokens or credentials in URL/logs.
    with tempfile.TemporaryDirectory(prefix="edp8-s5-native-") as home:
        os.environ.update(EDP8_HOME=home, EDP8_DB=str(Path(home) / "board.db"),
                          EDP8_TOKENS=str(Path(home) / "tokens.json"), EDP8_EMBEDDER="none",
                          EDP8_UI="folio", EDP8_ADMIN_TOKEN="s5-isolated-only")
        from edp8.board import Board
        from edp8.store import Store
        from edp8.schemas import Role, TicketKind, WorkType
        from edp8.service import create_app
        from edp8 import broker_adapter
        import uvicorn
        # This disposable fixture must never publish to the fleet broker.
        broker_adapter.publish = lambda *a, **kw: True
        board = Board(Store(os.environ["EDP8_DB"]))
        owner = board.participant_create("human", Role.owner, "owner", id_="owner")
        board.participant_create("human", Role.owner, "other", id_="other")
        board.participant_create("agent", Role.architect, "arch", id_="arch")
        epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="S5 native integrated trial")
        manifest = {"origin": f"http://127.0.0.1:{args.port}", "epic": epic.id, "pid": os.getpid()}
        Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest), flush=True)
        print("After explicit owner consent, manually open origin + /ui/epic/ + epic + ?as=owner. No browser was opened.", flush=True)
        uvicorn.run(create_app(board), host="127.0.0.1", port=args.port, log_level="warning")


def emit(args):
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    origin = manifest["origin"]
    # Prevent accidental invocation against the shared fleet service or arbitrary host.
    from urllib.parse import urlparse
    parsed = urlparse(origin)
    if parsed.hostname != "127.0.0.1" or parsed.port in {9400, 9402, 9300, 9301}:
        raise ValueError("Only the isolated loopback fixture is allowed")
    if args.approval:
        epic = call(origin, "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": "Native approval trial"})
        doc = call(origin, "/v1/docs", {"doc_type": "design", "title": "Native test design", "scope": epic["id"], "body_md": "Synthetic design for exact request/viewer navigation."}, "arch")
        call(origin, "/v1/criteria", {"ticket_id": epic["id"], "text": "Native navigation", "check": "look"}, "arch")
        request = Request(origin + "/v1/tickets/" + epic["id"], method="PATCH", data=json.dumps({"design_ref": doc["id"]}).encode(), headers={"Content-Type": "application/json", "X-Participant": "arch"})
        with urlopen(request, timeout=15) as response:
            assert json.load(response)["ok"]
        event = call(origin, f"/v1/gates/{epic['id']}/design_signoff/open", {"note": "Synthetic native approval trial"}, "arch")
        print(json.dumps({"request": event["id"], "source": epic["id"], "kind": "approval"}))
    else:
        message = call(origin, "/v1/messages", {"ticket_id": manifest["epic"], "kind": "question", "to": "owner", "text": "Synthetic native question trial"}, "arch")
        print(json.dumps({"message": message["id"], "source": manifest["epic"], "kind": "question"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["serve", "emit"])
    parser.add_argument("--manifest", default="s5-native-local.json")
    parser.add_argument("--port", type=int, default=19485)
    parser.add_argument("--approval", action="store_true")
    args = parser.parse_args()
    if args.port in {9400, 9402, 9300, 9301}:
        parser.error("shared service ports are forbidden")
    (serve if args.mode == "serve" else emit)(args)
