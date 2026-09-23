import { useCallback, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { AnchoredPanel } from "./AnchoredPanel";
import { Icon } from "./Icon";
import type { WorkContext } from "./ContextualWork";
import styles from "./AttentionAsks.module.css";

// S-UI (owner m-ec5a9b86c5 "the unanswered question alert is unclickable so I dont know what I
// unanswered"): the "N unanswered request(s)" badge is a control. One ask: a click scrolls the
// conversation to it and highlights it. Several: a click opens the list (oldest first), each row jumps.
// The jump sets the #m-<id> hash, so a message older than the loaded window is fetched in place
// (the page's ?include) and the scroll lands once it renders.

type Ask = NonNullable<WorkContext["unresolved_asks"]>[number];

export const HIGHLIGHT_ATTR = "data-highlight";

/** Scroll to the message and mark it (one highlighted message at a time). */
export function highlightMessage(id: string): boolean {
  document.querySelectorAll(`[${HIGHLIGHT_ATTR}]`).forEach((el) => el.removeAttribute(HIGHLIGHT_ATTR));
  const el = document.getElementById(id);
  if (!el) return false;
  if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "center", behavior: "smooth" }); // jsdom has none
  el.setAttribute(HIGHLIGHT_ATTR, "true");
  return true;
}

function ago(at?: string): string {
  if (!at) return "";
  const mins = Math.max(0, Math.round((Date.now() - Date.parse(at)) / 60000));
  return mins < 60 ? `${mins} min ago` : mins < 60 * 48 ? `${Math.round(mins / 60)} h ago` : `${Math.round(mins / 1440)} d ago`;
}

export function AttentionAsks({ asks }: { asks: Ask[] }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const close = useCallback(() => setOpen(false), []);
  const label = `${asks.length} unanswered request${asks.length === 1 ? "" : "s"}`;

  function jump(id: string) {
    setOpen(false);
    // on the page: mark it now (no navigation, so the page never refetches). Older than the loaded
    // window: the #m- hash makes the page fetch it in place (?include) and the retry marks it.
    if (highlightMessage(id)) return;
    if (location.hash !== `#${id}`) navigate({ search: location.search, hash: id }, { replace: true });
    for (const wait of [400, 1200, 2500]) window.setTimeout(() => highlightMessage(id), wait);
  }

  return <>
    <button ref={anchor} type="button" className={styles.badge} data-testid="attention-asks"
      aria-haspopup={asks.length > 1 ? "dialog" : undefined} aria-expanded={asks.length > 1 ? open : undefined}
      title={asks.length === 1 ? "Show the request in the conversation" : "List the requests"}
      onClick={() => (asks.length === 1 ? jump(asks[0].id) : setOpen((o) => !o))}>
      {label}
    </button>
    {open ? <AnchoredPanel anchor={anchor} label="Unanswered requests" heading="Unanswered requests" onClose={close} width={380}>
      <ul className={styles.list} data-testid="attention-asks-list">
        {asks.map((a) => (
          <li key={a.id}>
            <button type="button" className={styles.row} data-testid="attention-ask" data-ask={a.id} onClick={() => jump(a.id)}>
              <span className={styles.meta}><Icon name="review-request" size={16} />
                {a.kind} to {a.to}{a.by ? ` · from ${a.by}` : ""}{a.at ? ` · ${ago(a.at)}` : ""}</span>
              {a.text ? <span className={styles.text}>{a.text}</span> : null}
            </button>
          </li>
        ))}
      </ul>
    </AnchoredPanel> : null}
  </>;
}
