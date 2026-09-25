import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import type { QuoteIn } from "../api/types";
import { getDocSource, getQuotesSupported } from "../api/endpoints";
import { contextOf, linesOf, locateInSource, utf8Bytes } from "./quoteMatch";
import { activeQuoteTarget, MAX_TRAY, quoteTray } from "./quoteTray";
import styles from "./QuoteLayer.module.css";

// C19 (design-10b21760d9 §14.5/§14.7): select text in a doc (DocView, any type, any version) or in a
// chat message, and a small popover offers Quote with an optional note (also Ctrl+Shift+Q). Quote
// maps the rendered selection back to the markdown source (quoteMatch) and adds a chip to the current
// thread's composer (quoteTray). One layer for the whole app; a region opts in with quoteRegionRef.
// A board without quotes (pre-C18) gets no popover at all (steer m-5a2ea5c4e5 §3).

export interface QuoteRegion {
  kind: "doc" | "message";
  id: string;
  /** Doc version shown (doc regions). */
  version?: number;
  /** The thread a message belongs to, or the ticket a doc is scoped to (fallback target). */
  ticketId?: string | null;
  /** A message's author (the chip label). */
  author?: string;
  /** A message's markdown source (a doc's is fetched per version). */
  text?: string;
}

const regions = new WeakMap<Element, QuoteRegion>();

/** Ref callback that makes an element a quotable region. */
export function quoteRegionRef(region: QuoteRegion | null): (el: HTMLElement | null) => void {
  return (el) => {
    if (!el) return;
    if (region) { regions.set(el, region); el.setAttribute("data-quote-region", region.kind); }
    else { regions.delete(el); el.removeAttribute("data-quote-region"); }
  };
}

const docSources = new Map<string, Promise<string>>();
/** One doc version's markdown source, fetched once per version (versions are immutable). */
export function docSource(id: string, version: number): Promise<string> {
  const key = `${id}@${version}`;
  let p = docSources.get(key);
  if (!p) {
    p = getDocSource(id, version).then((d) => (d.body_md ?? "").replace(/\r\n/g, "\n"));
    p.catch(() => docSources.delete(key));
    docSources.set(key, p);
  }
  return p;
}

function regionOf(node: Node | null): { el: HTMLElement; region: QuoteRegion } | null {
  let el: Element | null = node instanceof Element ? node : node?.parentElement ?? null;
  el = el?.closest("[data-quote-region]") ?? null;
  const region = el ? regions.get(el) : undefined;
  return el && region ? { el: el as HTMLElement, region } : null;
}

interface Picked {
  region: QuoteRegion;
  selected: string;
  before: string;
  rect: { left: number; top: number; bottom: number };
  /** Where the popover renders: the modal dialog holding the region (a Drawer inerts everything
   *  outside its panel), else the body. */
  host: HTMLElement;
}

/** The live selection when it lies inside ONE quotable region, else null. */
function currentPick(): Picked | null {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  const a = regionOf(range.startContainer);
  const b = regionOf(range.endContainer);
  if (!a || !b || a.el !== b.el) return null;
  const selected = range.toString();
  if (!selected.trim()) return null;
  const pre = document.createRange();
  pre.selectNodeContents(a.el);
  pre.setEnd(range.startContainer, range.startOffset);
  const r = range.getBoundingClientRect();
  const host = a.el.closest<HTMLElement>("[role=dialog][aria-modal=true]") ?? document.body;
  return { region: a.region, selected, before: pre.toString(), rect: { left: r.left, top: r.top, bottom: r.bottom }, host };
}

/** Resolve a pick into the quote the board will verify, or a reason it cannot be quoted. */
export async function resolvePick(p: Pick<Picked, "region" | "selected" | "before">, note: string): Promise<{ quote: QuoteIn; label: string } | { error: string }> {
  const { region } = p;
  const src = region.kind === "doc" ? await docSource(region.id, region.version!) : (region.text ?? "");
  const span = locateInSource(src, p.selected, p.before);
  if (!span) return { error: "This passage could not be matched to its source. Select text inside one paragraph, list or table." };
  if (utf8Bytes(span.text) > 4096) return { error: "This passage is longer than 4096 bytes. Select a shorter passage." };
  const n = note.trim() ? { note: note.trim() } : {};
  if (region.kind === "doc") {
    const lines = linesOf(src, span);
    const ctx = contextOf(src, lines.line_start, lines.line_end);
    return {
      quote: { source: "doc", id: region.id, version: region.version!, locator: lines, text: span.text,
        ...(ctx.before || ctx.after ? { context: ctx } : {}), ...n },
      label: `${region.id} v${region.version} L${lines.line_start}${lines.line_end > lines.line_start ? `-${lines.line_end}` : ""}`,
    };
  }
  return {
    quote: { source: "message", id: region.id, locator: { char_start: span.start, char_end: span.end }, text: span.text, ...n },
    label: `${region.id}${region.author ? ` (${region.author})` : ""}`,
  };
}

