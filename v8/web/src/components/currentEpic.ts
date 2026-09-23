import { useEffect } from "react";
import { useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getTicketPage } from "../api/endpoints";

// The epic of the page in view — the epic itself, or a ticket's epic (its root; a quick task is its
// own). S-UI (owner m-ec5a9b86c5 "the decisions page is a mess with questions from all epics"): the
// rail's Needs you link carries it, and the last one seen this session is the Decisions page's
// default epic when the URL names none. Session storage is a per-tab convenience only (try/catch).

const KEY = "edp8.ui.last-epic";

export function rememberEpic(id: string): void {
  try { window.sessionStorage.setItem(KEY, id); } catch { /* storage blocked: no default */ }
}

export function recallEpic(): string | null {
  try { return window.sessionStorage.getItem(KEY); } catch { return null; }
}

export function useCurrentEpicId(): string {
  const location = useLocation();
  const m = /^\/(epic|ticket)\/([^/]+)/.exec(location.pathname);
  const kind = m?.[1];
  const id = m ? decodeURIComponent(m[2]) : "";
  const ticket = useQuery({ queryKey: ["ticket", id, null], queryFn: () => getTicketPage(id), enabled: kind === "ticket", retry: false });
  const epicId = kind === "epic" ? id : kind === "ticket" ? ticket.data?.epic_id ?? "" : "";
  useEffect(() => { if (epicId) rememberEpic(epicId); }, [epicId]);
  return epicId;
}
