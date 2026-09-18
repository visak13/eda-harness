import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useSearchParams } from "react-router";
import { Drawer } from "./Drawer";

/** A stable portal host moves, not the React composer: uploads, retry Files,
 * selection, recipient and mutations survive expansion without serialization. */
export function ExpandableComposer({ title, children }: {
  title: string;
  children: (expand: { expanded: boolean; onToggle: () => void }) => React.ReactNode;
}): React.JSX.Element {
  const [params, setParams] = useSearchParams();
  const expanded = params.get("compose") === "1" && !params.get("doc");
  const inline = useRef<HTMLDivElement>(null);
  const modal = useRef<HTMLDivElement>(null);
  const [host] = useState(() => document.createElement("div"));
  function change(on: boolean) {
    setParams(old => { const next = new URLSearchParams(old); if (on) next.set("compose", "1"); else next.delete("compose"); return next; }, { replace: true });
  }
  useLayoutEffect(() => {
    const focused = host.contains(document.activeElement) ? document.activeElement as HTMLElement : null;
    (expanded ? modal.current : inline.current)?.appendChild(host);
    focused?.focus();
  }, [expanded, host]);
  return <>
    <div ref={inline} />
    {expanded ? <p data-testid="composer-expanded-note">The composer is open in the drawer. <button type="button" onClick={() => change(false)}>Bring it back here</button></p> : null}
    <Drawer open={expanded} title={title} onClose={() => change(false)}>
      <div ref={modal} data-testid="composer-drawer" />
    </Drawer>
    {createPortal(children({ expanded, onToggle: () => change(!expanded) }), host)}
  </>;
}