export function QuoteLayer(): React.JSX.Element | null {
  const supported = useQuery({ queryKey: ["board", "quotes-supported"], queryFn: getQuotesSupported, retry: false, staleTime: 5 * 60_000 });
  const [pick, setPick] = useState<Picked | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const noteRef = useRef<HTMLInputElement>(null);
  const on = supported.data === true;

  const close = useCallback(() => { setPick(null); setNote(""); setError(null); setBusy(false); }, []);
  const open = useCallback((focusNote: boolean) => {
    const p = currentPick();
    if (!p) return false;
    setPick(p); setNote(""); setError(null); setDone(null);
    if (focusNote) requestAnimationFrame(() => noteRef.current?.focus());
    return true;
  }, []);

  useEffect(() => {
    if (!on) return;
    const inBox = (t: EventTarget | null) => t instanceof Node && Boolean(boxRef.current?.contains(t));
    const onUp = (e: MouseEvent) => { if (!inBox(e.target)) setTimeout(() => { if (!open(false)) close(); }, 0); };
    const onKeyUp = (e: KeyboardEvent) => { if (e.shiftKey && !inBox(e.target) && e.key.startsWith("Arrow")) open(false); };
    const onDown = (e: MouseEvent) => { if (!inBox(e.target)) setDone(null); };
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && (e.key === "Q" || e.key === "q")) {
        if (inBox(e.target)) return; // the note field handles its own
        if (open(true)) e.preventDefault();
      }
    };
    document.addEventListener("mouseup", onUp);
    document.addEventListener("keyup", onKeyUp);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("keyup", onKeyUp);
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [on, open, close]);

  async function add() {
    if (!pick || busy) return;
    const target = pick.region.kind === "message" ? pick.region.ticketId : activeQuoteTarget() ?? pick.region.ticketId;
    if (!target) { setError("Open a ticket or epic conversation first; the quote goes to its message box."); return; }
    setBusy(true); setError(null);
    try {
      const r = await resolvePick(pick, note);
      if ("error" in r) { setError(r.error); return; }
      if (!quoteTray.add(target, r.quote, r.label)) { setError(`A message carries at most ${MAX_TRAY} quotes. Send these first.`); return; }
      const n = quoteTray.get(target).length;
      window.getSelection()?.removeAllRanges();
      close();
      setDone(`Quoted into the ${target} message box (${n} ${n === 1 ? "quote" : "quotes"}).`);
    } catch (e) {
      setError(`Could not read the source: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  if (!on) return null;
  if (!pick) return done ? <p className={styles.toast} role="status" data-testid="quote-added">{done}</p> : null;
  let left = Math.max(8, Math.min(pick.rect.left, window.innerWidth - 340));
  const below = pick.rect.bottom + 8;
  let top = below + 120 > window.innerHeight ? Math.max(8, pick.rect.top - 128) : below;
  // position:fixed resolves against a transformed/filtered ancestor, not the viewport: offset by it.
  if (pick.host !== document.body) {
    const cs = getComputedStyle(pick.host);
    if (cs.transform !== "none" || cs.filter !== "none" || cs.perspective !== "none" || cs.contain.includes("paint")) {
      const hr = pick.host.getBoundingClientRect();
      left -= hr.left; top -= hr.top;
    }
  }
  return createPortal(
    <div ref={boxRef} className={styles.popover} style={{ left, top }} role="dialog" aria-label="Quote the selection"
      data-testid="quote-popover"
      onKeyDown={(e) => {
        if (e.key === "Escape") { e.stopPropagation(); close(); }
        if (e.key === "Enter" || (e.ctrlKey && e.shiftKey && (e.key === "Q" || e.key === "q"))) { e.preventDefault(); void add(); }
      }}>
      <input ref={noteRef} className={styles.note} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000}
        placeholder="Note on this passage (optional)" aria-label="Note on this passage" data-testid="quote-note" />
      <button type="button" className={styles.quote} onClick={() => void add()} disabled={busy} data-testid="quote-add"
        title="Quote (Ctrl+Shift+Q)">
        {busy ? "Quoting…" : "Quote"}
      </button>
      {error ? <p className={styles.error} role="alert" data-testid="quote-error">{error}</p> : null}
    </div>,
    pick.host,
  );
}
