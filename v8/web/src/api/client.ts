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
  return (await apiEnvelope<T>(path, init)).value;
}

// Same unwrap, but also returns the envelope `hint`. The board writes its recipient-resolution
// note into `hint` on POST /v1/messages ("'reviewer' resolved to seat …") — the Composer must
// REPORT that verbatim, never compute its own (design §13). Reads use `api()` and drop it.
export async function apiEnvelope<T>(path: string, init?: RequestInit): Promise<{ value: T; hint: string }> {
  const res = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...init?.headers },
  });
  const body = await res.json().catch(() => ({ ok: false, hint: "non-JSON response" }));
  if (!res.ok || !body.ok) {
    const err = typeof body.error === "object" ? body.error?.message : body.error;
    throw new BoardApiError(res.status, body.hint, err);
  }
  return { value: body.value as T, hint: (body.hint as string) ?? "" };
}

// JSON POST helper: the board expects application/json and returns the same envelope.
export function postJson<T>(path: string, body: unknown): Promise<{ value: T; hint: string }> {
  return apiEnvelope<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}
