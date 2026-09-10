import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { identity } from "./identity";

export interface WhoAmI {
  participant: { id: string; handle: string; role: string; type?: string };
}

/** The viewer's aliases — the raw login string (`?as=` may be a handle), plus the canonical id and
 *  handle from /v1/whoami (adversary round 2 #4/#10, 2026-09-10: a human who logs in by handle has
 *  messages stored under their id; filtering on the login string alone lost both directions). */
export function useViewerAliases(): Set<string> {
  const as = identity();
  const who = useQuery({ queryKey: ["whoami"], queryFn: () => api<WhoAmI>("/v1/whoami"), retry: false });
  const out = new Set<string>();
  for (const v of [as, who.data?.participant.id, who.data?.participant.handle]) {
    if (v) {
      out.add(v);
      out.add(`@${v}`);
    }
  }
  return out;
}
