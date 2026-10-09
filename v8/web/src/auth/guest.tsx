import { useQuery } from "@tanstack/react-query";
import type React from "react";
import { api } from "../api/client";
import { getPoolCapabilities } from "../api/seats";
import type { WhoAmI } from "./useViewer";

/** e0cec S5 (design-b6a55eed13 §4.B): a guest is an invited outside person scoped to its member epics. The
 *  board refuses its authority actions (gates, verdicts, spawn, status, admin, models, Code); the UI hides
 *  them so a guest never meets a control that can only fail. The board stays the authority. */
export const GUEST_ROLE = "guest";

export function useIsGuest(): boolean {
  return useGuestState().guest;
}

/** S12-ui2 (qa m-da89ef8294 m7): `teammate` is true only once whoami says so — gate a read the board refuses a
 *  guest on it, so a guest's page never fires it while whoami is still loading. */
export function useGuestState(): { guest: boolean; teammate: boolean } {
  const who = useQuery({ queryKey: ["whoami"], queryFn: () => api<WhoAmI>("/v1/whoami"), retry: false });
  const role = who.data?.participant.role;
  return { guest: role === GUEST_ROLE, teammate: Boolean(role) && role !== GUEST_ROLE };
}

/** How a person is named: a guest is always `ext:<handle>`, never mistaken for a teammate. */
export function displayHandle(p: { handle?: string | null; role?: string | null } | null | undefined): string {
  const h = (p?.handle ?? "").replace(/^@/, "");
  return p?.role === GUEST_ROLE ? `ext:${h}` : h;
}

/** Wrap a control a guest may not use: it renders nothing for a guest. The wrapper owns the whoami hook, so
 *  the wrapped component's own hooks run in a stable order. */
export function hideFromGuests<P extends object>(Inner: (props: P) => React.JSX.Element | null) {
  function GuestHidden(props: P): React.JSX.Element | null {
    return useIsGuest() ? null : <Inner {...props} />;
  }
  GuestHidden.displayName = `hideFromGuests(${Inner.name})`;
  return GuestHidden;
}

/** qa m12: the pool's capabilities (GET /v1/pool/capabilities) are owner-only, and the board answers a guest
 *  403. Every reader goes through this one gate, so no guest page fires it (nor while whoami is loading). */
export function usePoolCapabilities(enabled = true) {
  const { teammate } = useGuestState();
  return useQuery({ queryKey: ["pool", "capabilities"], queryFn: getPoolCapabilities, retry: false, enabled: enabled && teammate });
}
