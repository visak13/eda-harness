import { useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getTicketPage } from "../api/endpoints";

// The epic of the page in view — the epic itself, or a ticket's epic (its root; a quick task is its own): the rail's
// CURRENT EPIC block reads it.

export function useCurrentEpicId(): string {
  const location = useLocation();
  const m = /^\/(epic|ticket)\/([^/]+)/.exec(location.pathname);
  const kind = m?.[1];
  const id = m ? decodeURIComponent(m[2]) : "";
  const ticket = useQuery({ queryKey: ["ticket", id, null], queryFn: () => getTicketPage(id), enabled: kind === "ticket", retry: false });
  return kind === "epic" ? id : kind === "ticket" ? ticket.data?.epic_id ?? "" : "";
}
