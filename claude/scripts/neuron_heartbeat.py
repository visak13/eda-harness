"""External neuron driver — heartbeat + broker-wake for a NON-Claude neuron.

DESIGN-v7 follow-up (2026-07-12): the neuron role is "whatever process calls
reconcile/next_action over the edp-claude MCP server and exercises judgment in
between." A Claude Code neuron gets its cadence from CronCreate and its live
wakes from the Monitor tool; an external harness (e.g. an OpenAI-CLI neuron)
has neither, so THIS script supplies both from the outside:

A Claude neuron's observe() merges THREE wake planes; this driver covers
all three (v7, 2026-07-13 — it originally covered only the broker plane,
so a worker's emit_recipe_event flowback could never wake the neuron):

  * TIMER  — fire the neuron command every --heartbeat-secs (default 1800,
             the 30-min backstop band the pacing table already names);
  * BROKER WAKE — stream the broker's SSE feed for the recipe's inbox
             (GET /v1/events?recipient=<recipe_id>): question/answer/steer/
             plan_closed land here (≙ rx.broker(me));
  * FLOWBACK WAKE — tail the recipe's events.jsonl for the neuron's
             flowback kinds (learning / discovery / blocker /
             spec_learning_proposed / review_finding — ≙ rx.recipe_events);
  * POOL-DEAD WAKE — poll the pool's sessions for a shell of THIS recipe
             flipping to dead (≙ rx.pool(scope=me, states=['dead']));
  * NO OVERLAP — a tick that arrives while the neuron command is still
             running is coalesced into ONE pending re-fire (never a pile-up,
             never a drop: the re-fire drains whatever arrived meanwhile).

The neuron command is YOURS (--cmd): anything that runs one agent turn and
exits — e.g. an OpenAI CLI in exec mode resuming a session, with the standard
reconcile-loop prompt. The prompt is passed by replacing the literal token
{PROMPT} in --cmd, or appended as the last argument when the token is absent.

Usage (from eda-base3/claude):
  uv run python scripts/neuron_heartbeat.py \
      --recipe recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8 \
      --cmd "<your-agent-cli> exec --resume <session-id> {PROMPT}" \
      --heartbeat-secs 1800

Robustness contract: broker down => keep ticking on the timer and retry the
stream with backoff (the SSE plane is the accelerator, the timer is the
guarantee — the same primary/backstop split the in-framework roles use).
Ctrl-C exits cleanly. The script never parses the neuron's output; the
recipe store is the source of truth, exactly as with an in-framework neuron.
"""

import argparse
import os
import shlex
import subprocess
import sys
import threading
import time

import httpx

# The canonical reconcile-loop prompt (cadence.py) — the SAME contract a
# Claude neuron's cron fires. Kept as a literal here so the script has no
# package import requirement; if cadence.py ever rewords it, update this.
RECONCILE_PROMPT = (
    "call reconcile then next_action and obey wait_hint: if it says wait, "
    "end your turn. If you do not remember your recipe's grounding_epoch "
    "(fresh, resumed, or compacted session), pass reground=true to "
    "reconcile first and re-read the digest before acting.")

STREAM_RETRY_MIN_S = 5
STREAM_RETRY_MAX_S = 300


def build_command(cmd_template: str, prompt: str) -> list[str]:
    """The neuron command as argv. {PROMPT} in the template is replaced;
    absent, the prompt is appended as one final argument.

    WINDOWS SPLIT (2026-07-20, live finding): plain shlex POSIX mode
    treats backslash as an ESCAPE, so an unquoted registered cmd like
    `C:\\...\\python.exe ...` collapsed to `C:...python.exe` and every
    driver fire died WinError 2 — the neuron's armed cadence failed
    silently forever. On nt, split with quoting enabled but NO escape
    character: backslashes are path separators, quoted and unquoted
    paths both survive."""
    if os.name == "nt":
        lex = shlex.shlex(cmd_template, posix=True)
        lex.whitespace_split = True
        lex.escape = ""
        parts = list(lex)
    else:
        parts = shlex.split(cmd_template)
    if any("{PROMPT}" in p for p in parts):
        return [p.replace("{PROMPT}", prompt) for p in parts]
    return [*parts, prompt]


