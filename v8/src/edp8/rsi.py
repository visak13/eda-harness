"""edp8 RSI phase 1 — a self-triggered retrieval regression tripwire (report-9a85d0418e §9, story S18).

    python -m edp8.rsi tick [--dry-run] [--force] [--db PATH] [--manifest PATH]

One `tick()` decides whether the corpus (T1) or the loaded retrieval code (T2) changed since the last
CONSUMED trigger, and if so replays every question of the tracked exam manifest (tests/rsi/manifest.json)
through the seat's own lookup (knowledge.wired_lookup) under the incumbent policy p-0, with the freshness
clock pinned to the last passing run. A required record id that the last pass found and this run does not
is a regression: the run is `regressed` and ONE kind=finding goes to the architect named in the manifest.

F0 is EVIDENCE PRESENCE, not correctness (§2): it cannot see negation or a wrong answer.

Boundaries (§9 c4/c5/c6):
- fail closed: a missing/malformed manifest or exam, or a lookup exception, is verdict=error (a stale
  process, low RAM or a warming/lost dense index is a hold) — never `pass`, and the trigger stays pending;
- writes: only the policy / rsi_run / rsi_state rows and the one finding message (+ its feed event);
  no record writes, no claims, no knob changes; exam files and exam.py are only ever READ;
- no generative calls: lookups embed the query at most; nothing here spawns, consults or shells out.
Server-side role enforcement of these boundaries is phase 3 and is NOT claimed here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import knowledge
from .schemas import (EventKind, Message, MessageKind, Participant, Policy, Role, RsiRun, RsiState,
                      Ticket, now)
from .store import Store, new_id

_log = logging.getLogger("edp8.rsi")

V8_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = V8_ROOT / "tests" / "rsi" / "manifest.json"
STATE_ID = "rsi-state"
P0 = "p-0"
DEBOUNCE_ROWS = 20                      # §3 T1: fire when >= 20 rows differ ...
DEBOUNCE_AGE = timedelta(hours=24)      # ... or the last consumed run is older than 24 h
LEASE = timedelta(minutes=15)           # single-flight lease; a crashed tick frees it after this
RAM_FLOOR_MB = int(os.environ.get("EDP8_RSI_RAM_FLOOR_MB", "1500"))
INTERVAL_S = float(os.environ.get("EDP8_RSI_INTERVAL_S", "900"))
FIRST_WAIT_S = 60.0                     # let the board listen and the index hydrate before the first tick
CODE_MODULES = ("knowledge", "search", "store", "exam")  # §3 T2: the retrieval code a regression lives in
REQUIRED_FIELDS = ("expected_ids", "required_ids")
# the unpersisted identity the finding is sent as (no participant row is written)
ACTOR = Participant(id="rsi", type="agent", role=Role.consultant, handle="rsi", created_by="rsi")


class RsiError(Exception):
    """A fail-closed condition: the run is verdict=error and the trigger stays pending."""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _jsha(obj: Any) -> str:
    return _sha(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))


# ----------------------------------------------------------------------------- T2: loaded-code identity
def module_files() -> dict[str, Path]:
    """The source files of CODE_MODULES, located without importing any of them."""
    out: dict[str, Path] = {}
    for name in CODE_MODULES:
        mod = sys.modules.get(f"edp8.{name}")
        origin = getattr(mod, "__file__", None) if mod else None
        if origin is None:
            spec = importlib.util.find_spec(f"edp8.{name}")
            origin = spec.origin if spec else None
        if origin:
            out[f"{name}.py"] = Path(origin)
    return out


class CodeIdentity:
    """sha256 of each retrieval source file AS THIS PROCESS EXECUTED IT: every module records its own
    SOURCE_SHA256 while it loads; a module this process never imported (exam.py in the board) is hashed
    from disk. `stale()` names files whose bytes on disk now differ: the running process no longer serves
    what is on disk, so a run would measure the wrong code. `loaded=None` hashes `files` now (a fresh import)."""

    def __init__(self, files: dict[str, Path] | None = None, loaded: dict[str, str] | None = None):
        self.files = dict(files if files is not None else module_files())
        self.loaded = dict(sorted(loaded.items())) if loaded is not None else \
            {n: _sha(p.read_bytes()) for n, p in sorted(self.files.items())}

    @classmethod
    def from_process(cls) -> "CodeIdentity":
        files = module_files()
        loaded = {}
        for n, p in files.items():
            mod = sys.modules.get(f"edp8.{n[:-3]}")
            loaded[n] = getattr(mod, "SOURCE_SHA256", None) or _sha(p.read_bytes())
        return cls(files, loaded)

    def code_hash(self) -> str:
        return _jsha(self.loaded)

    def stale(self) -> list[str]:
        out = []
        for n, p in sorted(self.files.items()):
            try:
                if _sha(p.read_bytes()) != self.loaded[n]:
                    out.append(n)
            except OSError:
                out.append(n)
        return out


LOADED = CodeIdentity.from_process()


# ----------------------------------------------------------------------------- T1: corpus fingerprint
def corpus_rows(store: Any) -> dict[str, str]:
    """One short hash per knowledge row: EVERY field of every decision, claim and lesson, live or retired
    (status, binding, text, detail, scope, domains, dates, evidence, counters — anything lookup may read),
    plus every kglink (kind, ends) — so an addition, a withdrawal, a count-preserving replacement, a
    re-link or a re-dated/re-domained record each change the fingerprint (§3 T1, widened by the second
    opinion: a domains edit changed a pack while a narrower fingerprint stayed equal)."""
    rows: dict[str, str] = {}
    for rtype in knowledge.RECORD_TYPES:
        for r in store.query(rtype, limit=10_000_000):
            rows[f"{rtype}:{r.id}"] = _jsha(r.model_dump(mode="json"))[:16]
    for lk in store.query("kglink", limit=10_000_000):
        rows[f"kglink:{lk.id}"] = _jsha([lk.kind, lk.from_id, lk.to_id])[:16]
    return rows


def fingerprint(rows: dict[str, str]) -> str:
    return _jsha(rows)


def rows_changed(old: dict[str, str], new: dict[str, str]) -> int:
    return sum(1 for k in set(old) | set(new) if old.get(k) != new.get(k))


# ----------------------------------------------------------------------------- policy p-0
def p0_knobs() -> dict[str, Any]:
    """The incumbent policy = the retrieval constants knowledge.py runs with today."""
    k = knowledge
    return {"rrf_k": 60, "leg_min": k.SEED_TOP, "leg_max": k.SEED_TOP_CAP, "leg_div": k.SEED_SCALE_DIV,
            "hops": k.MAX_HOPS, "link_w": dict(k.LINK_WEIGHT), "default_w": k.DEFAULT_WEIGHT,
            "co_source_w": k.CO_SOURCE_WEIGHT, "fresh_days": 30, "noise_floor": k.RANKED_FLOOR_FRAC,
            "lesson_cap": k.MAX_LESSONS, "max_bytes": k.MAX_BYTES}


def ensure_p0(store: Any) -> bool:
    """Bootstrap the one incumbent p-0 once (boot calls this on every start). True when it wrote it."""
    with store.transaction(immediate=True):
        if store.get("policy", P0) is not None or store.query("policy", {"status": "incumbent"}, limit=1):
            return False
        store.put("policy", Policy(id=P0, status="incumbent", knobs=p0_knobs(), proposed_by="rsi",
                                   created_by="rsi", rationale="phase-1 bootstrap: knowledge.py constants"))
    return True


# ----------------------------------------------------------------------------- state + lease
def _state(store: Any) -> RsiState:
    st = store.get("rsi_state", STATE_ID)
    return st if st is not None else RsiState(id=STATE_ID, created_by="rsi")  # type: ignore[return-value]


def _acquire(store: Any, run_id: str, at: datetime) -> bool:
    """Single-flight across threads AND processes: BEGIN IMMEDIATE serialises the read-check-write."""
    with store.transaction(immediate=True):
        st = _state(store)
        inf = st.in_flight
        if inf and datetime.fromisoformat(inf["lease_until"]) > at:
            return False
        st.in_flight = {"run_id": run_id, "lease_until": (at + LEASE).isoformat()}
        store.put("rsi_state", st)
    return True


def _release(store: Any, run_id: str) -> None:
    with store.transaction(immediate=True):
        st = _state(store)
        if st.in_flight and st.in_flight.get("run_id") == run_id:
            st.in_flight = None
            store.put("rsi_state", st)


def _note_attempt(store: Any, at: datetime, outcome: str, reason: str, run_id: str | None = None,
                  **inputs: Any) -> None:
    with store.transaction(immediate=True):
        st = _state(store)
        st.last_attempt = {"at": at.isoformat(), "outcome": outcome, "reason": reason, "run_id": run_id,
                           **inputs}
        store.put("rsi_state", st)


def _trigger(st: RsiState, fp: str, code_hash: str, rows: dict[str, str], force: bool,
             at: datetime) -> tuple[str | None, str]:
    lc = st.last_consumed
    if st.last_pass_run is None or lc is None:
        return "bootstrap", "no passing baseline yet"
    if code_hash != lc.get("code_hash"):
        return "T2", "loaded retrieval code changed"
    if fp != lc.get("corpus_fp"):
        n = rows_changed(lc.get("rows") or {}, rows)
        age = at - datetime.fromisoformat(lc["at"])
        if n >= DEBOUNCE_ROWS or age > DEBOUNCE_AGE:
            return "T1", f"corpus changed: {n} rows, last run {age.total_seconds() / 3600:.1f} h ago"
        pending = f"corpus changed by {n} rows (< {DEBOUNCE_ROWS}) and last run < 24 h ago: debounced"
        return ("manual", pending) if force else (None, pending)
    return ("manual", "forced") if force else (None, "no change since the last consumed run")


# ----------------------------------------------------------------------------- manifest + exams
def _resolve(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else V8_ROOT / p


def load_manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise RsiError(f"manifest unreadable: {path}: {e}") from e
    try:
        m = json.loads(raw)
    except ValueError as e:
        raise RsiError(f"manifest malformed: {path}: {e}") from e
    exams = m.get("exams") if isinstance(m, dict) else None
    if not isinstance(exams, list) or not exams:
        raise RsiError(f"manifest malformed: {path}: needs a non-empty 'exams' list")
    for i, e in enumerate(exams, 1):
        if not isinstance(e, dict) or not e.get("path"):
            raise RsiError(f"manifest malformed: exam #{i} needs a 'path'")
        if not e.get("skip") and e.get("required") not in REQUIRED_FIELDS:
            raise RsiError(f"manifest malformed: exam #{i} needs 'required' in {REQUIRED_FIELDS} or a 'skip' reason")
    f = m.get("finding")
    if not isinstance(f, dict) or not f.get("ticket_id") or not f.get("to"):
        raise RsiError("manifest malformed: 'finding' needs ticket_id and to")
    names = [e.get("name") or Path(e["path"]).stem for e in exams]
    if len(set(names)) != len(names):
        raise RsiError("manifest malformed: exam names must be unique (they key the per-question baseline)")
    if not [e for e in exams if not e.get("skip")]:
        raise RsiError("manifest lists no exam with required evidence")
    return m, raw


def load_exam(entry: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bytes]:
    """(questions, synthetic corpus or None, raw bytes). Every question must declare required ids."""
    path = _resolve(entry["path"])
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except OSError as e:
        raise RsiError(f"exam missing: {entry['path']}: {e}") from e
    except ValueError as e:
        raise RsiError(f"exam malformed: {entry['path']}: {e}") from e
    corpus = data.get("corpus") if isinstance(data, dict) else None
    qs = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(qs, list) or not qs:
        raise RsiError(f"exam malformed: {entry['path']}: no questions")
    field = entry["required"]
    out = []
    seen: set[Any] = set()
    for i, q in enumerate(qs, 1):
        req = q.get(field) if isinstance(q, dict) else None
        if not isinstance(q, dict) or not q.get("epic") or not q.get("question") or not isinstance(req, list) \
                or not req or not all(isinstance(x, str) and x.strip() for x in req):
            raise RsiError(f"exam malformed: {entry['path']} question #{i} needs epic, question and a "
                           f"non-empty list of id strings in {field}")
        n = q.get("n", i)
        if n in seen:
            raise RsiError(f"exam malformed: {entry['path']} repeats question n={n}")
        seen.add(n)
        out.append({"n": q.get("n", i), "epic": q["epic"], "question": q["question"],
                    "required": list(req), "paths": list(q.get("paths") or []), "vec": q.get("vec")})
    return out, corpus, raw


# ----------------------------------------------------------------------------- the synthetic world
class FixtureEmbedder:
    """The synthetic fixture's declared embedding: each tagged text maps to a 0/1 vector over the
    fixture's tag vocabulary; any other text is the zero vector. Deterministic and model-free, so the
    dense leg's code path is exercised without loading a model."""

    name = "fixture"
    fallback_reason = None

    def __init__(self, tags_by_text: dict[str, list[str]]):
        self._tags = tags_by_text
        self._vocab = sorted({t for tags in tags_by_text.values() for t in tags})

    def embed(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        return [[1.0 if v in self._tags.get(t, ()) else 0.0 for v in self._vocab] or [0.0] for t in texts]


def synthetic_world(corpus: dict[str, Any], questions: list[dict[str, Any]]) -> tuple[Store, Any]:
    """An in-memory Store + Index holding only the fixture's corpus (never the board DB)."""
    from .schemas import Decision, KgLink
    from .search import Index
    s = Store(":memory:")
    tags: dict[str, list[str]] = {}
    for t in corpus.get("tickets") or []:
        s.put("ticket", Ticket(**t))
    for d in corpus.get("decisions") or []:
        vec = d.get("vec")
        dec = Decision(**{k: v for k, v in d.items() if k != "vec"})
        s.put("decision", dec)
        if vec:
            tags[Store._fts_text("decision", dec.model_dump(mode="json")) or ""] = list(vec)
    for lk in corpus.get("kglinks") or []:
        s.put("kglink", KgLink(**lk))
    for q in questions:
        if q.get("vec"):
            tags[q["question"]] = list(q["vec"])
    index = Index(embedder=FixtureEmbedder(tags), cache=None)
    index.rebuild(s.all_text_units())
    return s, index


# ----------------------------------------------------------------------------- replay
def _dense_status(index: Any) -> dict[str, Any]:
    if index is None:
        return {"available": False, "warming": False, "embed_model": "none"}
    st = index.status()
    return {"available": bool(st.get("embeddings_active")), "warming": bool(st.get("warming")),
            "embed_model": st.get("model") or st.get("embedder")}


class _Watch:
    """A pass-through view that RECORDS any exception a retrieval leg raises. knowledge.lookup swallows a
    failing FTS or dense leg (a seat still gets a pack), which would let a broken leg pass the tripwire;
    the replay turns what was recorded into an error, so the run fails closed. Seat lookups are unchanged."""

    def __init__(self, inner: Any, errors: list[str], names: set[str]):
        self._inner, self._errors, self._names = inner, errors, names

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name not in self._names or not callable(attr):
            return attr

        def call(*a: Any, **k: Any) -> Any:
            try:
                return attr(*a, **k)
            except Exception as e:
                self._errors.append(f"{name}: {type(e).__name__}: {e}")
                raise
        return call


def replay(questions: list[dict[str, Any]], exam_name: str, store: Any, index: Any, *, ref_now: datetime,
           paths: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One seat-identical lookup per question; `present` = required ids that are records IN the pack
    (replaces-history does not count, §0 row 2)."""
    out = []
    for q in questions:
        errors: list[str] = []
        s = _Watch(store, errors, {"fts_search"})
        ix = _Watch(index, errors, {"dense_search", "search", "status"}) if index is not None else None
        try:
            value = knowledge.wired_lookup(s, ix, q["epic"], question=q["question"], ref_now=ref_now,
                                           **(paths or {}))
        except Exception as e:  # fail closed: one broken lookup makes the whole run an error
            raise RsiError(f"lookup failed on {exam_name}#{q['n']}: {type(e).__name__}: {e}") from e
        if errors:  # a leg failed inside lookup and was swallowed there: still an error here
            raise RsiError(f"lookup failed on {exam_name}#{q['n']}: retrieval leg {errors[0]}")
        ids = {r.get("id") for r in value.get("records") or []}
        present = [i for i in q["required"] if i in ids]
        out.append({"exam": exam_name, "n": q["n"], "required": q["required"], "present": present,
                    "missing_ids": [i for i in q["required"] if i not in ids],
                    **({"paths": q["paths"]} if q["paths"] else {})})
    return out


def regressions(base: RsiRun | None, per_question: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Required ids the last PASS found that this run does not. A question new since the baseline, or a
    miss the baseline already had, is reported in per_question but is not a regression."""
    if base is None:
        return []
    was = {(p["exam"], p["n"]): set(p.get("present") or []) for p in base.per_question}
    out = []
    for p in per_question:
        lost = [i for i in p["required"] if i in was.get((p["exam"], p["n"]), set()) and i not in p["present"]]
        if lost:
            out.append({"exam": p["exam"], "n": p["n"], "lost_ids": lost})
    return out


def _peak_rss_mb() -> float | None:
    try:
        import psutil
        mi = psutil.Process().memory_info()
        return round(getattr(mi, "peak_wset", mi.rss) / (1024 ** 2), 1)
    except Exception:
        return None


def _free_mb() -> float | None:
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 2)
    except Exception:
        return None


# ----------------------------------------------------------------------------- finding
def _finding_text(run: RsiRun, base_id: str | None) -> str:
    lines = [f"RSI tripwire {run.id} ({run.trigger}): {len(run.regressions)} question(s) lost required "
             f"evidence against pass {base_id}. F0 checks evidence presence only, not answers."]
    for r in run.regressions:
        lines.append(f"- {r['exam']}#{r['n']} lost {', '.join(r['lost_ids'])}")
    idt = run.identity
    lines.append(f"identity: code {str(idt.get('code_hash'))[:12]} · corpus {str(idt.get('corpus_fp'))[:12]} "
                 f"({idt.get('corpus_rows')} rows) · dense {'on' if idt.get('dense_available') else 'OFF'} "
                 f"· clock {idt.get('clock_pinned_at')}")
    lines.append(f"Full per-question evidence: rsi_run {run.id} (python -m edp8.rsi show {run.id}).")
    return "\n".join(lines)


def post_finding(store: Any, board: Any, run: RsiRun, target: dict[str, str], base_id: str | None) -> str:
    """The ONE finding for a regressed run, idempotent by run id: the message and the run's
    finding_msg_id land in one transaction, and a run that already carries one posts nothing."""
    with store.transaction(immediate=True):
        cur = store.get("rsi_run", run.id)
        if cur is not None and cur.finding_msg_id:
            return cur.finding_msg_id
        t = board.ticket(target["ticket_id"])
        to, _note = board.resolve_recipient(target["to"], t)
        text = _finding_text(run, base_id)
        m = Message(id=new_id("m"), ticket_id=t.id, to=to, kind=MessageKind.finding, text=text,
                    created_by=ACTOR.id)
        store.put("message", m)
        board._index("message", m.id, text)
        board._emit(t.id, EventKind.message_sent,
                    {"message": m.id, "to": to, "kind": MessageKind.finding, "from": ACTOR.id,
                     "from_type": ACTOR.type, "from_role": "rsi", "text": text[:280], "mentions": []})
        run.finding_msg_id = m.id
        store.put("rsi_run", run)
    return m.id


# ----------------------------------------------------------------------------- tick
def _hold(store: Any, at: datetime, reason: str, dry_run: bool) -> dict[str, Any]:
    if not dry_run:
        _note_attempt(store, at, "hold", reason)
    return {"verdict": "hold", "hold_reason": reason, "run": None}


def tick(store: Any, index: Any = None, *, board: Any = None, manifest: Path | str | None = None,
         force: bool = False, dry_run: bool = False, code: CodeIdentity | None = None,
         paths: dict[str, Any] | None = None, free_mb: Callable[[], float | None] | None = None,
         ) -> dict[str, Any]:
    """One monitor step. Returns {verdict, run, ...}: verdict None (no trigger), hold, skipped (another
    tick holds the lease), pass, regressed or error. `paths` switches one retrieval path off for every
    lookup of THIS run (fts/dense False, max_hops 0/1) — the tripwire's own self-test (§9 c3)."""
    t0 = time.perf_counter()
    started = now()
    code = code or LOADED
    stale = code.stale()
    if stale:
        return _hold(store, started, f"restart pending: {', '.join(stale)} changed on disk since this "
                                     "process loaded it", dry_run)
    mb = (free_mb or _free_mb)()
    if mb is not None and mb < RAM_FLOOR_MB:
        return _hold(store, started, f"low RAM: {mb:.0f} MB free < {RAM_FLOOR_MB} MB floor", dry_run)
    run_id = new_id("rsi")
    if not dry_run and not _acquire(store, run_id, started):
        return {"verdict": "skipped", "reason": "another tick holds the lease", "run": None}
    try:
        st = _state(store)
        rows = corpus_rows(store)
        fp, ch = fingerprint(rows), code.code_hash()
        trig, why = _trigger(st, fp, ch, rows, force, started)
        if trig is None:
            if not dry_run:
                _note_attempt(store, started, "no_trigger", why)
            return {"verdict": None, "reason": why, "run": None}
        dense = _dense_status(index)
        base = store.get("rsi_run", st.last_pass_run) if st.last_pass_run else None
        if dense["warming"]:
            return _hold(store, started, "dense index warming", dry_run)
        if base is not None and base.identity.get("dense_available") and not dense["available"] \
                and (paths or {}).get("dense", True):
            return _hold(store, started, "dense unavailable (the baseline pass had it)", dry_run)
        ref = base.started_at if base is not None and base.started_at else started
        identity: dict[str, Any] = {
            "code_hash": ch, "code_files": dict(code.loaded), "stale_process": False,
            "corpus_fp": fp, "corpus_rows": len(rows), "clock_pinned_at": ref.isoformat(),
            "dense_available": dense["available"], "embed_model": dense["embed_model"],
            "policy": P0, "paths": dict(paths or {}), "rubric_hash": None}
        run = RsiRun(id=run_id, trigger=trig, identity=identity, baseline_run=base.id if base else None,
                     verdict="error", started_at=started, created_by="rsi")
        identity = run.identity  # pydantic copied the dict: later hashes must land on the run's own copy
        target: dict[str, str] = {}
        try:
            mpath = Path(manifest) if manifest else MANIFEST
            m, mraw = load_manifest(mpath)
            target = m["finding"]
            identity["manifest_hash"] = _sha(mraw)
            identity["exam_hashes"] = {}
            per_question: list[dict[str, Any]] = []
            for entry in m["exams"]:
                name = entry.get("name") or Path(entry["path"]).stem
                if entry.get("skip"):
                    run.skipped.append({"exam": name, "path": entry["path"], "reason": entry["skip"]})
                    continue
                qs, corpus, raw = load_exam(entry)
                identity["exam_hashes"][entry["path"]] = _sha(raw)
                if corpus is not None:
                    s_store, s_index = synthetic_world(corpus, qs)
                    per_question += replay(qs, name, s_store, s_index, ref_now=ref, paths=paths)
                else:
                    per_question += replay(qs, name, store, index, ref_now=ref, paths=paths)
            # the finding target (ticket AND addressee) must resolve before a run may pass: a regression
            # nobody can be told of is an error
            if board is not None:
                board.resolve_recipient(target["to"], board.ticket(target["ticket_id"]))
            elif not dry_run:
                raise RsiError("no board to post a finding through")
            run.per_question = per_question
            req = sum(len(p["required"]) for p in per_question)
            run.f0 = {"questions": len(per_question), "required": req,
                      "present_frac": round(sum(len(p["present"]) for p in per_question) / req, 4) if req else None}
            run.regressions = regressions(base, per_question)
            run.verdict = "regressed" if run.regressions else "pass"
        except RsiError as e:
            run.verdict, run.error = "error", str(e)
        except Exception as e:  # noqa: BLE001 — anything unexpected is an error run, never a pass
            run.verdict, run.error = "error", f"{type(e).__name__}: {e}"
        run.ended_at = now()
        run.wall_s = round(time.perf_counter() - t0, 3)
        run.peak_rss_mb = _peak_rss_mb()
        if dry_run:
            return {"verdict": run.verdict, "run": run.model_dump(mode="json"), "dry_run": True}
        return _commit(store, board, run, st, rows, fp, ch, target, base)
    finally:
        if not dry_run:
            _release(store, run_id)


def _commit(store: Any, board: Any, run: RsiRun, st0: RsiState, rows: dict[str, str], fp: str, ch: str,
            target: dict[str, str], base: RsiRun | None) -> dict[str, Any]:
    at = run.started_at or now()
    la = st0.last_attempt or {}
    if run.verdict == "error" and la.get("outcome") == "error" and la.get("reason") == run.error \
            and la.get("corpus_fp") == fp and la.get("code_hash") == ch:
        # the same failure on the same inputs: refresh the attempt, do not pile up identical error rows
        _note_attempt(store, at, "error", run.error, la.get("run_id"), corpus_fp=fp, code_hash=ch)
        return {"verdict": "error", "run": la.get("run_id"), "error": run.error, "repeat": True}
    prev_regressed = None
    with store.transaction(immediate=True):
        st = _state(store)
        if not st.in_flight or st.in_flight.get("run_id") != run.id:
            # our lease expired and another tick took it: its result stands, ours is dropped unwritten
            return {"verdict": "skipped", "reason": "lease lost before commit", "run": None}
        lc = st.last_consumed or {}
        if lc.get("run_id"):
            prev = store.get("rsi_run", lc["run_id"])
            if prev is not None and prev.verdict == "regressed":
                prev_regressed = prev
        if run.verdict == "regressed" and prev_regressed is not None and prev_regressed.finding_msg_id \
                and prev_regressed.regressions == run.regressions \
                and all(prev_regressed.identity.get(k) == run.identity.get(k)
                        for k in ("code_hash", "corpus_fp", "manifest_hash", "exam_hashes", "paths")):
            # a re-tick of the SAME state finding the SAME loss: that finding already describes it
            run.finding_msg_id = prev_regressed.finding_msg_id
        store.put("rsi_run", run)
        st.last_attempt = {"at": at.isoformat(), "outcome": run.verdict, "reason": run.error or run.trigger,
                           "run_id": run.id, "corpus_fp": fp, "code_hash": ch}
        if run.verdict in ("pass", "regressed"):
            st.last_consumed = {"at": at.isoformat(), "run_id": run.id, "corpus_fp": fp, "code_hash": ch,
                                "rows": rows}
        if run.verdict == "pass":
            st.last_pass_run = run.id
        store.put("rsi_state", st)
        if run.verdict == "regressed" and not run.finding_msg_id:
            post_finding(store, board, run, target, base.id if base else None)
    return {"verdict": run.verdict, "run": run.id, "regressions": run.regressions,
            "finding_msg_id": run.finding_msg_id, "error": run.error or None}


# ----------------------------------------------------------------------------- board thread
def start_thread(board: Any, *, interval_s: float | None = None,
                 first_wait_s: float | None = None) -> tuple[threading.Thread, threading.Event]:
    """The board sweep (§9 wiring): ticks every `interval_s` while EDP8_RSI=1 — the flag is re-read
    every loop, so unsetting it stops the thread within one loop; `stop` ends it at once."""
    stop = threading.Event()
    interval = INTERVAL_S if interval_s is None else interval_s
    wait = FIRST_WAIT_S if first_wait_s is None else first_wait_s

    def _loop() -> None:
        w = wait
        while not stop.wait(w):
            w = interval
            if os.environ.get("EDP8_RSI") != "1":
                _log.info("EDP8_RSI unset: rsi sweep stops")
                return
            try:
                res = tick(board.store, board.index, board=board)
                if res.get("verdict") not in (None, "pass", "skipped"):
                    _log.warning("rsi tick: %s", {k: res.get(k) for k in ("verdict", "run", "hold_reason", "error")})
            except Exception as e:  # noqa: BLE001 — the sweep never takes the board down
                _log.warning("rsi tick failed: %s", e)

    th = threading.Thread(target=_loop, name="edp8-rsi-sweep", daemon=True)
    th.start()
    return th, stop


# ----------------------------------------------------------------------------- CLI
def _cli_board(db: str) -> Any:
    from .board import Board
    from .search import Index, VectorCache, make_embedder
    store = Store(db)
    try:
        cache = VectorCache(os.environ.get("EDP8_VEC_CACHE", str(db) + ".vec"))
    except Exception:
        cache = None
    index = Index(embedder=make_embedder(), cache=cache)
    index.rebuild(store.all_text_units())
    deadline = time.monotonic() + float(os.environ.get("EDP8_RSI_WARM_S", "900"))
    while index.status().get("warming") and time.monotonic() < deadline:
        time.sleep(1.0)
    return Board(store, index)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m edp8.rsi", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick", help="one monitor step")
    t.add_argument("--dry-run", action="store_true", help="evaluate and print; write nothing")
    t.add_argument("--force", action="store_true", help="run even when no trigger is pending")
    t.add_argument("--db", default=None, help="board DB (default EDP8_DB or EDP8_HOME/edp8.db)")
    t.add_argument("--manifest", default=None, type=Path)
    s = sub.add_parser("show", help="print one rsi_run (or the state with no id)")
    s.add_argument("run_id", nargs="?")
    s.add_argument("--db", default=None)
    a = ap.parse_args(argv)
    db = a.db or os.environ.get("EDP8_DB", str(Path(os.environ.get("EDP8_HOME", ".")) / "edp8.db"))
    if a.cmd == "show":
        store = Store(db)
        obj = store.get("rsi_run", a.run_id) if a.run_id else _state(store)
        print(json.dumps(obj.model_dump(mode="json") if obj else None, indent=1))
        return 0
    board = _cli_board(db)
    if not a.dry_run:
        ensure_p0(board.store)
    res = tick(board.store, board.index, board=board, manifest=a.manifest, force=a.force, dry_run=a.dry_run)
    print(json.dumps(res, indent=1, default=str))
    return {None: 0, "pass": 0, "skipped": 0, "regressed": 1, "error": 2, "hold": 3}.get(res.get("verdict"), 2)


if __name__ == "__main__":
    sys.exit(main())
