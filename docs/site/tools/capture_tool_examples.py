"""Capture one real reply per board tool for the site's Reference -> MCP tools page (story s-bd0cf6288c).

Each tool is called through edp8.bundles.invoke, the same entry the MCP server uses, on the throwaway board the
product-guide specs seed with the made-up Tidewater project (v8/web/guide/demo.seed.ts). It never touches a real
board: v8/web/guide/tools.spec.ts starts it with a private home, a dead pool and no broker. Replies are clipped
for reading and scrubbed of the run's temp paths, then written to docs/site/tool-examples.json.

    python capture_tool_examples.py --board <url> --demo <demo.json> --home <board home> --out <json>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

LIST_MAX = 3
STR_MAX = 360

#: tools whose success needs something the sealed demo board doesn't have; the page shows the reply it gave instead
NOT_LIVE = {
    "spawn": "No pool runs beside the demo board, so this is the reply a seat gets while the pool is down.",
    "resume": "No pool runs beside the demo board, so this is the reply a seat gets while the pool is down.",
    "reap": "No pool runs beside the demo board, so this is the reply a seat gets while the pool is down.",
    "close_self": "No pool runs beside the demo board, so this is the reply a seat gets while the pool is down.",
    "topic_research": "The demo board has no internet access, so this is the reply when the fetch is blocked.",
    "topic_propose": "Proposals cite a page topic_research fetched; with no internet access the board refuses the source.",
    "harvest_cost": "The demo seats never ran a harness, so there is no session log to cost.",
    "teammate": "The demo board runs without sign-in tokens, and teammate needs an admin signed in with one.",
    "close": "The demo epic is still in progress, so the board refuses to close it.",
}

Step = tuple[str, str, Callable[[dict[str, Any]], dict[str, Any]]]


def plan() -> list[Step]:
    """(tool, who calls it, args from the context). Ordered: later steps use ids earlier replies returned."""
    eng = "seat:merge"
    return [
        # identity
        ("whoami", eng, lambda c: {}),
        ("preflight", "arch", lambda c: {}),
        ("subscribe", eng, lambda c: {}),
        ("resume_self", eng, lambda c: {}),
        ("context", eng, lambda c: {"ticket_id": c["stories"]["merge"]}),
        ("context_delta", eng, lambda c: {"ticket_id": c["stories"]["merge"], "cursor": c["cursor"]}),
        ("describe", eng, lambda c: {"type": "enum:TicketStatus"}),
        ("describe_objects", eng, lambda c: {}),
        ("get_guide", eng, lambda c: {}),
        # board and search
        ("board", "arch", lambda c: {"epic_id": c["epic"]}),
        ("events_query", "arch", lambda c: {"subject_id": c["epic"], "limit": 3}),
        ("participants", "arch", lambda c: {"role": "engineer", "limit": 3}),
        ("find", eng, lambda c: {"query": "tombstone", "k": 3, "epic_id": c["epic"]}),
        # tickets, criteria, requirements
        ("ticket_read", eng, lambda c: {"ticket_id": c["stories"]["merge"], "include": "criteria", "thread_limit": 1}),
        ("ticket_query", "arch", lambda c: {"epic_id": c["epic"], "kind": "story", "limit": 3}),
        ("ticket_create", "arch", lambda c: {"kind": "story", "work_type": "feature", "parent_id": c["epic"],
                                             "title": "S6 Sync status: show when a note is waiting to sync",
                                             "description": "A small badge on each note while its edits are queued offline."}),
        ("ticket_update", "arch", lambda c: {"ticket_id": c["s6"], "title": "S6 Sync badge: show when a note is waiting to sync"}),
        ("criterion_create", "arch", lambda c: {"ticket_id": c["s6"], "check": "look",
                                                "text": "A note with queued edits shows the badge until the queue drains."}),
        ("criterion_query", "arch", lambda c: {"ticket_id": c["s6"]}),
        ("criterion_update", "arch", lambda c: {"id": c["c6"],
                                                "text": "A note with queued offline edits shows the badge until they sync."}),
        ("requirements", "arch", lambda c: {"epic": c["epic"], "state": "open"}),
        ("requirement_link", "arch", lambda c: {"id": c["open_requirement"], "criterion": c["c6"]}),
        # thread and gates
        ("message_send", eng, lambda c: {"ticket_id": c["stories"]["merge"], "kind": "status",
                                         "text": "Merge handles a paragraph moved on one device and edited on the other. 44 tests pass."}),
        ("message_read", "maya", lambda c: {"id": c["question"]}),
        ("message_query", "arch", lambda c: {"ticket_id": c["epic"], "limit": 2}),
        ("gates", "arch", lambda c: {"ticket_id": c["epic"]}),
        ("gate_open", "arch", lambda c: {"ticket_id": c["epic"], "gate": "scope",
                                         "note": "S6 would be the ninth open story: can I raise the cap to nine?"}),
        ("gate_answer", "maya", lambda c: {"ticket_id": c["epic"], "gate": "scope", "answer": "approve"}),
        # docs and links
        ("doc_create", eng, lambda c: {"doc_type": "report", "scope": c["stories"]["merge"], "title": "S2 evidence: merge replay",
                                       "body_md": "# S2 evidence\n\nTwo devices, 200 offline edits each, replayed in both orders.\nNo paragraph lost.\n"}),
        ("doc_read", eng, lambda c: {"id": c["design"], "section": "### 3.1 Conflict rule"}),
        ("doc_query", eng, lambda c: {"scope": c["epic"], "limit": 3}),
        ("doc_update", eng, lambda c: {"id": c["d2"], "title": "S2 evidence: merge replay on two devices"}),
        ("doc_edit", eng, lambda c: {"id": c["d2"], "expected_version": c["d2_version"],
                                     "old_string": "No paragraph lost.",
                                     "new_string": "No paragraph lost; 3 conflicts surfaced, all same-paragraph."}),
        ("link_create", eng, lambda c: {"from_id": c["d2"], "to_id": c["stories"]["merge"], "relation": "evidence_for"}),
        ("link_query", eng, lambda c: {"to_id": c["stories"]["merge"], "limit": 3}),
        ("link_delete", eng, lambda c: {"id": c["link"]}),
        # attachments
        ("artifact_create", eng, lambda c: {"form": "url", "uri": "https://ci.example.com/tidewater/builds/412",
                                            "note": "CI run for the merge change", "ticket_id": c["stories"]["merge"]}),
        ("artifact_read", eng, lambda c: {"id": c["image_artifact"]}),
        ("artifact_upload", eng, lambda c: {"path": c["upload_path"], "note": "merge replay log"}),
        # knowledge
        ("record_decision", "arch", lambda c: {"scope": c["epic"], "text": "Merge per paragraph, never per note.",
                                               "detail": "Owner chose (b): a whole-note overwrite loses work by design.",
                                               "source": c["question"]}),
        ("set_binding", "arch", lambda c: {"decision_id": c["dec"], "binding": True, "reason": "Every story touches merge."}),
        ("record_claim", eng, lambda c: {"scope": c["stories"]["merge"], "basis": "measured",
                                         "text": "Paragraph merge of a 10,000-word note takes under 20 ms on a mid-range phone."}),
        ("withdraw_claim", eng, lambda c: {"claim_id": c["claim"], "reason": "Measured on a debug build; re-measuring on release."}),
        ("record_lesson", eng, lambda c: {"domain": "sync", "topic": "paragraph ids",
                                          "text": "Give a split paragraph two new ids, or the older device resurrects the original."}),
        ("retire_lesson", "arch", lambda c: {"lesson_id": c["lesson"], "reason": "The merge now handles splits itself."}),
        ("lookup", eng, lambda c: {"scope": c["epic"], "question": "what happens to a deleted paragraph"}),
        ("dense_search", eng, lambda c: {"scope": c["epic"], "question": "deleted paragraph comes back", "k": 3}),
        ("withdraw_decision", "arch", lambda c: {"decision_id": c["dec"], "reason": "Folded into the design's section 3.1."}),
        ("topic_research", "sme", lambda c: {"topic_id": c["topic"], "query": "offline sync"}),
        ("topic_propose", "sme", lambda c: {"topic_id": c["topic"], "title": "Offline sync patterns",
                                             "body_md": "# Offline sync patterns\n\nQueue, replay, merge per field.\n",
                                             "source_url": "https://example.com/offline-sync"}),
        # seats and the pool (no pool runs here: these show the reply a seat gets when it is down)
        ("inbox", "maya", lambda c: {}),
        ("record_status", eng, lambda c: {"status": "handed_off", "note": "S2 merge in review; evidence attached."}),
        ("session_query", "arch", lambda c: {"ticket_id": c["stories"]["merge"], "limit": 3}),
        ("spawn", "arch", lambda c: {"role": "engineer", "ticket_id": c["s6"]}),
        ("resume", "arch", lambda c: {"participant_id": c["seats"]["merge"]}),
        ("reap", "arch", lambda c: {"participant_id": c["seats"]["spike"]}),
        ("close_self", "seat:spike", lambda c: {}),
        # framework, help and admin
        ("pain", eng, lambda c: {"action": "file", "area": "mcp", "severity": "low",
                                 "symptom": "doc_read with a section name returns the whole doc when the heading has trailing spaces",
                                 "expected": "only that section", "workaround": "used offset and limit instead", "evidence": "doc_read(id=design-..., section='### 3.1 Conflict rule ') returned 1.3k chars"}),
        ("service_status", "maya", lambda c: {}),
        ("harvest_cost", "maya", lambda c: {"participant_id": c["seats"]["merge"]}),
        ("teammate", "maya", lambda c: {"action": "list"}),
        ("workflow", "maya", lambda c: {"action": "list"}),
        ("workflow_check", "doctor", lambda c: {"ref": "standard@1"}),
        ("why_stuck", "doctor", lambda c: {"ticket_id": c["stories"]["screen"]}),
        ("doctor_health", "doctor", lambda c: {}),
        ("doctor_pool", "doctor", lambda c: {}),
        ("doctor_feed_lag", "doctor", lambda c: {}),
        ("doctor_dead_mail", "doctor", lambda c: {}),
        ("doctor_pains", "doctor", lambda c: {}),
        ("doctor_logs", "doctor", lambda c: {"service": "board", "lines": 3}),
        ("propose_fix", "doctor", lambda c: {"topic_id": c["help_topic"], "effect": "Let four seats run at once so the queued S3 engineer can start.",
                                           "action": {"kind": "pool.set_limits", "max_live_shells": 4}}),
        ("close", "maya", lambda c: {"epic_id": c["epic"]}),
    ]


def learn(tool: str, reply: dict[str, Any], c: dict[str, Any]) -> None:
    """Keep the ids later steps need."""
    v = reply.get("value")
    if not reply.get("ok") or v is None:
        return
    if tool == "context":
        c["cursor"] = v.get("cursor")
    elif tool == "ticket_create":
        c["s6"] = v["id"]
    elif tool == "criterion_create":
        c["c6"] = v["id"]
    elif tool == "doc_create":
        c["d2"], c["d2_version"] = v["id"], v.get("version", 1)
    elif tool == "doc_update":
        c["d2_version"] = v.get("version", c.get("d2_version"))
    elif tool == "link_create":
        c["link"] = v["id"]
    elif tool == "record_decision":
        c.setdefault("dec", v["id"])
    elif tool == "record_claim":
        c["claim"] = v["id"]
    elif tool == "record_lesson":
        c["lesson"] = v["id"]


def clip(x: Any, depth: int = 0) -> Any:
    if isinstance(x, dict):
        return {k: clip(v, depth + 1) for k, v in x.items()}
    if isinstance(x, list):
        out = [clip(v, depth + 1) for v in x[:LIST_MAX]]
        if len(x) > LIST_MAX:
            out.append(f"… {len(x) - LIST_MAX} more")
        return out
    if isinstance(x, str) and len(x) > STR_MAX:
        return x[:STR_MAX] + "…"
    return x


def scrub(text: str, roots: list[str]) -> str:
    for r in sorted({r for r in roots if r}, key=len, reverse=True):
        for form in {r, r.replace("\\", "/"), r.replace("\\", "\\\\"), r.replace("/", "\\\\")}:
            text = text.replace(form, "<home>")
    text = re.sub(r"[A-Za-z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)[^\\/\"\s]+", "<user-dir>", text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--demo", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from edp8 import bundles
    from edp8.client import BoardClient

    demo = json.loads(Path(a.demo).read_text(encoding="utf-8"))
    who = {"arch": demo["seats"]["arch"], "qa": demo["seats"]["qa"], "maya": "maya"}
    for k, v in demo["seats"].items():
        who[f"seat:{k}"] = v
    ws = Path(tempfile.mkdtemp(prefix="tool-examples-"))
    log = ws / "merge-replay.log"
    log.write_text("replay 200x2 edits: 0 lost, 3 conflicts\n", encoding="utf-8")
    c: dict[str, Any] = dict(demo, upload_path=str(log))
    seed = BoardClient(base_url=a.board, participant=who["arch"])
    reqs = seed.requirements(demo["epic"], state="open").get("value", {}).get("requirements", [])
    c["open_requirement"] = reqs[0]["id"] if reqs else None
    msg = seed._request("GET", f"/v1/messages/{demo['attachmentMsg']}").get("value", {})
    c["image_artifact"] = (msg.get("artifacts") or [None])[0]

    # the Help thread (its doctor seat runs the diagnostics) and a Library topic (its sme seat researches)
    maya = BoardClient(base_url=a.board, participant="maya")
    help_out = maya._request("POST", "/v1/help", json={"text": "The S3 story has not moved since yesterday."})
    hv = help_out.get("value") or {}
    c["help_topic"] = (hv.get("topic") or {}).get("id")
    who["doctor"] = (hv.get("topic") or {}).get("assignee") or "maya"
    topic_out = maya._request("POST", "/v1/topics", json={"title": "Offline sync patterns", "seed_url": "https://example.com/offline-sync"})
    tv = topic_out.get("value") or {}
    c["topic"] = (tv.get("topic") or {}).get("id")
    who["sme"] = (tv.get("topic") or {}).get("assignee") or "maya"
    # close_self needs the seat's own status first
    bundles.set_client(BoardClient(base_url=a.board, participant=who["seat:spike"]))
    bundles.invoke(bundles.ALL_TOOLS["record_status"], {"status": "done", "note": "S5 report attached."}, seat=who["seat:spike"])

    examples: dict[str, Any] = {}
    for tool, caller, args_of in plan():
        args = args_of(c)
        client = BoardClient(base_url=a.board, participant=who[caller], workspace_root=ws)
        bundles.set_client(client)
        try:
            reply = bundles.invoke(bundles.ALL_TOOLS[tool], args, seat=who[caller])
        except Exception as e:  # noqa: BLE001 - a crash is recorded, never hidden
            reply = {"ok": False, "error": {"code": "capture_crash", "message": f"{type(e).__name__}: {e}"}}
        learn(tool, reply, c)
        role = caller.split(":")[0] if caller != "maya" else "owner"
        examples[tool] = {**({"note": NOT_LIVE[tool]} if tool in NOT_LIVE else {}), "caller": {"seat": "engineer", "arch": "architect", "doctor": "help seat"}.get(role, role), "args": args, "reply": clip(reply)}
        print(f"{tool:20} {'ok' if reply.get('ok') else 'ERR ' + json.dumps(reply.get('error'))[:140]}", flush=True)

    missing = sorted(set(bundles.ALL_TOOLS) - set(examples))
    if missing:
        print("not in the plan:", ", ".join(missing), file=sys.stderr)
    text = json.dumps({"_note": "Generated by docs/site/tools/capture_tool_examples.py on the made-up demo board; "
                                "do not edit by hand.", "tools": examples}, indent=1, ensure_ascii=False)
    text = scrub(text, [a.home, str(ws), str(Path(a.home).resolve()), tempfile.gettempdir()])
    for exe in {sys.executable, sys.executable.replace("\\", "/")}:
        text = text.replace(exe.replace("\\", "\\\\"), "<python>").replace(exe, "<python>")
    text = text.replace(a.board.rstrip("/"), "http://127.0.0.1:19400")
    Path(a.out).write_text(text + "\n", encoding="utf-8")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
