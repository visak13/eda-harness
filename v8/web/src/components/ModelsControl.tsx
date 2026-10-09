import { hideFromGuests } from "../auth/guest";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  choiceFromTags, getEpicPage, getTicket, optionToken, roleOptionsFromTags, sameOption, setTicketTags,
  withChoiceTags, withStoryPick, type SeatOption,
} from "../api/endpoints";
import { getModels, modelLabel } from "../api/seats";
import type { ModelCatalog, ModelMeta } from "../api/types";
import { BoardApiError } from "../api/client";
import { EFFORTS, effortCap, SeatPickHead, SeatPickRow, type Effort } from "./SeatPicks";
import { AddOptionButton, effortOf, normOption, RoleOptionList } from "./SeatOptions";
import { roleLabel } from "./iconPaths";
import { useActionDirty } from "./actionDirty";
import { useDrawerClose } from "./Drawer";
import ui from "./ui.module.css";
import styles from "./ModelsControl.module.css";

// S-UI (owner m-ec5a9b86c5): Actions → Models… on the epic page and on every story page. S7 (design-
// b6a55eed13 §4.E): each role has an ORDERED option list — `model:<role>=<id>@<effort>|<id>@<effort>`, the
// first one the default — and each STORY may run a role on any model of that role's catalog row at any effort up
// to the model's cap (`seat:<role>=<id>@<effort>` on the story; RC2 F2, architect m-1f09a47214: the epic's list
// is the default and the quick choices, not a limit). Save rewrites the epic's tags (PATCH /v1/tickets/{epic}; the owner or the architect may)
// and the picked stories' tags. Only later spawns read them: a seat already running is never swapped.
// Precedence at a spawn: spawn argument > story pick > the role's first option > the catalog default.

const same = (a: SeatOption[], b: SeatOption[]) => a.length === b.length && a.every((o, i) => sameOption(o, b[i]));
const dedupe = (l: SeatOption[]) => l.filter((o, i) => l.findIndex((x) => sameOption(x, o)) === i);
const label = (o: SeatOption, meta?: Record<string, ModelMeta>) => `${modelLabel(o.model, meta?.[o.model])} · ${o.effort || "medium"}`;

