"""edp8 slack bridge — the doorbell: broker inbox growth → a Slack ping. No LLM, no tokens.

Config `slack_map.json` at the agent home (EDP8_SLACK_MAP overrides the path):

    {
      "board_url": "http://<host-tailnet-ip>:9400",     // used in the deep link
      "webhook_url": "https://hooks.slack.com/...",     // default: one channel for everyone
      "bot_token": "xoxb-...",                          // optional: enables DMs via chat.postMessage
      "people": {
        "x":     {"slack_id": "U0123456", "quiet": [22, 7]},   // DM if bot_token, else webhook mention
        "aksou": {"webhook_url": "https://hooks.slack.com/other", "quiet": null}
      }
    }

One thread per person tails the broker's SSE stream for their handle (starting at "now" — the
inbox file is append-only history). Each new message posts one Slack line with a deep link to
/ui/me. `quiet: [start_hour, end_hour)` (host-local) buffers pings and flushes them after the
quiet window — the +12h teammate sleeps uninterrupted and wakes to the batch.

Replies happen on the board (/ui/me), never in Slack: inbound Slack callbacks would need a
public HTTPS endpoint, which the tailnet deliberately avoids.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx

log = logging.getLogger("edp8.slack")

BROKER = os.environ.get("EDP_BROKER_URL", "http://127.0.0.1:9300")


def _config() -> dict:
    f = Path(os.environ.get("EDP8_SLACK_MAP",
                            str(Path(os.environ.get("EDP8_HOME", ".")) / "slack_map.json")))
    return json.loads(f.read_text(encoding="utf-8"))


def _in_quiet(quiet: list | None, now_hour: int) -> bool:
    if not quiet:
        return False
    start, end = int(quiet[0]), int(quiet[1])
    return (start <= now_hour or now_hour < end) if start > end else (start <= now_hour < end)


def _post(cfg: dict, person: dict, text: str) -> bool:
    token = cfg.get("bot_token")
    if token and person.get("slack_id"):
        r = httpx.post("https://slack.com/api/chat.postMessage",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"channel": person["slack_id"], "text": text}, timeout=15)
        ok = r.status_code < 400 and r.json().get("ok", False)
    else:
        hook = person.get("webhook_url") or cfg.get("webhook_url")
        if not hook:
            log.warning("no webhook/bot_token for a ping; dropped")
            return False
        mention = f"<@{person['slack_id']}> " if person.get("slack_id") else ""
        r = httpx.post(hook, json={"text": mention + text}, timeout=15)
        ok = r.status_code < 400
    if not ok:
        log.warning("slack post failed: %s %s", r.status_code, r.text[:200])
    return ok


def _line(cfg: dict, handle: str, msg: dict) -> str:
    body = msg.get("body") or {}
    ticket = body.get("ticket_id") or ""
    text = (body.get("text") or body.get("note") or body.get("answer")
            or json.dumps(body)[:120])
    link = f"{cfg.get('board_url', 'http://127.0.0.1:9400')}/ui/me?as={handle}"
    return (f"*{handle}* ← {msg.get('from')} ({msg.get('kind')})"
            + (f" on `{ticket}`" if ticket else "") + f": {str(text)[:140]}\n→ {link}")


def _watch(cfg: dict, handle: str, person: dict, stop: threading.Event) -> None:
    seen: set[str] = set()
    held: list[str] = []
    since = datetime.now().astimezone().isoformat()
    while not stop.is_set():
        try:
            with httpx.Client(timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10)) as c:
                with c.stream("GET", f"{BROKER}/v1/events",
                              params={"recipient": handle, "since_ts": since}) as resp:
                    resp.raise_for_status()
                    for raw in resp.iter_lines():
                        if stop.is_set():
                            return
                        # flush the quiet-hours buffer as soon as the window ends
                        if held and not _in_quiet(person.get("quiet"), datetime.now().hour):
                            if _post(cfg, person, "\n\n".join(held)):
                                held.clear()
                        if not raw.startswith("data: "):
                            continue
                        try:
                            msg = json.loads(raw[len("data: "):])
                        except json.JSONDecodeError:
                            continue
                        since = msg.get("ts", since)
                        mid = msg.get("msg_id")
                        if not mid or mid in seen:
                            continue
                        seen.add(mid)
                        line = _line(cfg, handle, msg)
                        if _in_quiet(person.get("quiet"), datetime.now().hour):
                            held.append(line)
                        else:
                            _post(cfg, person, line)
        except Exception as e:
            log.warning("watch %s: %s; reconnecting", handle, e)
            time.sleep(5)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    cfg = _config()
    stop = threading.Event()
    people = cfg.get("people") or {}
    if not people:
        raise SystemExit("slack_map.json has no people; nothing to watch")
    for handle, person in people.items():
        threading.Thread(target=_watch, args=(cfg, handle, person, stop),
                         name=f"slack-{handle}", daemon=True).start()
    log.info("slack bridge up: watching %s", ", ".join(people))
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    run()
