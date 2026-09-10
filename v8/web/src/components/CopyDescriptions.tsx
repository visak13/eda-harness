import { PAGES, SIDEBAR, copyId } from "../copy/pages";

// The aria-describedby targets for every control's "does / wakes" line (human defect #31): one
// visually-hidden <span id="copy-<page>-<key>"> per copy item, rendered by the shell for the
// sidebar and the current page. Controls point at them through copyProps().
export function CopyDescriptions({ page }: { page: string }): React.JSX.Element {
  const pages = [SIDEBAR, ...(PAGES[page] ? [PAGES[page]] : [])];
  return (
    <div hidden data-testid="copy-descriptions">
      {pages.flatMap((p) =>
        p.items.map((i) => (
          <span key={`${p.key}.${i.key}`} id={copyId(p.key, i.key)}>
            {i.label} — {i.text}
          </span>
        )),
      )}
    </div>
  );
}
