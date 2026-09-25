import { Link, useInRouterContext, useLocation } from "react-router";
import { kindLabel, refHref, splitRefs, type RefPart } from "./boardRefs";
import styles from "./RefText.module.css";

// C24 (s-5d1b171d57): `$<id>` references in plain text (a plain-text message, a quote's note) as link chips —
// the same chip the Markdown path builds (Markdown.tsx refChip): label or id, kind as data, id in the tooltip.

function RoutedChip({ r }: { r: Exclude<RefPart, string> }): React.JSX.Element {
  const here = useLocation().pathname;
  return (
    <Link to={refHref(r.id, r.kind, here)} className={`ref-chip ${styles.chip}`} data-ref={r.id} data-kind={r.kind}
      data-testid="ref-chip" title={`${kindLabel(r.kind)} $${r.id}`}>
      {r.label ? `${kindLabel(r.kind)} · ${r.label}` : `$${r.id}`}
    </Link>
  );
}

export function RefText({ text }: { text: string }): React.JSX.Element {
  const routed = useInRouterContext();
  const parts = splitRefs(text);
  if (parts.length === 1 && typeof parts[0] === "string") return <>{text}</>;
  return (
    <>
      {parts.map((p, i) => (typeof p === "string" ? <span key={i}>{p}</span>
        : routed ? <RoutedChip key={i} r={p} /> : <span key={i} className={`ref-chip ${styles.chip}`} data-ref={p.id}>{p.label ?? `$${p.id}`}</span>))}
    </>
  );
}
