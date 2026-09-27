import { Link, useRouteError } from "react-router";
import { useBoardBehind } from "../live/boardVersion";
import ui from "./ui.module.css";

// t-b2f8859d30 (owner art-678346d6e2): a render error on one page used to replace the whole app with the router's
// "Unexpected Application Error!". This is the errorElement of the shell's page routes (routes.tsx): the error
// shows as a card in the page's place, and the rail, the account menu and every other page keep working.
// Moving to another page clears it (the router drops the error on navigation).

function messageOf(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (err && typeof err === "object" && "statusText" in err) return String((err as { statusText: unknown }).statusText);
  return String(err ?? "unknown error");
}

export function PageError(): React.JSX.Element {
  const err = useRouteError();
  const behind = useBoardBehind();
  return (
    <section className={ui.card} role="alert" data-testid="page-error">
      <h1 style={{ margin: "0 0 8px", fontSize: 20 }}>This page hit an error</h1>
      <p className={ui.empty} data-testid="page-error-message">{messageOf(err)}</p>
      {behind ? (
        <p className={ui.empty} data-testid="page-error-board-behind">
          This page is newer than the board, which is the likely cause. It needs a board restart (admin).
        </p>
      ) : null}
      <p style={{ display: "flex", gap: 16, margin: "12px 0 0" }}>
        <a href={typeof window === "undefined" ? "." : window.location.href} data-testid="page-error-reload"
          onClick={(e) => { e.preventDefault(); window.location.reload(); }}>Reload this page</a>
        <Link to="/epics">Go to Epics</Link>
      </p>
    </section>
  );
}