class NeuronTicker:
    """Serialized tick executor: at most ONE neuron turn at a time, with a
    single coalesced pending re-fire for wakes that arrive mid-turn."""

    def __init__(self, argv: list[str]):
        self.argv = argv
        self._lock = threading.Lock()
        self._running = False
        self._pending = False

    def fire(self, reason: str) -> None:
        with self._lock:
            if self._running:
                # coalesce: one pending re-fire drains everything that
                # arrived during the in-flight turn.
                self._pending = True
                print(f"[neuron-heartbeat] {reason}: turn in flight - "
                      "coalesced into one pending re-fire", flush=True)
                return
            self._running = True
        threading.Thread(target=self._run, args=(reason,),
                         daemon=True).start()

    def _run(self, reason: str) -> None:
        while True:
            print(f"[neuron-heartbeat] firing neuron turn ({reason})",
                  flush=True)
            try:
                proc = subprocess.run(self.argv)
                print(f"[neuron-heartbeat] neuron turn exited "
                      f"{proc.returncode}", flush=True)
            except Exception as e:  # noqa: BLE001 — a broken cmd must not
                # kill the driver; the next tick retries and the operator
                # sees why.
                print(f"[neuron-heartbeat] neuron command FAILED: {e}",
                      flush=True)
            with self._lock:
                if self._pending:
                    self._pending = False
                    reason = "pending re-fire"
                    continue
                self._running = False
                return


def stream_wakes(broker_url: str, recipient: str, ticker: NeuronTicker,
                 stop: threading.Event) -> None:
    """Follow the broker SSE feed for `recipient`; every delivered message
    fires a neuron turn. Reconnects with capped backoff - the timer thread
    is the guarantee while this plane is down.

    since_ts DISCIPLINE (2026-07-19, live finding): /v1/events with no
    `since_ts` REPLAYS THE WHOLE BACKLOG, so a fresh driver burst-fired
    real turns on OLD mail the moment it connected. The endpoint's own
    contract says the driver reconnects with the last since_ts it saw -
    implemented here: the first connect starts at NOW (the kickoff turn
    already drained history), and every delivered message advances the
    cursor by its own `ts`, so a reconnect never re-delivers."""
    import json
    from datetime import datetime, timezone
    backoff = STREAM_RETRY_MIN_S
    url = f"{broker_url.rstrip('/')}/v1/events"
    cursor = datetime.now(timezone.utc).isoformat()
    while not stop.is_set():
        try:
            with httpx.Client(timeout=None) as c, c.stream(
                    "GET", url,
                    params={"recipient": recipient,
                            "since_ts": cursor}) as r:
                r.raise_for_status()
                print(f"[neuron-heartbeat] SSE stream live for {recipient} "
                      f"(since {cursor})", flush=True)
                backoff = STREAM_RETRY_MIN_S
                for line in r.iter_lines():
                    if stop.is_set():
                        return
                    if line.startswith("data:") and line[5:].strip():
                        try:
                            ts = json.loads(line[5:]).get("ts")
                            if ts:
                                cursor = ts
                        except ValueError:
                            pass
                        ticker.fire("broker wake")
        except Exception as e:  # noqa: BLE001 — broker down/restarting
            print(f"[neuron-heartbeat] SSE stream down ({e}); retry in "
                  f"{backoff}s (timer backstop still active)", flush=True)
            if stop.wait(backoff):
                return
            backoff = min(backoff * 2, STREAM_RETRY_MAX_S)


_LIVE_STATES = {"comprehending", "planning", "executing", "reviewing"}


def autodetect_recipe() -> str:
    """The single LIVE recipe under .recipes/ — the neuron's inbox. Refuses
    (raises with the concrete list) when zero or several are live: the wake
    driver must never guess which recipe it keeps alive."""
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / ".recipes"
    live = []
    for rj in sorted(root.glob("*/recipe.json")):
        try:
            state = json.loads(rj.read_text(encoding="utf-8")).get("state")
        except (OSError, ValueError):
            continue
        if state in _LIVE_STATES:
            live.append((rj.parent.name, state))
    if len(live) == 1:
        return live[0][0]
    raise SystemExit(
        f"--auto found {len(live)} live recipe(s) {live} — pass --recipe "
        "<id> explicitly.")


#: rx.recipe_events kinds the NEURON wakes on — mirrors ROLE_WAKE_KINDS
#: ["neuron"]["recipe_events"] in edp_claude.reactive.runtime; kept literal
#: so this script stays import-free of the package.
FLOWBACK_WAKE_KINDS = frozenset({
    "learning", "discovery", "blocker",
    "spec_learning_proposed", "review_finding",
})


def watch_flowback(recipes_root, recipe_id: str, ticker: "NeuronTicker",
                   stop: threading.Event, poll_s: float = 3.0) -> None:
    """Tail <recipes_root>/<recipe_id>/events.jsonl; a NEW line of a
    flowback wake kind fires a neuron turn (≙ rx.recipe_events). Starts at
    the current end of file — history is the heartbeat's job, not a wake
    storm's. Rollup-safe: if the file shrinks (rollup rewrote it), restart
    from its new end rather than misreading offsets."""
    import json as _json
    from pathlib import Path
    path = Path(recipes_root) / recipe_id / "events.jsonl"
    pos = path.stat().st_size if path.exists() else 0
    while not stop.is_set():
        try:
            if path.exists():
                size = path.stat().st_size
                if size < pos:
                    pos = size          # rollup rewrote the file
                elif size > pos:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                    pos = size
                    for line in chunk.splitlines():
                        try:
                            kind = _json.loads(line).get("kind")
                        except ValueError:
                            continue
                        if kind in FLOWBACK_WAKE_KINDS:
                            ticker.fire(f"flowback:{kind}")
                            break       # one wake drains everything
        except OSError:
            pass                        # transient read race — next poll
        if stop.wait(poll_s):
            return


