import { attentionLabel } from "../api/attention";
import styles from "./AttentionDot.module.css";

// S20 attention trail (design-e963c656f5 §4.18): the same dot at every hop from the rail to the item. A dot glyph plus
// the count plus an aria-label ("needs your attention: 2"), never colour alone. Renders nothing at zero.
export function AttentionDot({ count, bare = false }: { count: number; bare?: boolean }): React.JSX.Element | null {
  if (count <= 0) return null;
  return (
    <span className={`${styles.dot} ${bare ? styles.bare : ""}`} role="img" aria-label={attentionLabel(count)}
      title={attentionLabel(count)} data-attention-dot={count}>
      {bare ? null : count}
    </span>
  );
}

/** Class for the element that holds an item on the trail (row, opener, item), paired with data-attention="true". */
export const attentionMark = styles.mark;
