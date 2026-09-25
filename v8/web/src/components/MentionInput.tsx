import { useQuery } from "@tanstack/react-query";
import { useId, useRef } from "react";
import { getPeople } from "../api/endpoints";
import styles from "./MentionInput.module.css";
import { useMentions } from "./useMentions";
import { useBoardRefs } from "./useBoardRefs";
import { RefMenu } from "./RefMenu";

// C23 (s-93ddb7fd1a, owner m-5a9111ce12): a quote's note takes @mentions like the composer. A one-line
// input with the composer's @ picker (useMentions over the one /v1/me/people list, same keys: ↑/↓ move,
// Enter/Tab pick, Esc closes). The board resolves a note's @handles like the text's, so a picked
// person is woken. `#` stays plain text in the board UI (architect ruling m-ef7cdf6dec).
// C24 (s-5d1b171d57): `$` opens the board-object picker here too (useBoardRefs, same keys).

type Props = Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
  value: string;
  onValue: (next: string) => void;
  inputRef?: React.RefObject<HTMLInputElement | null>;
  menuTestId?: string;
  /** class of the wrapper (the flex item); `className` styles the input itself */
  wrapClassName?: string;
  /** C24: the ticket whose epic ranks first in the $ list (default: the page's :id) */
  ticketId?: string | null;
};

export function MentionInput({ value, onValue, inputRef, menuTestId = "note-mentions-menu", ticketId, onKeyDown, className, wrapClassName, ...rest }: Props): React.JSX.Element {
  const own = useRef<HTMLInputElement>(null);
  const ref = inputRef ?? own;
  const people = useQuery({ queryKey: ["me", "people"], queryFn: getPeople, retry: false });
  const mentions = useMentions(people.data ?? [], ref, onValue);
  const refs = useBoardRefs(ticketId, ref, onValue);
  const listId = useId();
  const refListId = useId();
  const open = mentions.menu.open;
  const refsOpen = !open && refs.menu.open;
  const refresh = () => { mentions.refresh(); refs.refresh(); };
  return (
    <span className={`${styles.wrap} ${wrapClassName ?? ""}`}>
      <input
        {...rest}
        ref={ref}
        className={`${styles.field} ${className ?? ""}`}
        value={value}
        onChange={(e) => onValue(e.target.value)}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open || refsOpen}
        aria-controls={open ? listId : refsOpen ? refListId : undefined}
        aria-activedescendant={open ? `${listId}-${mentions.menu.index}` : refsOpen ? `${refListId}-${refs.menu.index}` : undefined}
        data-mentions-open={open || refsOpen || undefined}
        onKeyDown={(e) => {
          if (!e.nativeEvent.isComposing && (mentions.onKeyDown(e) || (!open && refs.onKeyDown(e)))) { e.stopPropagation(); return; }
          onKeyDown?.(e);
        }}
        onKeyUp={refresh}
        onClick={refresh}
        onBlur={() => { mentions.close(); refs.close(); }}
      />
      {open ? (
        <ul id={listId} className={styles.menu} role="listbox" data-testid={menuTestId}>
          {mentions.menu.items.map((p, i) => (
            <li key={p.id} id={`${listId}-${i}`} role="option" aria-selected={i === mentions.menu.index}
              className={i === mentions.menu.index ? styles.active : ""}
              onMouseDown={(e) => { e.preventDefault(); mentions.accept(p); }}>
              <span className={styles.handle}>@{p.handle}</span>
              <span className={styles.label}>{p.label}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {refsOpen ? <RefMenu refs={refs} listId={refListId} className={styles.menu} activeClass={styles.active}
        handleClass={styles.handle} labelClass={styles.label} testId={menuTestId.replace("mentions", "refs")} /> : null}
    </span>
  );
}
