// A pure SSE frame parser (strategyll-1a201146c8 §4; WHATWG server-sent events). Fed any string
// chunks; CRLF, CR and LF all end a line; a frame ends at a blank line. A frame with `data:` lines
// yields their joined payload, else its first comment line (`: ready 12` -> "ready 12").

export type Frame = { data?: string; comment?: string };

export function sseParser(onFrame: (f: Frame) => void): (chunk: string) => void {
  let buf = '';
  let pendingCR = false;
  return (chunk: string) => {
    // a CR at the end of one chunk may be the first half of a CRLF split across two chunks
    if (pendingCR && chunk.startsWith('\n')) chunk = chunk.slice(1);
    pendingCR = chunk.endsWith('\r');
    buf += chunk.replace(/\r\n?/g, '\n');
    let i: number;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const lines = buf.slice(0, i).split('\n');
      buf = buf.slice(i + 2);
      const dataLines = lines.filter(l => l.startsWith('data:'));
      if (dataLines.length) { onFrame({ data: dataLines.map(l => l.slice(5).replace(/^ /, '')).join('\n') }); continue; }
      const c = lines.find(l => l.startsWith(':'));
      if (c !== undefined) onFrame({ comment: c.slice(1).trim() });
    }
  };
}

/** `ready 12` / `resync 40` -> the mark and its cursor; anything else (ping) -> undefined. */
export function cursorMark(comment: string | undefined): { mark: 'ready' | 'resync'; cursor: number } | undefined {
  const m = /^(ready|resync)\s+(\d+)/.exec(comment ?? '');
  return m ? { mark: m[1] as 'ready' | 'resync', cursor: Number(m[2]) } : undefined;
}
