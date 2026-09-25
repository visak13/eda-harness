import { kindLabel, type RefRow } from "./boardRefs";
import type { BoardRefs } from "./useBoardRefs";

// C24: the $ picker's listbox, drawn with the host's @ menu classes (the composer's .mentions, a note's .menu)
// so both pickers look alike. Each row: kind, id, title; the current scope's rows come first.
export function RefMenu({ refs, listId, className, activeClass, handleClass, labelClass, testId = "refs-menu" }: {
  refs: BoardRefs;
  listId: string;
  className: string;
  activeClass: string;
  handleClass: string;
  labelClass: string;
  testId?: string;
}): React.JSX.Element | null {
  if (!refs.menu.open) return null;
  return (
    <ul id={listId} className={className} role="listbox" aria-label="Board objects" data-testid={testId}>
      {refs.menu.items.map((r: RefRow, i) => (
        <li key={r.id} id={`${listId}-${i}`} role="option" aria-selected={i === refs.menu.index}
          aria-label={`${kindLabel(r.kind)} ${r.id} ${r.title}${r.group === "board" ? " (other work)" : ""}`}
          className={i === refs.menu.index ? activeClass : ""} data-ref={r.id} data-group={r.group}
          onMouseDown={(e) => { e.preventDefault(); refs.accept(r); }}>
          <span className={handleClass} data-kind={r.kind}>{kindLabel(r.kind)} ${r.id}</span>
          <span className={labelClass}>{r.title}</span>
        </li>
      ))}
    </ul>
  );
}
