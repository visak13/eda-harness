import { useQuery } from "@tanstack/react-query";
import { getPeople } from "../api/endpoints";
import type { PersonRow } from "../api/types";
import { displayHandle, GUEST_ROLE } from "../auth/guest";

// S12-ui2 (qa m-da89ef8294 item 6): a guest's participant id (`guest-bc795c7001`) is not a name. Wherever an author
// shows, a guest reads as People names it (`ext:<handle>`); a seat reads as its role (`engineer.s-…` → engineer).

/** The name an author id shows as, given the board's people list. */
export function personName(by: string, people: PersonRow[] | undefined): string {
  const bare = by.replace(/^@/, "");
  const p = people?.find((r) => r.id === bare || r.handle.replace(/^@/, "") === bare);
  if (p?.role === GUEST_ROLE) return displayHandle(p);
  return bare.includes(".") ? bare.split(".")[0] : bare;
}

/** `personName` over the cached `/v1/me/people` (the composer's and mentions' query). */
export function usePersonName(): (by: string) => string {
  const people = useQuery({ queryKey: ["me", "people"], queryFn: getPeople, retry: false });
  return (by: string) => personName(by, people.data);
}
