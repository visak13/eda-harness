// A board doc at one version, as a read-only editor document (C15 s-e14d316891; design §14.2): the URI
// `edp-doc:/<id>/v<N>.md` names exactly what the board serves at `GET /v1/docs/<id>?version=N`, so what the
// viewer read is what a sign-off rules on. C16 reuses the same source for its reader and version diff
// (architect m-3a4c731cd7); only the opener changes. Pure: no vscode import.

export const DOC_SCHEME = 'edp-doc';
export const DOC_ID = /^[a-z][a-z_]*-[0-9a-f]{10}$/;

/** `/<id>/v<N>.md` */
export function docPath(id: string, version: number): string {
  if (!DOC_ID.test(id) || !Number.isSafeInteger(version) || version < 1) throw new Error(`not a doc version: ${id} v${version}`);
  return `/${id}/v${version}.md`;
}

/** The doc id and version a path names, or null for anything else. */
export function parseDocPath(path: string): { id: string; version: number } | null {
  const m = /^\/([a-z][a-z_]*-[0-9a-f]{10})\/v([1-9][0-9]{0,8})\.md$/.exec(path);
  return m ? { id: m[1], version: Number(m[2]) } : null;
}