function ModelsControlView({ epicId, storyId }: { epicId: string; storyId?: string }): React.JSX.Element {
  const qc = useQueryClient();
  const modelsQ = useQuery({ queryKey: ["models"], queryFn: getModels, retry: false });
  const epicQ = useQuery({ queryKey: ["ticket-record", epicId], queryFn: () => getTicket(epicId), retry: false });
  const pageQ = useQuery({ queryKey: ["epic", epicId, null], queryFn: () => getEpicPage(epicId, null), retry: false });
  const [lists, setLists] = useState<Record<string, SeatOption[]>>({});
  const [storyEdits, setStoryEdits] = useState<Record<string, Record<string, SeatOption | null>>>({});
  const [saved, setSaved] = useState<string | null>(null);
  const catalog = modelsQ.data as ModelCatalog | undefined;
  const meta = catalog?.models;
  const tags = epicQ.data?.tags ?? [];
  const current = catalog ? choiceFromTags(tags, catalog) : null;
  const roles = Object.keys(catalog?.roles ?? {});
  const explicit = roleOptionsFromTags(tags);

  // the saved list of a role: its tag list, else the one default the role runs on today
  const savedList = (r: string): SeatOption[] => {
    const listed = (explicit[r] ?? []).filter((o) => catalog?.roles[r]?.includes(o.model));
    if (listed.length) return dedupe(listed.map((o) => normOption(o, meta)));
    return current?.roleModels[r]
      ? [normOption({ model: current.roleModels[r], effort: current.roleEfforts[r] }, meta)] : [];
  };
  const listOf = (r: string): SeatOption[] => lists[r] ?? savedList(r);
  const edit = (r: string, fn: (l: SeatOption[]) => SeatOption[]) => {
    setSaved(null);
    setLists((p) => ({ ...p, [r]: fn(p[r] ?? savedList(r)) }));
  };
  const dirtyRoles = roles.filter((r) => !same(dedupe(listOf(r)), savedList(r)));

  // stories that may pick: one story page → that story; the epic page → every story of the epic
  const stories = (pageQ.data?.board.epic.children ?? []).filter((s) => s.kind === "story" && (!storyId || s.id === storyId));
  const savedPick = (s: string, r: string): SeatOption | null => {
    const p = pageQ.data?.story_picks?.[s]?.[r];
    return p ? { model: p.model, effort: p.effort ?? "" } : null;
  };
  const pickOf = (s: string, r: string): SeatOption | null => (storyEdits[s]?.[r] !== undefined ? storyEdits[s][r] : savedPick(s, r));
  // what a story may run a role on: the epic's list first, then every catalog model of the role at each effort
  // up to its cap (the board's rule, seat_choice.story_pick_problem)
  const upTo = (m: string): Effort[] => EFFORTS.slice(0, EFFORTS.indexOf(effortCap(m, meta) ?? "high") + 1);
  const anyOf = (r: string): SeatOption[] => (catalog?.roles[r] ?? []).flatMap((m) => upTo(m).map((e) => ({ model: m, effort: e })));
  const inList = (r: string, o: SeatOption | null) => !o
    || ((catalog?.roles[r] ?? []).includes(o.model) || listOf(r).some((x) => x.model === o.model))
      && (!o.effort || upTo(o.model).includes(o.effort as Effort));
  // the story's own doer (engineer) always; another role once it has a choice to make or a pick to show
  const pickRoles = roles.filter((r) => r === "engineer" || dedupe(listOf(r)).length > 1 || stories.some((s) => pickOf(s.id, r)));
  const dirtyPicks = stories.flatMap((s) => pickRoles.filter((r) => storyEdits[s.id]?.[r] !== undefined
    && JSON.stringify(storyEdits[s.id][r]) !== JSON.stringify(savedPick(s.id, r))).map((r) => [s.id, r] as const));
  const dirty = dirtyRoles.length > 0 || dirtyPicks.length > 0;
  useActionDirty(dirty);

  const save = useMutation({
    mutationFn: async () => {
      const roleModels = Object.fromEntries(roles.map((r) => [r, listOf(r)[0]?.model ?? ""]));
      const roleEfforts = Object.fromEntries(roles.map((r) => [r, listOf(r)[0]?.effort ?? ""]));
      // a role with a list in its tags, or one edited now, gets its whole ordered list; the rest stay as they were
      const roleOptions = Object.fromEntries(roles.filter((r) => explicit[r]?.length || dirtyRoles.includes(r))
        .map((r) => [r, dedupe(listOf(r))]));
      let res: unknown = null;
      if (dirtyRoles.length) res = await setTicketTags(epicId, withChoiceTags(tags, { roleModels, roleEfforts, roleOptions }));
      // each story's pick: the edit; an old pick is dropped only when its model left the role's catalog row
      for (const s of stories) {
        const edits = storyEdits[s.id] ?? {};
        const touched = roles.filter((r) => edits[r] !== undefined
          || (dirtyRoles.includes(r) && !inList(r, savedPick(s.id, r))));
        if (!touched.length) continue;
        let st = (await getTicket(s.id)).tags ?? [];
        for (const r of touched) {
          const want = edits[r] !== undefined ? edits[r] : savedPick(s.id, r);
          st = withStoryPick(st, r, want && inList(r, want) ? want : null);
        }
        res = await setTicketTags(s.id, st);
      }
      return res;
    },
    onSuccess: () => {
      setLists({}); setStoryEdits({});
      setSaved("Saved. Applies to the next seat spawned; a seat already running is never swapped.");
      void qc.invalidateQueries({ queryKey: ["ticket-record"] });
      void qc.invalidateQueries({ queryKey: ["epic", epicId] });
      void qc.invalidateQueries({ queryKey: ["ticket"] });
    },
  });
  const err = (save.error ?? modelsQ.error ?? epicQ.error) as BoardApiError | Error | null;
  const reset = () => { setLists({}); setStoryEdits({}); setSaved(null); };
  const close = useDrawerClose();

  return (
    <div className={styles.models} data-testid="models-dialog" role="group" aria-label={`Models for ${epicId}`}>
      {modelsQ.isPending || epicQ.isPending ? <p className={ui.empty}>Loading models…</p> : null}
      {roles.length ? <SeatPickHead /> : null}
      {roles.map((r) => {
        const list = listOf(r);
        const head = list[0] ?? { model: "", effort: "medium" };
        return (
          <div key={r} className={styles.role} data-testid={`models-role-${r}`}>
            <SeatPickRow role={r} testIdPrefix="models" options={catalog?.roles[r] ?? []} meta={meta}
              model={head.model} effort={effortOf(head)} disabled={save.isPending}
              onModel={(id) => edit(r, (l) => [normOption({ model: id, effort: l[0]?.effort ?? "medium" }, meta), ...l.slice(1)])}
              onEffort={(e: Effort) => edit(r, (l) => [normOption({ model: l[0]?.model ?? head.model, effort: e }, meta), ...l.slice(1)])}
              add={<AddOptionButton role={r} list={list} catalogIds={catalog?.roles[r] ?? []} meta={meta}
                disabled={save.isPending || !list.length} testIdPrefix="models" onChange={(next) => edit(r, () => next)} />} />
            <RoleOptionList role={r} list={list} catalogIds={catalog?.roles[r] ?? []} meta={meta}
              disabled={save.isPending || !list.length} testIdPrefix="models" onChange={(next) => edit(r, () => next)} />
          </div>
        );
      })}
      {stories.length && pickRoles.length ? (
        <div className={styles.picks} data-testid="models-story-picks">
          <div className={ui.sectionLabel}>Story picks</div>
          <p className={styles.note}>
            A story may run a role on any of that role&rsquo;s models, at any effort up to the model&rsquo;s cap; with no pick the role&rsquo;s first option runs.
          </p>
          {stories.map((s) => (
            <div key={s.id} className={styles.story} data-testid={`models-story-${s.id}`}>
              <span className={styles.storyName}><span className={ui.idMono}>{s.id}</span> {s.title}</span>
              {pickRoles.map((r) => {
                const opts = dedupe(listOf(r));
                const more = anyOf(r).filter((o) => !opts.some((x) => sameOption(x, o)));
                const pick = pickOf(s.id, r);
                const stale = !inList(r, pick);
                // RC2 F2: a pick the catalog no longer offers still runs (the story pick wins at a spawn), so the
                // select shows it, never "Default", and says why it is flagged
                const value = pick ? (stale ? optionToken(pick) : optionToken([...opts, ...more].find((o) => o.model === pick.model && (!pick.effort || o.effort === pick.effort)) ?? pick)) : "";
                return (
                  <label key={r} className={styles.pick}>
                    <span className={styles.pickRole}>{roleLabel(r)}</span>
                    <select className={ui.select} value={value} disabled={save.isPending} data-testid={`models-pick-${s.id}-${r}`}
                      aria-label={`${s.id} ${r} pick`}
                      onChange={(e) => {
                        setSaved(null);
                        const back = pick && stale && e.target.value === optionToken(pick); // the pick it already has
                        const o = [...opts, ...more].find((x) => optionToken(x) === e.target.value) ?? null;
                        setStoryEdits((p) => {
                          const { [r]: _, ...rest } = p[s.id] ?? {};
                          return { ...p, [s.id]: back ? rest : { ...rest, [r]: o } };
                        });
                      }}>
                      <option value="">Default{opts[0] ? ` (${label(opts[0], meta)})` : ""}</option>
                      <optgroup label="This epic's options">
                        {opts.map((o) => <option key={optionToken(o)} value={optionToken(o)}>{label(o, meta)}</option>)}
                      </optgroup>
                      {more.length ? <optgroup label={`Any ${roleLabel(r)} model`}>
                        {more.map((o) => <option key={optionToken(o)} value={optionToken(o)}>{label(o, meta)}</option>)}
                      </optgroup> : null}
                      {stale && pick ? <option value={optionToken(pick)}>{label(pick, meta)} (not in the catalog)</option> : null}
                    </select>
                    {stale && pick ? <span className={styles.stale} data-testid={`models-pick-stale-${s.id}-${r}`}>
                      runs on {label(pick, meta)}, which the catalog no longer lists for {roleLabel(r)} at that effort: pick another.
                    </span> : null}
                  </label>
                );
              })}
            </div>
          ))}
        </div>
      ) : null}
      <p className={styles.note} data-testid="models-applies-note">
        Applies to the next spawn: a seat already running keeps its model and effort and is never swapped.
        Each model&rsquo;s effort cap comes from its catalog entry (Admin → Seats &amp; models → Models); no seat runs above high.
      </p>
      {err ? <p className={ui.banner} role="alert" data-testid="models-error">{(err as BoardApiError).hint ?? err.message}</p> : null}
      {saved ? <p className={styles.note} role="status" data-testid="models-saved">{saved}</p> : null}
      <div className={styles.actions} data-testid="models-actions">
        {close ? <button type="button" className={ui.button} onClick={close} data-testid="models-close">Close</button> : null}
        <button type="button" className={ui.button} disabled={!dirty || save.isPending} onClick={reset}>Reset</button>
        <button type="button" className={`${ui.button} ${ui.buttonPrimary}`} disabled={!dirty || save.isPending || !catalog}
          onClick={() => save.mutate()} data-testid="models-save">
          {save.isPending ? "Saving…" : "Save models"}
        </button>
      </div>
    </div>
  );
}

/** e0cec S5: a guest never sees this control (the board refuses it). */
export const ModelsControl = hideFromGuests(ModelsControlView);
