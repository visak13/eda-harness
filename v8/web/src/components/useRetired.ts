import { useQuery } from "@tanstack/react-query";
import { getSeats } from "../api/seats";

/** t-882e4d2eeb: people who left the board (removed, revoked, or an invite that expired unredeemed). They are
 *  out of every picker and People list server-side; history keeps their name, greyed, so the thread reads
 *  this set (ids and handles, with and without "@"). One /v1/seats read, shared with the Seats page. */
export function useRetired(): Set<string> {
  const q = useQuery({ queryKey: ["seats"], queryFn: getSeats, retry: false });
  const rows = (q.data as { retired?: { id: string; handle: string }[] } | undefined)?.retired ?? [];
  const out = new Set<string>();
  for (const r of rows) {
    for (const v of [r.id, r.handle]) {
      if (!v) continue;
      out.add(v);
      out.add(v.startsWith("@") ? v.slice(1) : `@${v}`);
    }
  }
  return out;
}
