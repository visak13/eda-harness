"""Plan load/save + worklog + snapshot (LLD §1)."""

import json
from pathlib import Path

from ..schemas import Plan
from .attribution import actor
from .atomic import (
    append_jsonl,
    filter_entries,
    read_jsonl,
    should_write_snapshot,
    write_atomic,
    write_snapshot,
)
from .ipc_lock import StoreConflict, object_lock
from .tiering import dehydrate_plan_payload, hydrate_plan_payload
from .vault_mirror import mirror_plan


class PlanStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        # C1 (s18): per-store last-saved state so save() snapshots only on a
        # state transition (or every Kth version), not on every per-tick save
        # (plan saves are frequent — every action stamp keeps the same state).
        self._last_state: dict[str, str] = {}

    def _file(self, pid: str) -> Path:
        return self.root / f"{pid}.json"

    def _dir(self, pid: str) -> Path:
        return self.root / pid

    def exists(self, pid: str) -> bool:
        return self._file(pid).exists()

    # ── DESIGN-v7 Phase 8 — the GROUNDING BRIEF sidecar ─────────────────────
    # One markdown file per plan (files in play + roles, key symbols,
    # invariants, landmines, test entry points), written by the PLANNER once
    # at grounding and injected into every worker + the reviewer brief — the
    # fix for the triple read (neuron reads the code, planner re-reads, every
    # worker re-reads, and none of it was durably shared).

    def write_grounding_brief(self, pid: str, content: str) -> str:
        d = self._dir(pid)
        d.mkdir(parents=True, exist_ok=True)
        write_atomic(d / "grounding-brief.md", content)
        return f"{pid}/grounding-brief.md"

    def read_grounding_brief(self, pid: str) -> str | None:
        try:
            return (self._dir(pid) / "grounding-brief.md").read_text(
                encoding="utf-8")
        except OSError:
            return None

    def find_by_step(self, recipe_id: str, step_id: str):
        """Find the plan for a recipe step. Convention-first (plan_id =
        f'{recipe_id}-{step_id}', fast path), then a scan by the plan's
        own recipe_id/recipe_step_id fields (robust if a planner ever
        names the plan off-convention). Returns Plan | None. Removes the
        silent-stall failure mode where the F2 disk-backstop relied on
        the naming convention alone."""
        pid = f"{recipe_id}-{step_id}"
        if self.exists(pid):
            return self.load(pid)
        if not self.root.exists():
            return None
        for f in self.root.glob("*.json"):
            try:
                p = self.load(f.stem)
            except Exception:
                continue
            if p.recipe_id == recipe_id and p.recipe_step_id == step_id:
                return p
        return None

    def list_for_recipe(self, recipe_id: str) -> list[Plan]:
        """Every loadable plan belonging to `recipe_id`, in filename order
        (DESIGN-v7 1.5.6 — the staleness delta walks a plan's SIBLINGS; the
        1.5.3 resume backstop walks a recipe's parked plans). Same tolerant
        scan discipline as find_by_step above: a corrupt or foreign plan file
        is skipped, never a raised exception — a staleness/park check must
        degrade to 'fewer siblings seen', not break a tick."""
        out: list[Plan] = []
        if not self.root.exists():
            return out
        for f in sorted(self.root.glob("*.json")):
            try:
                p = self.load(f.stem)
            except Exception:
                continue
            if p.recipe_id == recipe_id:
                out.append(p)
        return out

    # (W9's store half lived here: `_reachable_plan_payloads`, the shared
    # reachability predicate; `harvest_artifact_paths`, the direction reviewer's
    # deterministic artifact sample; and `count_done_actions`, the checkpoint
    # counter reconcile stamped onto the recipe. ALL THREE lost their only
    # callers when the neuron-facing direction-review surface was removed
    # (d128/d132) and are deleted rather than left as dead code.
    #
    # The HARVEST BUG (d127/d124) is retired with them: harvest_artifact_paths
    # expanded a `glob_matches` acceptance pattern with `Path().glob(pattern)`,
    # which is RELATIVE-ONLY, so this host's ABSOLUTE Windows acceptance paths
    # raised "Non-relative patterns are unsupported" and the direction reviewer
    # could not run here at all. Deleting the only caller is the fix.)

    def load(self, pid: str) -> Plan:
        data = json.loads(self._file(pid).read_text(encoding="utf-8"))
        # P2 tiering: resolve sidecar refs/markers to full text BEFORE
        # validation — the in-memory plan always carries full text, so the
        # RP-A worker-grounding resolve stays byte-identical. Legacy = no-op.
        warnings: list[str] = []
        data = hydrate_plan_payload(data, self._dir(pid), warnings)
        for w in warnings:
            append_jsonl(self._dir(pid) / "worklog.jsonl",
                         {"kind": "tiering_degraded", "detail": w})
        return Plan.model_validate(data)

    def save(self, plan: Plan) -> int:
        # F34 R2 #1 — same locked optimistic-version discipline as
        # RecipeStore.save (see the doc there): concurrent shells saving
        # the same plan must conflict loudly, never last-writer-wins.
        pdir = self._dir(plan.plan_id)
        with object_lock(pdir):
            f = self._file(plan.plan_id)
            if f.exists():
                try:
                    disk_v = json.loads(
                        f.read_text(encoding="utf-8")).get("version", 1)
                except (OSError, json.JSONDecodeError):
                    disk_v = plan.version
                if plan.version == 1 and disk_v != 1:
                    plan.version = disk_v            # fresh-object overwrite
                elif plan.version != disk_v:
                    raise StoreConflict(
                        f"plan {plan.plan_id!r} changed on disk (disk "
                        f"v{disk_v}, yours v{plan.version}) — another shell "
                        "saved after your load. Nothing was written; "
                        "re-read the plan and re-apply your change.")
            return self._save_locked(plan)

    def _save_locked(self, plan: Plan) -> int:
        plan.version += 1
        payload = plan.model_dump(mode="json")
        # P2 tiering: evidence blobs + injected-context texts move to
        # sidecars; live file AND snapshot store the dehydrated shape.
        payload = dehydrate_plan_payload(payload, self._dir(plan.plan_id))
        write_atomic(self._file(plan.plan_id), json.dumps(payload, indent=2))
        # C1 (s18): snapshot only on a state transition or every Kth version,
        # not on every save. The live plan.json above is always current.
        if should_write_snapshot(
            self._last_state.get(plan.plan_id), plan.state, plan.version
        ):
            write_snapshot(
                self._dir(plan.plan_id) / "snapshots", plan.version, payload
            )
        self._last_state[plan.plan_id] = plan.state
        append_jsonl(
            self._dir(plan.plan_id) / "worklog.jsonl",
            # W15 (a4): stamp actor attribution (by:{role,handle}) resolved
            # IN CODE from the environment (attribution.actor(), principle-6),
            # reusing a2's shared helper so who-wrote is identical across every
            # store. Additive to this NEW record only — legacy worklog untouched.
            {"kind": "plan_saved", "version": plan.version,
             "state": plan.state, "agent_role": "planner", "by": actor()},
        )
        # Sol-harness vault projection (2026-07-19): re-render the Obsidian
        # note on every save — best-effort, never fails the durable write.
        mirror_plan(plan, self.root)
        return plan.version

    def append_worklog(self, plan_id: str, record: dict) -> None:
        """Append an arbitrary worklog entry (crash recovery, drift,
        etc.). The trail is the working-memory layer that survives
        compaction (ADR-013). `ts` is added by append_jsonl.

        v7 WS3 (§2.1): worklogs are ARCHIVE-tier and now ROLL like recipe
        events — at the same threshold the head is archived to
        worklog.NNNN.jsonl + a code-generated digest, the hot tail stays.
        The O(1) stat gate makes the common append free; read_worklog's
        tail semantics are unchanged (it reads the bounded hot file).
        Live measurement that motivated this: a 558KB never-rolled hot
        worklog on plan …39fd30-s11. Best-effort — a rollup failure never
        fails the append."""
        pdir = self._dir(plan_id)
        with object_lock(pdir):
            append_jsonl(pdir / "worklog.jsonl", record)
            try:
                from .recipe_store import rollup_events
                rollup_events(pdir, filename="worklog.jsonl")
            except Exception:  # noqa: BLE001 — maintenance never blocks it
                pass

    def read_worklog(
        self,
        plan_id: str,
        tail: int = 20,
        kinds: list[str] | None = None,
        since: str | None = None,
        action_id: str | None = None,
    ) -> list[dict]:
        """Read the last `tail` worklog entries (2026-05-25). Lets an
        OBSERVER inspect a worker's externally-visible progress without
        the worker self-reporting — a working LLM is heads-down and
        can't heartbeat, so the neuron reads the trail instead.

        P1 read-efficiency: optional kinds/since/action_id filters are
        applied BEFORE the tail cut (see store.atomic.filter_entries), so
        `tail=20, kinds=['dispatch_failed']` is the last 20 of that kind."""
        entries = read_jsonl(self._dir(plan_id) / "worklog.jsonl")
        entries = filter_entries(
            entries, kinds=kinds, since=since, action_id=action_id
        )
        return entries[-tail:]
