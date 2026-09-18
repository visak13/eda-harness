import { useCallback, useId, useRef, useState } from "react";
import { GLOSSARY, label as glossLabel, meaning as glossMeaning, type GlossaryCategory } from "../copy/glossary";
import styles from "./Term.module.css";

// A glossary term rendered plain (design §15): the human label, with its one-line meaning attached
// as an accessible tooltip. The meaning is ALWAYS in the DOM (a `role="tooltip"` span the trigger
// points at with `aria-describedby`), visually revealed on hover and keyboard focus — so a screen
// reader announces it, a mouse user sees it, and a keyboard user reaches it by Tab. When a value is
// not glossed the label falls back to the de-underscored raw value and no tooltip is attached
// (nothing to explain), never a blank.
//
// Owner defect (epic-44a0576511, m-f33ab9207d): every tooltip used to render at the viewport's
// bottom-left. The bubble is now ANCHORED to its trigger — above it by default, flipped below when
// there is no room above, and shifted horizontally so it never leaves the viewport.

/** Where to put the bubble for a trigger at `rect`: above unless the top edge is too close. */
export function placeTip(rect: { top: number; left: number; width: number; bottom: number }, tipWidth: number, viewportWidth: number): { below: boolean; shift: number } {
  const below = rect.top < 72;
  const left = rect.left + rect.width / 2 - tipWidth / 2;
  const shift = left < 8 ? 8 - left : left + tipWidth > viewportWidth - 8 ? viewportWidth - 8 - (left + tipWidth) : 0;
  return { below, shift };
}

/** The anchored tooltip wrapper shared by Term and StatusChip. `children` is the trigger. */
export function Tip({ meaning, id, className, children, testId }: {
  meaning: string; id: string; className?: string; children: React.ReactNode; testId?: string;
}): React.JSX.Element {
  const tipRef = useRef<HTMLSpanElement>(null);
  const [placement, setPlacement] = useState<{ below: boolean; shift: number }>({ below: false, shift: 0 });
  const place = useCallback((e: React.SyntheticEvent<HTMLElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const width = tipRef.current?.offsetWidth || 220;
    setPlacement(placeTip(rect, width, window.innerWidth || 1440));
  }, []);
  return (
    <span className={`${styles.wrap} ${className ?? ""}`} onMouseEnter={place} onFocus={place} data-testid={testId}>
      {children}
      <span
        ref={tipRef}
        role="tooltip"
        id={id}
        className={styles.tip}
        data-placement={placement.below ? "below" : "above"}
        style={{ transform: `translateX(calc(-50% + ${placement.shift}px))` }}
      >
        {meaning}
      </span>
    </span>
  );
}

export function Term({
  category,
  value,
  className,
  as: As = "span",
}: {
  category: GlossaryCategory;
  value: string;
  className?: string;
  as?: "span" | "strong";
}): React.JSX.Element {
  const id = useId();
  const text = glossLabel(category, value);
  const meaning = glossMeaning(category, value);
  if (!meaning) {
    return (
      <As className={className} data-term={`${category}:${value}`}>
        {text}
      </As>
    );
  }
  return (
    <Tip meaning={meaning} id={id} className={className}>
      <As className={styles.trigger} tabIndex={0} aria-describedby={id} data-term={`${category}:${value}`}>
        {text}
      </As>
    </Tip>
  );
}

/** The set of glossary categories, for a panel/legend to walk. */
export const ALL_CATEGORIES = Object.keys(GLOSSARY) as GlossaryCategory[];
