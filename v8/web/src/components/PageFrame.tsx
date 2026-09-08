import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { GlossaryCategory } from "../copy/glossary";

// Plain language rule (design §15): every page opens with ONE sentence — what this is, what you can
// do here — rendered in a landmark a reader (and a test) can find, and it declares which glossary
// terms are visible on it so the "What am I looking at?" panel lists only those. A page registers
// both with `usePageFrame`; the landmark and the panel read them from this context.

export interface TermRef {
  category: GlossaryCategory;
  value: string;
}

interface PageFrame {
  framing: string | null;
  terms: TermRef[];
}
interface Ctx extends PageFrame {
  setFrame: (f: PageFrame | null) => void;
}

const PageFrameContext = createContext<Ctx | null>(null);

export function PageFrameProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [frame, setFrame] = useState<PageFrame | null>(null);
  const value = useMemo<Ctx>(
    () => ({ framing: frame?.framing ?? null, terms: frame?.terms ?? [], setFrame }),
    [frame],
  );
  return <PageFrameContext.Provider value={value}>{children}</PageFrameContext.Provider>;
}

export function usePageFrameCtx(): Ctx {
  const c = useContext(PageFrameContext);
  if (!c) throw new Error("usePageFrameCtx must be used inside PageFrameProvider");
  return c;
}

/** A page declares its framing sentence and the glossary terms it shows. Registered on mount,
 *  cleared on unmount so a route change never leaves a stale sentence or term list behind. */
export function usePageFrame(framing: string, terms: TermRef[] = []): void {
  const { setFrame } = usePageFrameCtx();
  // Serialise terms so the effect only re-runs when the actual content changes, not each render.
  const key = terms.map((t) => `${t.category}:${t.value}`).join(",");
  useEffect(() => {
    setFrame({ framing, terms });
    return () => setFrame(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [framing, key, setFrame]);
}

// Default framing per route, used until (or if) a page registers its own. Guarantees the
// criterion "every route renders a page-framing sentence in a landmark" even before a page opts in.
export function defaultFraming(pathname: string): string {
  if (pathname.startsWith("/epic/")) return "One epic: its goal, its work, and what needs a decision.";
  if (pathname.startsWith("/epics")) return "Every project on the board and how far each has got.";
  if (pathname.startsWith("/seats")) return "See who is available, read their latest status, and message or resume a seat.";
  if (pathname.startsWith("/ticket/")) return "One story: review its criteria, read its evidence, and move it forward.";
  if (pathname.startsWith("/doc/")) return "Read a document and record your sign-off on its criteria.";
  if (pathname.startsWith("/library")) return "Browse the board's tickets, documents, artifacts, links and history.";
  return "Decisions collects requests that need your action. Read the ask, then answer or review its evidence.";
}
