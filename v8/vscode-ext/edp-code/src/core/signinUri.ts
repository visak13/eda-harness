// S6 (s-e6b4fa59d5; design-e963c656f5 §4.8): the VS Code sign-in link an admin's invite carries,
// vscode://edp.edp-code/signin?board=<board url>&handle=<handle>&code=<one-time code>. Parsing and the
// POST /v1/join redeem live here (no `vscode` import) so the units test them; auth.ts stores the result
// through the same verify-then-store path as the prompted sign-in.

export interface SigninLink { origin: string; handle: string; code: string }

/** Parse the link's query; a string is the reason it is not a usable sign-in link. */
export function parseSigninLink(path: string, query: string): SigninLink | string {
  if (path.replace(/\/+$/, '') !== '/signin') return `not a sign-in link (${path || '/'})`;
  const q = new URLSearchParams(query);
  const board = q.get('board')?.trim() ?? '', handle = q.get('handle')?.trim() ?? '', code = q.get('code')?.trim() ?? '';
  if (!board) return 'the link names no board';
  let origin: string;
  try {
    const u = new URL(board);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return `the board address is not http(s): ${board}`;
    origin = u.origin;
  } catch { return `the board address is invalid: ${board}`; }
  if (!code) return 'the link carries no sign-in code; ask an admin for a new invite';
  return { origin, handle, code };
}

type Fetch = (url: string, init: { method: string; headers: Record<string, string>; body: string }) =>
  Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;

/** Spend the one-time code at POST /v1/join; the board's refusal is thrown as its own words. */
export async function redeemInvite(fetchFn: Fetch, link: SigninLink): Promise<{ participant: string; token: string }> {
  let res: Awaited<ReturnType<Fetch>>;
  try {
    res = await fetchFn(`${link.origin}/v1/join`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ code: link.code }) });
  } catch (e) { throw new Error(`the board at ${link.origin} did not answer (${(e as Error).message})`); }
  const env = (await res.json().catch(() => null)) as { ok?: boolean; value?: { handle?: string; token?: string }; error?: { message?: string } | string } | null;
  if (!res.ok || !env?.ok || !env.value?.token || !env.value.handle) {
    const msg = typeof env?.error === 'object' ? env.error?.message : env?.error;
    throw new Error(msg || `the board refused the sign-in code (HTTP ${res.status})`);
  }
  if (link.handle && env.value.handle !== link.handle) throw new Error(`the code belongs to ${env.value.handle}, not ${link.handle}`);
  return { participant: env.value.handle, token: env.value.token };
}
