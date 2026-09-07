import { authHeaders } from "../auth/identity";

// SEAM (envelope client). Every board response is `{ok, value?, hint?, error?}`.
// Unwrap it in exactly ONE place and fail loud + typed at the boundary, so no caller
// renders `undefined` and TanStack Query gets a thrown error to drive its error state.
export class BoardApiError extends Error {
  constructor(
    readonly status: number,
    readonly hint?: string,
    msg?: string,
  ) {
    super(msg ?? hint ?? `board ${status}`);
    this.name = "BoardApiError";
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...init?.headers },
  });
  const body = await res.json().catch(() => ({ ok: false, hint: "non-JSON response" }));
  if (!res.ok || !body.ok) {
    const err = typeof body.error === "object" ? body.error?.message : body.error;
    throw new BoardApiError(res.status, body.hint, err);
  }
  return body.value as T; // callers get value, never the envelope
}
