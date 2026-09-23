import { useEffect, useState, useSyncExternalStore } from "react";
import { authHeaders, identity } from "../auth/identity";
import { Icon } from "./Icon";
import { modelProvider, PROVIDER_ICONS, ROLE_ICONS, seatRole } from "./iconPaths";
import styles from "./Avatar.module.css";

// Authenticated identity SVGs share owned object URLs. Saving bumps only the current person's
// canonical ID and login alias; unrelated messages and other identities retain their bytes.
let version = 0;
const participantVersions = new Map<string, number>();
const listeners = new Set<() => void>();
export function bumpAvatarVersion(canonicalId = identity()): void {
  version += 1;
  participantVersions.set(canonicalId, version);
  participantVersions.set(identity(), version);
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

// Shared in-flight bytes and object URLs, keyed by actor/token as well as avatar identity.
// Last consumer releases the URL. Unrelated query refreshes never touch this cache.
const images = new Map<string, { refs: number; promise: Promise<string>; url?: string; controller: AbortController }>();
function useAvatarImage(id: string, size: number, v: number): string | undefined {
  const headers = authHeaders();
  const path = avatarUrl(id, size, v);
  const key = JSON.stringify([headers, path]);
  const [image, setImage] = useState<{ key: string; url: string }>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let entry = images.get(key);
    if (!entry) {
      const controller = new AbortController();
      const created = { refs: 0, controller, promise: Promise.resolve(""), url: undefined as string | undefined };
      created.promise = fetch(path, { headers, signal: controller.signal }).then(async (response) => {
        if (!response.ok) throw new Error(`avatar ${response.status}`);
        const blob = await response.blob();
        if (controller.signal.aborted) throw new Error("avatar released");
        return created.url = URL.createObjectURL(blob);
      }).catch((error) => {
        if (images.get(key) === created) images.delete(key); // failed promises must not poison new consumers
        throw error;
      });
      images.set(key, created); entry = created;
    }
    entry.refs++;
    let alive = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    void entry.promise.then((url) => { if (alive) setImage({ key, url }); }).catch(() => {
      if (alive && attempt < 2) retry = setTimeout(() => setAttempt((n) => n + 1), 1000 * (attempt + 1));
    });
    return () => {
      alive = false;
      if (retry) clearTimeout(retry);
      if (--entry.refs === 0) {
        entry.controller.abort();
        if (entry.url) URL.revokeObjectURL(entry.url);
        if (images.get(key) === entry) images.delete(key);
      }
    };
  }, [key, attempt]); // key contains every request input, including authenticated actor
  return image?.key === key ? image.url : undefined;
}

/** S-UI (owner m-ec5a9b86c5): an AGENT seat (`<role>.<ticket>` or a bare role) shows its role glyph
 *  instead of the generic generated avatar; a person keeps their picture. */
export function Avatar({ id, size = 24, className }: { id: string; size?: number; className?: string }): React.JSX.Element {
  const role = seatRole(id);
  if (role) return <RoleAvatar id={id} role={role} size={size} className={className} />;
  return <PictureAvatar id={id} size={size} className={className} />;
}

function RoleAvatar({ id, role, size, className }: { id: string; role: keyof typeof ROLE_ICONS; size: number; className?: string }): React.JSX.Element {
  const glyph = size >= 28 ? 18 : 16;
  return (
    <span className={`${styles.avatar} ${styles.role} ${styles[role] ?? ""} ${className ?? ""}`} style={{ width: size, height: size }}
      aria-hidden="true" data-testid="avatar" data-avatar-for={id} data-role-icon={role}>
      <Icon name={ROLE_ICONS[role]} size={glyph} />
    </span>
  );
}

/** The provider glyph (Claude / GPT) beside a model name; nothing for an unknown provider. */
export function ProviderIcon({ model, size = 16 }: { model: string | null | undefined; size?: 16 | 18 }): React.JSX.Element | null {
  const p = modelProvider(model);
  return p ? <span className={styles.provider} data-provider-icon={p} title={p === "gpt" ? "GPT (codex seat)" : "Claude"}><Icon name={PROVIDER_ICONS[p]} size={size} /></span> : null;
}

function PictureAvatar({ id, size, className }: { id: string; size: number; className?: string }): React.JSX.Element {
  useAvatarVersion();
  const v = participantVersions.get(id) ?? 0;
  const src = useAvatarImage(id, size, v);
  return (
    <img
      className={`${styles.avatar} ${className ?? ""}`}
      src={src}
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
