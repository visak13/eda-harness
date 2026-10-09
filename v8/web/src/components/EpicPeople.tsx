import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, BoardApiError, postJson } from "../api/client";
import type { WhoAmI } from "../auth/useViewer";
import { GUEST_ROLE } from "../auth/guest";
import ui from "./ui.module.css";
import styles from "./EpicPeople.module.css";

/** e0cec S5 (design-b6a55eed13 §4.B): the epic's People — its guest members. A guest member reads this epic's
 *  tree (one link hop out) and nothing else on the board. The owner adds and removes guests here; everyone
 *  else reads the list. The board is the authority: PUT /v1/epics/{id}/members refuses a non-owner. */
export interface EpicMember { id: string; handle: string; display: string; role: string; type: string; retired?: boolean }
interface MembersValue { epic_id: string; members: EpicMember[] }
interface ParticipantRow { id: string; handle: string; role: string; type: string; retired?: boolean }

export const membersKey = (epicId: string) => ["epic-members", epicId] as const;

export function getEpicMembers(epicId: string): Promise<MembersValue> {
  return api<MembersValue>(`/v1/epics/${encodeURIComponent(epicId)}/members`);
}

export function putEpicMembers(epicId: string, members: string[]) {
  return postJson<MembersValue>(`/v1/epics/${encodeURIComponent(epicId)}/members`, { members }, "PUT");
}

export function EpicPeople({ epicId }: { epicId: string }): React.JSX.Element {
  const qc = useQueryClient();
  const who = useQuery({ queryKey: ["whoami"], queryFn: () => api<WhoAmI>("/v1/whoami"), retry: false });
  const canEdit = who.data?.participant.role === "owner";
  const members = useQuery({ queryKey: membersKey(epicId), queryFn: () => getEpicMembers(epicId) });
  const guests = useQuery({
    queryKey: ["participants", GUEST_ROLE],
    queryFn: () => api<ParticipantRow[]>(`/v1/participants?role=${GUEST_ROLE}`),
    enabled: canEdit,
  });
  const [pick, setPick] = useState("");
  const save = useMutation({
    mutationFn: (ids: string[]) => putEpicMembers(epicId, ids),
    onSuccess: (r) => {
      qc.setQueryData(membersKey(epicId), r.value);
      setPick("");
    },
  });

  if (members.isPending) return <p className={ui.empty}>Loading people…</p>;
  if (members.isError) return <p className={ui.banner} role="alert">Could not load people: {(members.error as Error).message}</p>;

  const rows = members.data.members;
  const ids = rows.map((m) => m.id);
  const candidates = (guests.data ?? []).filter((p) => !p.retired && !ids.includes(p.id));
  const error = save.error instanceof BoardApiError ? save.error.message : save.error ? String(save.error) : null;

  return (
    <section data-testid="epic-people" aria-label="People">
      <p className={styles.intro}>Guests read this epic and what it links to, ask questions, leave notes and upload files. They never
        answer gates, rule on criteria, spawn seats or change status.</p>
      {rows.length === 0 ? <p className={ui.empty} data-testid="people-empty">No guests on this epic.</p> : (
        <ul className={styles.list} data-testid="people-list">
          {rows.map((m) => (
            <li key={m.id} className={styles.row} data-testid="people-row" data-member={m.id}>
              <span className={styles.name}>{m.display}</span> <span className={ui.idMono}>{m.role}</span>
              {canEdit ? (
                <button type="button" className={ui.button} disabled={save.isPending} data-testid="people-remove"
                  aria-label={`Remove ${m.display}`} onClick={() => save.mutate(ids.filter((x) => x !== m.id))}>
                  Remove
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canEdit ? (
        <form className={styles.add} onSubmit={(e) => { e.preventDefault(); if (pick) save.mutate([...ids, pick]); }}>
          <label htmlFor={`people-add-${epicId}`}>Add a guest</label>{" "}
          <select className={ui.select} id={`people-add-${epicId}`} value={pick} onChange={(e) => setPick(e.target.value)} data-testid="people-pick">
            <option value="">{candidates.length ? "Choose a guest…" : "No other guests (invite one in Admin → Teammates)"}</option>
            {candidates.map((p) => <option key={p.id} value={p.id}>ext:{p.handle.replace(/^@/, "")}</option>)}
          </select>{" "}
          <button type="submit" className={ui.button} disabled={!pick || save.isPending} data-testid="people-add">Add</button>
        </form>
      ) : null}
      {error ? <p className={ui.banner} role="alert">{error}</p> : null}
    </section>
  );
}
