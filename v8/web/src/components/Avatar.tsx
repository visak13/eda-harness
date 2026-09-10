import { useSyncExternalStore } from "react";
import styles from "./Avatar.module.css";

// The board's identity SVG for a participant (GET /v1/avatars/{id}.svg — header-less so an <img>
// can load it; humans get their chosen catalog avatar, seats a role glyph). Design §12 parity with
// the legacy avatars (human defect #11, 2026-09-10: the picker saved but nothing rendered). The
// server caches the SVG for 5 minutes, so a save bumps `avatarVersion` and every <Avatar> on the
// page re-fetches with a new query string — no reload, no stale face.
let version = 0;
const listeners = new Set<() => void>();
export function bumpAvatarVersion(): void {
  version += 1;
  listeners.forEach((l) => l());
}
function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
export function useAvatarVersion(): number {
  return useSyncExternalStore(subscribe, () => version, () => version);
}

export function avatarUrl(id: string, size: number, v: number): string {
  return `/v1/avatars/${encodeURIComponent(id)}.svg?size=${size}${v ? `&v=${v}` : ""}`;
}

export function Avatar({ id, size = 24, className }: { id: string; size?: number; className?: string }): React.JSX.Element {
  const v = useAvatarVersion();
  return (
    <img
      className={`${styles.avatar} ${className ?? ""}`}
      src={avatarUrl(id, size, v)}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      data-testid="avatar"
      data-avatar-for={id}
      loading="lazy"
    />
  );
}
