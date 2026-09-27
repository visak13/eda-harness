import { useBoardBehind } from "../live/boardVersion";
import ui from "./ui.module.css";

// t-b2f8859d30: a quiet line above the page while this bundle runs ahead of the board (live/boardVersion.ts),
// instead of a page crashing on a route or field the board does not have yet. Gone after the board restarts.
export function BoardVersionBanner(): React.JSX.Element | null {
  const behind = useBoardBehind();
  if (!behind) return null;
  return (
    <p className={ui.banner} role="status" data-testid="board-behind-banner" style={{ margin: "0 0 12px" }}>
      This page needs a board restart (admin). The web app was updated after the board started, so some pages may
      not work until then.
    </p>
  );
}
