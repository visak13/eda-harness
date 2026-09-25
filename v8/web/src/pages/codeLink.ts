// epic-91fcd3b370 S3: the Code tab deep link. `/code?folder=<abs>&file=<rel>&line=<n>[-<m>]` is
// parsed here (pure, unit-tested) and turned into the code-server iframe URL.
//
// Two measured facts shape it (code-server 4.138 native Windows, S1 report-b90f1f63df, S3 probe):
//  - `?folder=` must be `/c:/Projects/...` — leading slash, lowercase drive, forward slashes. The
//    `C:/...` form opens a phantom workspace in which git finds no repository (dec-ea925a2d30).
//  - A file opens at a line through the workbench `payload` query: [["openFile", "vscode-remote://
//    <host>/c:/.../file:<n>"], ["gotoLineMode", "true"]]. It reveals the START line only (no range).

export interface LineRange {
  start: number;
  end: number;
}

export interface CodeLink {
  folder: string | null;
  file: string | null;
  line: LineRange | null;
  /** Parameters present but unusable, named for the header ("line", "file", "folder"). */
  invalid: string[];
}

/** An absolute folder in code-server's URI-path form, or null when it is not absolute.
 *  `C:\a\b`, `C:/a/b`, `c:\a\b\` and `/C:/a/b` all become `/c:/a/b`; a POSIX `/a/b` stays. */
export function normalizeFolder(raw: string | null | undefined): string | null {
  const s = (raw ?? "").trim().replace(/\\/g, "/");
  if (!s) return null;
  const drive = /^\/?([A-Za-z]):(\/.*)?$/.exec(s);
  let path: string;
  if (drive) path = `/${drive[1].toLowerCase()}:${drive[2] ?? "/"}`;
  else if (s.startsWith("/") && !s.startsWith("//")) path = s;
  else return null; // relative, UNC or garbage: code-server cannot open it as a folder
  path = path.replace(/\/{2,}/g, "/");
  if (path.split("/").some((seg) => seg === "..")) return null;
  if (path.length > 1 && path.endsWith("/") && !/^\/[a-z]:\/$/.test(path)) path = path.slice(0, -1);
  return path;
}

/** A file path relative to the folder: forward slashes, no leading slash, no `..` escape. */
export function normalizeFile(raw: string | null | undefined): string | null {
  const s = (raw ?? "").trim().replace(/\\/g, "/").replace(/^\/+/, "").replace(/\/{2,}/g, "/");
  if (!s || s.endsWith("/")) return null;
  const segs = s.split("/");
  if (segs.some((seg) => seg === ".." || seg === ".")) return null;
  if (/^[A-Za-z]:/.test(s)) return null; // absolute Windows path: not relative to the folder
  return s;
}

/** `10` → 10..10, `10-20` → 10..20 (a reversed range is swapped); anything else is null. */
export function parseLine(raw: string | null | undefined): LineRange | null {
  const m = /^\s*(\d{1,7})\s*(?:[-–]\s*(\d{1,7}))?\s*$/.exec(raw ?? "");
  if (!m) return null;
  const a = Number(m[1]);
  const b = m[2] === undefined ? a : Number(m[2]);
  if (a < 1 || b < 1) return null;
  return { start: Math.min(a, b), end: Math.max(a, b) };
}

export function parseCodeLink(search: string): CodeLink {
  const q = new URLSearchParams(search);
  const invalid: string[] = [];
  const pick = <T,>(key: string, fn: (v: string) => T | null): T | null => {
    const v = q.get(key);
    if (v === null || v === "") return null;
    const out = fn(v);
    if (out === null) invalid.push(key);
    return out;
  };
  const folder = pick("folder", normalizeFolder);
  const file = pick("file", normalizeFile);
  const line = pick("line", parseLine);
  return { folder, file, line, invalid };
}

/** Percent-encode each path segment for a vscode-remote URI; the drive segment `c:` stays literal. */
function encodePath(path: string): string {
  return path
    .split("/")
    .map((seg) => (/^[a-z]:$/.test(seg) ? seg : encodeURIComponent(seg)))
    .join("/");
}

/** The code-server URL for the iframe (and for "Open in new window"). `base` is the service URL
 *  the board reports (`http://127.0.0.1:<port>/`); `fallbackFolder` is the board's own tree. */
export function embedUrl(base: string, link: CodeLink, fallbackFolder: string | null): string {
  const url = new URL(base);
  // An explicitly rejected root must never redirect its relative file into another workspace.
  const folder = link.invalid.includes("folder") ? null : link.folder ?? normalizeFolder(fallbackFolder);
  const params: string[] = [];
  // code-server reads `folder` raw (no `+` decoding): encode with %20 etc., keep `/` and `:` readable
  if (folder) params.push(`folder=${encodeURIComponent(folder).replace(/%2F/g, "/").replace(/%3A/g, ":")}`);
  if (folder && link.file) {
    const target = `vscode-remote://${url.host}${encodePath(`${folder === "/" ? "" : folder}/${link.file}`)}`;
    const payload: [string, string][] = link.line
      ? [["openFile", `${target}:${link.line.start}`], ["gotoLineMode", "true"]]
      : [["openFile", target]];
    params.push(`payload=${encodeURIComponent(JSON.stringify(payload))}`);
  }
  return `${url.origin}/${params.length ? `?${params.join("&")}` : ""}`;
}

/** Is the board page itself served from loopback? The iframe points at the board HOST's loopback,
 *  so from any other machine it would load that machine's port instead (strategyhl-e69dbbae06 §3). */
export function isLoopbackHost(hostname: string): boolean {
  const h = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return h === "localhost" || h === "::1" || /^127(\.\d{1,3}){3}$/.test(h);
}

/** "L10" or "L10–20" for the header. */
export function lineLabel(line: LineRange | null): string {
  if (!line) return "";
  return line.start === line.end ? `L${line.start}` : `L${line.start}–${line.end}`;
}
