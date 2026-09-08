import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { identity } from "../auth/identity";
import { subscribeFeed } from "../live/feed";
import { ThemePicker } from "../theme/ThemePicker";
import { Icon } from "./Icon";
import styles from "./AppShell.module.css";

interface WhoAmI {
  participant: { id: string; handle: string; role: string };
}
interface Summary {
  decisions?: number;
  epics?: number;
  seats?: number;
  library?: number;
}
interface EpicInView {
  id: string;
  title: string;
}

// Nav order is fixed (design §4.2): Decisions, Epics, Seats, Library. `count` names the
// key read from /v1/me/summary; that endpoint belongs to G1a, so counts render only when
// present — the shell works (and fidelity holds) whether or not it has landed.
const NAV = [
  { to: "/me", label: "Decisions", icon: "decisions", count: "decisions" as const },
  { to: "/epics", label: "Epics", icon: "epics", count: "epics" as const },
  { to: "/seats", label: "Seats", icon: "seats", count: "seats" as const },
  { to: "/library/tickets", label: "Library", icon: "library", count: "library" as const },
] as const;

function crumbFor(pathname: string): string {
  if (pathname.startsWith("/epic")) return "Epic";
  if (pathname.startsWith("/epics")) return "Epics";
  if (pathname.startsWith("/seats")) return "Seats";
  if (pathname.startsWith("/library")) return "Library";
  if (pathname.startsWith("/ticket")) return "Ticket";
  if (pathname.startsWith("/doc")) return "Document";
  return "Decisions";
}

export function AppShell(): React.JSX.Element {
  const qc = useQueryClient();
  const location = useLocation();
  const as = identity();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [newEvents, setNewEvents] = useState(0);
  const identityRef = useRef<HTMLDivElement>(null);

  // Seam 1+2 proof + identity display: an authenticated /v1 call that succeeds on a
  // seeded board (unlike summary, which is G1a's). Falls back to `as` if it errors.
  const whoami = useQuery({
    queryKey: ["whoami"],
    queryFn: () => api<WhoAmI>("/v1/whoami"),
    retry: false,
  });
  const summary = useQuery({
    queryKey: ["me", "summary"],
    queryFn: () => api<Summary>("/v1/me/summary"),
    retry: false,
  });
  const inView = useQuery({
    queryKey: ["me", "epics-in-view"],
    queryFn: () => api<EpicInView[]>("/v1/epics/summary"),
    retry: false,
  });

  // Live plane: feed events invalidate server-state queries; a visible "N new" pill is the
  // parity stub for the legacy live pill (G2 turns it into the draft-guarded refresh).
  useEffect(() => {
    const stop = subscribeFeed(
      () => {
        setNewEvents((n) => n + 1);
        qc.invalidateQueries();
      },
      { onError: () => void 0 },
    );
    return stop;
  }, [qc]);

  // Close the identity popover on outside click / Escape.
  useEffect(() => {
    if (!popoverOpen) return;
    const onDown = (e: MouseEvent) => {
      if (identityRef.current && !identityRef.current.contains(e.target as Node)) setPopoverOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPopoverOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [popoverOpen]);

  const handle = whoami.data?.participant.handle ?? as;
  const role = whoami.data?.participant.role ?? "";
  const counts = summary.data;

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar} aria-label="Primary">
        <div className={styles.brand}>
          <span className={styles.brandmark} aria-hidden="true">
            e
          </span>
          <span>edp8</span>
        </div>
        <div className={styles.workspaceName}>Fleet workspace</div>

        <nav className={styles.nav} aria-label="Sections">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ""}`}
            >
              <span className={styles.icon} data-nav-icon>
                <Icon name={item.icon} />
              </span>
              <span className={styles.navLabel}>{item.label}</span>
              {counts && typeof counts[item.count] === "number" ? (
                <span className={styles.count}>{counts[item.count]}</span>
              ) : null}
            </NavLink>
          ))}
        </nav>

        <button className={styles.find} type="button" aria-label="Find (Ctrl-K)">
          <span className={styles.icon}>
            <Icon name="find" />
          </span>
          <span className={styles.findLabel}>Find</span>
          <span className={styles.key}>Ctrl K</span>
        </button>

        {inView.data && inView.data.length > 0 ? (
          <>
            <div className={styles.sectionLabel}>In view</div>
            {inView.data.slice(0, 4).map((e) => (
              <div key={e.id} className={styles.miniEpic}>
                <span className={styles.dot} aria-hidden="true" />
                <span>{e.title}</span>
              </div>
            ))}
          </>
        ) : null}

        <div className={styles.identity} ref={identityRef}>
          <button
            className={styles.identityBtn}
            type="button"
            aria-label="Account and preferences"
            aria-haspopup="dialog"
            aria-expanded={popoverOpen}
            onClick={() => setPopoverOpen((o) => !o)}
          >
            <span className={styles.avatar} aria-hidden="true">
              {handle.slice(0, 1).toUpperCase()}
            </span>
            <span>
              <span className={styles.identityName} data-testid="identity">
                {as}
              </span>
              <br />
              <span className={styles.identityRole} data-testid="whoami-handle">
                {handle}
              </span>
              {role ? <span className={styles.identityRole}> · {role}</span> : null}
            </span>
          </button>
          {popoverOpen ? (
            <div className={styles.popover} role="dialog" aria-label="Preferences">
              <ThemePicker />
            </div>
          ) : null}
        </div>
      </aside>

      <header className={styles.header} data-testid="app-header">
        <div className={styles.breadcrumb}>
          <span>Workspace</span>
          <span aria-hidden="true">/</span>
          <span className={styles.here}>{crumbFor(location.pathname)}</span>
        </div>
        <div className={styles.headerRight}>
          {newEvents > 0 ? (
            <button
              className={styles.btnPrimary}
              type="button"
              data-testid="live-new"
              aria-live="polite"
              onClick={() => setNewEvents(0)}
            >
              {newEvents} new · refresh
            </button>
          ) : (
            <button className={styles.btnPrimary} type="button">
              New epic
            </button>
          )}
        </div>
      </header>

      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
