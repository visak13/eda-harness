import { useBoardSkew } from "../live/boardVersion";
import ui from "./ui.module.css";

// t-b2f8859d30: a quiet line above the page while this bundle runs ahead of the board (live/boardVersion.ts),
// instead of a page crashing on a route or field the board does not have yet. Gone after the board restarts.
// owner m-7411cee472: a page left open across an update says so, and offers the reload (never forces it).
export function BoardVersionBanner(): React.JSX.Element | null {
  const { behind, updated } = useBoardSkew();
  if (!behind && !updated) return null;
  return (
    <>
      {behind ? (
        <p className={ui.banner} role="status" data-testid="board-behind-banner" style={{ margin: "0 0 12px" }}>
          This page needs a board restart (admin). The web app was updated after the board started, so some pages may
          not work until then.
        </p>
      ) : null}
      {updated ? (
        <p className={`${ui.banner} ${ui.bannerInfo}`} role="status" data-testid="board-updated-banner" style={{ margin: "0 0 12px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span>Heronry was updated. Reload to get the new version.</span>
          <button type="button" className={ui.button} onClick={() => window.location.reload()}>Reload</button>
        </p>
      ) : null}
    </>
  );
}
