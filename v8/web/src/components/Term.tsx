import { useId } from "react";
import { GLOSSARY, label as glossLabel, meaning as glossMeaning, type GlossaryCategory } from "../copy/glossary";
import styles from "./Term.module.css";

// A glossary term rendered plain (design §15): the human label, with its one-line meaning attached
// as an accessible tooltip. The meaning is ALWAYS in the DOM (a `role="tooltip"` span the trigger
// points at with `aria-describedby`), visually revealed on hover and keyboard focus — so a screen
// reader announces it, a mouse user sees it, and a keyboard user reaches it by Tab. When a value is
// not glossed the label falls back to the de-underscored raw value and no tooltip is attached
// (nothing to explain), never a blank.

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
    <span className={`${styles.wrap} ${className ?? ""}`} data-term={`${category}:${value}`}>
      <As className={styles.trigger} tabIndex={0} aria-describedby={id}>
        {text}
      </As>
      <span role="tooltip" id={id} className={styles.tip}>
        {meaning}
      </span>
    </span>
  );
}

/** The set of glossary categories, for a panel/legend to walk. */
export const ALL_CATEGORIES = Object.keys(GLOSSARY) as GlossaryCategory[];