def watch_pool_dead(pool_url: str, recipe_id: str, ticker: "NeuronTicker",
                    stop: threading.Event, poll_s: float = 30.0) -> None:
    """Poll the pool's sessions; a shell of THIS recipe transitioning to
    dead fires a neuron turn (≙ rx.pool(scope=me, states=['dead'])). Only
    TRANSITIONS fire — a shell already dead at startup is reconcile's
    business, not a wake storm."""
    url = f"{pool_url.rstrip('/')}/v1/sessions"
    known_dead: set = set()
    primed = False
    while not stop.is_set():
        try:
            with httpx.Client(timeout=10) as c:
                body = c.get(url).json()
            rows = body.values() if isinstance(body, dict) else body
            dead_now = {
                s.get("handle") or sid
                for sid, s in (body.items() if isinstance(body, dict)
                               else enumerate(rows))
                if isinstance(s, dict)
                and str(s.get("handle", "")).startswith(recipe_id)
                and s.get("state") == "done"
            } if isinstance(body, (dict, list)) else set()
            fresh = dead_now - known_dead
            known_dead = dead_now
            if primed and fresh:
                ticker.fire(f"pool-dead:{sorted(fresh)[0]}")
            primed = True
        except Exception:
            pass                        # pool down — timer backstop holds
        if stop.wait(poll_s):
            return


def main() -> int:
    ap = argparse.ArgumentParser(
        description="heartbeat + broker/flowback/pool-dead wake driver "
                    "for an external neuron")
    ap.add_argument("--recipe", default=None,
                    help="recipe_id (== the neuron's broker inbox)")
    ap.add_argument("--auto", action="store_true",
                    help="auto-detect the single LIVE recipe under .recipes/")
    ap.add_argument("--cmd",
                    default=os.environ.get("EDP_NEURON_CMD") or None,
                    help="neuron command template; {PROMPT} is replaced "
                         "with the reconcile-loop prompt (else appended)")
    ap.add_argument("--broker-url", default="http://127.0.0.1:9300")
    ap.add_argument("--pool-url", default="http://127.0.0.1:9301")
    ap.add_argument("--recipes-root", default=None,
                    help="recipes dir (default: <claude>/.recipes)")
    ap.add_argument("--heartbeat-secs", type=float, default=1800,
                    help="timer backstop cadence (default 30 min)")
    ap.add_argument("--prompt", default=RECONCILE_PROMPT,
                    help="override the reconcile-loop prompt")
    ap.add_argument("--fire-on-start", action="store_true",
                    help="fire one neuron turn immediately on launch")
    args = ap.parse_args()
    if not args.recipe:
        if not args.auto:
            ap.error("pass --recipe <id> or --auto")
        args.recipe = autodetect_recipe()
        print(f"[neuron-heartbeat] auto-detected live recipe: {args.recipe}",
              flush=True)

    if not args.cmd:
        sys.exit("--cmd missing and EDP_NEURON_CMD unset - nothing to fire")
    argv = build_command(args.cmd, args.prompt)
    ticker = NeuronTicker(argv)
    stop = threading.Event()

    from pathlib import Path
    recipes_root = (Path(args.recipes_root) if args.recipes_root
                    else Path(__file__).resolve().parents[1] / ".recipes")

    threading.Thread(target=stream_wakes,
                     args=(args.broker_url, args.recipe, ticker, stop),
                     daemon=True).start()
    threading.Thread(target=watch_flowback,
                     args=(recipes_root, args.recipe, ticker, stop),
                     daemon=True).start()
    threading.Thread(target=watch_pool_dead,
                     args=(args.pool_url, args.recipe, ticker, stop),
                     daemon=True).start()

    print(f"[neuron-heartbeat] driving {args.recipe}: timer every "
          f"{args.heartbeat_secs:.0f}s + wakes: broker SSE "
          f"({args.broker_url}), flowback events ({recipes_root}), "
          f"pool-dead ({args.pool_url})", flush=True)
    try:
        if args.fire_on_start:
            ticker.fire("startup")
        while True:
            if stop.wait(args.heartbeat_secs):
                break
            ticker.fire("heartbeat")
    except KeyboardInterrupt:
        print("[neuron-heartbeat] stopping", flush=True)
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
