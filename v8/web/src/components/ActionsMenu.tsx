import { useCallback, useRef, useState } from "react";
import { AnchoredPanel } from "./AnchoredPanel";
import { Drawer } from "./Drawer";
import { Icon } from "./Icon";
import styles from "./ActionsMenu.module.css";

// "Actions ▾" (revision3-clean topline): the one place the page's controls live. Picking an item
// opens it in the right drawer, so the reading surface never carries seven cards of forms (owner
// defect: "7 ambiguous cards moved down"). Each item carries its copy-contract gloss.

export interface ActionItem {
  key: string;
  label: string;
  /** One line: what it does and who is woken (from copy/pages.ts). */
  gloss: string;
  /** The control, rendered inside the drawer when picked. */
  render: () => React.ReactNode;
  /** A count badge (e.g. answerable decisions). */
  count?: number;
  /** Extra props for the copy contract (title + aria-describedby). */
  copy?: { title: string; "aria-describedby": string; "data-copy": string };
}

export function ActionsMenu({ items, subject }: { items: ActionItem[]; subject: string }): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const anchor = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => setOpen(false), []);
  const active = items.find((i) => i.key === picked) ?? null;
  return <>
    <button ref={anchor} type="button" className={styles.trigger} aria-haspopup="menu" aria-expanded={open}
      onClick={() => setOpen((o) => !o)} data-testid="actions-open">
      Actions <Icon name="chevron" size={16} />
    </button>
    {open ? <AnchoredPanel anchor={anchor} label={`Actions on ${subject}`} heading="Actions" onClose={close} width={340}>
      <ul className={styles.menu} role="menu" data-testid="actions-menu">
        {items.map((item) => <li key={item.key} role="none">
          <button type="button" role="menuitem" className={styles.item} data-testid={`action-${item.key}`}
            onClick={() => { setPicked(item.key); setOpen(false); }} {...item.copy}>
            <span className={styles.itemLabel}>{item.label}{item.count ? <span className={styles.count}>{item.count}</span> : null}</span>
            <span className={styles.itemGloss}>{item.gloss}</span>
          </button>
        </li>)}
      </ul>
    </AnchoredPanel> : null}
    <Drawer open={active !== null} title={active?.label ?? ""} width={640} onClose={() => setPicked(null)} returnFocusTo={anchor.current}>
      {active ? <div className={styles.body} data-testid={`action-drawer-${active.key}`}>
        <p className={styles.drawerGloss}>{active.gloss}</p>
        {active.render()}
      </div> : null}
    </Drawer>
  </>;
}
