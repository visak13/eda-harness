import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, postJson } from "../api/client";
import type { AvatarState } from "../api/types";
import { bumpAvatarVersion } from "./Avatar";
import styles from "./AvatarPicker.module.css";

// The avatar picker lives in the preferences popover (design §4.1 "identity + preferences"): a
// human picks from the board's catalog (GET /v1/me/avatar) and the choice is saved with
// PUT /v1/me/avatar — the legacy /ui had this, the SPA had dropped it (adversary finding #11,
// 2026-09-10). Agents have no catalog and see nothing here.
export function AvatarPicker(): React.JSX.Element | null {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me", "avatar"], queryFn: () => api<AvatarState>("/v1/me/avatar"), retry: false });
  const save = useMutation({
    mutationFn: (avatar_id: string) => postJson<{ avatar_id: string }>("/v1/me/avatar", { avatar_id }, "PUT"),
    onSuccess: () => {
      bumpAvatarVersion(); // every <Avatar> on the page re-fetches past the server's 5-minute cache
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
  const catalog = q.data?.catalog ?? [];
  if (catalog.length === 0) return null;
  return (
    <fieldset className={styles.picker} data-testid="avatar-picker">
      <legend className={styles.legend}>Avatar</legend>
      <div className={styles.grid} role="radiogroup" aria-label="Avatar">
        {catalog.map((a) => {
          const chosen = a.id === q.data?.avatar_id;
          return (
            <button
              key={a.id}
              type="button"
              role="radio"
              aria-checked={chosen}
              aria-label={a.name}
              title={a.name}
              className={`${styles.cell} ${chosen ? styles.chosen : ""}`}
              disabled={save.isPending}
              onClick={() => save.mutate(a.id)}
              // The catalog SVG comes from the board's own avatars module (not user content).
              // eslint-disable-next-line react/no-danger
              dangerouslySetInnerHTML={{ __html: a.svg }}
            />
          );
        })}
      </div>
      {save.isError ? <p className={styles.err}>{(save.error as Error).message}</p> : null}
    </fieldset>
  );
}
