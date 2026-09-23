import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api, BoardApiError } from "../api/client";
import { getEpicPage, getTicketPage } from "../api/endpoints";
import { identity } from "../auth/identity";
import { IdentityPanel } from "./IdentityPanel";
import { DraftGuardProvider, useDraftGuard } from "../live/useDraftGuard";
import { DocDrawerProvider } from "./DocDrawer";
import { ThemePicker } from "../theme/ThemePicker";
import { AvatarPicker } from "./AvatarPicker";
import { AnchoredPanel } from "./AnchoredPanel";
import { Avatar } from "./Avatar";
import { Icon } from "./Icon";
import { PageFrameProvider, usePageFrameCtx, defaultFraming } from "./PageFrame";
import { GlossaryPanel } from "./GlossaryPanel";
import { CommandPalette } from "./CommandPalette";
import { CopyDescriptions } from "./CopyDescriptions";
import { PendingNavigation } from "./PendingNavigation";
import { NotificationCenter } from "./NotificationCenter";
import { UsageWidget } from "./UsageWidget";
import { useViewerFlag } from "./viewerPrefs";
import { copyProps, pageKeyFor } from "../copy/pages";
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

// The rail per revision3-clean (design-a2e5369133 §AppShell): brand, Epics, Seats, a divider,
// Needs you with its coral count, the CURRENT EPIC block, then (lower) Usage directly above Find
// and the account row. Notifications are NOT a rail item (finding 6): Enable/Test live on
// Settings → Notifications (S17), the worker/authorization run in the always-mounted provider.
// There is NO global header any more (owner defect: "the epic header takes many pixels for two
// buttons"): New epic lives on the Epics page, preferences in the account menu, help is the floating
// top-right button (S17), and a pending live refresh is an inline banner at the top of main.
const NAV = [
  { to: "/epics", label: "Epics", icon: "epics", count: "epics" as const, copy: "epics" },
  { to: "/seats", label: "Seats", icon: "seats", count: "seats" as const, copy: "seats" },
] as const;

// Human #38 (m-4e303d7b27, 2026-09-11): the sidebar highlight is by ROUTE FAMILY, not by exact path.
export function navFamily(pathname: string): "/me" | "/epics" | "/seats" | "/library/tickets" | "/settings" | null {
  if (pathname === "/me" || pathname.startsWith("/me/")) return "/me";
  if (/^\/(epics|epic|ticket|records)(\/|$)/.test(pathname)) return "/epics";
  if (/^\/seats(\/|$)/.test(pathname)) return "/seats";
  if (/^\/(library|doc|artifact)(\/|$)/.test(pathname)) return "/library/tickets";
  if (/^\/settings(\/|$)/.test(pathname)) return "/settings";
  return null;
}

export function AppShell(): React.JSX.Element {
  return (
    <DraftGuardProvider>
      <PageFrameProvider>
        <PendingNavigation />
        <AppShellChrome />
      </PageFrameProvider>
    </DraftGuardProvider>
  );
}

/** CURRENT EPIC (render rail): the epic of the page in view — the epic itself, or a ticket's epic. */
function CurrentEpic(): React.JSX.Element | null {
  const location = useLocation();
  const m = /^\/(epic|ticket)\/([^/]+)/.exec(location.pathname);
  const kind = m?.[1];
  const id = m ? decodeURIComponent(m[2]) : "";
  const ticket = useQuery({ queryKey: ["ticket", id, null], queryFn: () => getTicketPage(id), enabled: kind === "ticket", retry: false });
  const epicId = kind === "epic" ? id : ticket.data?.epic_id ?? "";
  const epic = useQuery({ queryKey: ["epic", epicId, null], queryFn: () => getEpicPage(epicId), enabled: Boolean(epicId), retry: false });
  if (!epicId) return null;
  const title = epic.data?.title ?? epic.data?.board.epic.title ?? epicId;
  return (
    <div className={styles.current} data-testid="current-epic">
      <span className={styles.currentLabel}>Current epic</span>
      <Link to={`/epic/${encodeURIComponent(epicId)}`} className={styles.currentTitle}>{title}</Link>
    </div>
  );
}

function AppShellChrome(): React.JSX.Element {
  const location = useLocation();
  const as = identity();
  const [menuOpen, setMenuOpen] = useState(false);
  // S17 c-33ffd96baf: the rail collapses to a 64px icon rail and the message list takes the width;
  // remembered per viewer (localStorage in try/catch). Desktop only — below 768 the rail is the Menu.
  const [railCollapsed, setRailCollapsed] = useViewerFlag(as, "rail-collapsed");
  const [accountOpen, setAccountOpen] = useState(false);
  const menuRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { setMenuOpen(false); setAccountOpen(false); }, [location.pathname]);
  const [helpOpen, setHelpOpen] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const activeFamily = navFamily(location.pathname);
  const findBtnRef = useRef<HTMLButtonElement>(null);
  const closeFind = useCallback(() => {
    setFindOpen(false);
    if (findBtnRef.current?.getClientRects().length) findBtnRef.current.focus();
    else menuRef.current?.focus();
  }, []);
  const { pending, flush } = useDraftGuard();
  const { framing, terms } = usePageFrameCtx();
  const accountRef = useRef<HTMLButtonElement>(null);
  const closeAccount = useCallback(() => setAccountOpen(false), []);
  const pageFraming = framing ?? defaultFraming(location.pathname);
  const pageKey = pageKeyFor(location.pathname);

  const helpRef = useRef<HTMLButtonElement>(null);
  const closeHelp = () => {
    setHelpOpen(false);
    helpRef.current?.focus();
  };

  // Ctrl-/ toggles "What am I looking at?"; Ctrl-K opens Find (human defect #12, m-783e725c2f).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setHelpOpen((o) => !o);
      }
      if ((e.key === "k" || e.key === "K") && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setFindOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const whoami = useQuery({ queryKey: ["whoami"], queryFn: () => api<WhoAmI>("/v1/whoami"), retry: false });
  const summary = useQuery({ queryKey: ["me", "summary"], queryFn: () => api<Summary>("/v1/me/summary"), retry: false });

  const handle = whoami.data?.participant.handle ?? as;
  const role = whoami.data?.participant.role ?? "";
  const counts = summary.data;

  // Design §4.1: a 401 from the identity probe renders the inline identity panel.
  const authError = whoami.error instanceof BoardApiError && whoami.error.status === 401 ? whoami.error : null;
  if (authError) {
    return <IdentityPanel hint={authError.hint ?? authError.message} />;
  }

  const shell = (
    <div className={styles.shell} data-rail={railCollapsed ? "collapsed" : "full"}>
      <div className={styles.mobileBar} data-testid="app-header">
        <button ref={menuRef} type="button" className={styles.menuToggle} aria-label="Workspace navigation"
          aria-expanded={menuOpen} aria-controls="workspace-navigation" onClick={() => setMenuOpen((open) => !open)}>
          Menu
        </button>
        <span className={styles.mobileBrand}>Board</span>
      </div>
      <aside id="workspace-navigation" className={styles.sidebar} data-open={menuOpen} aria-label="Primary"
        onKeyDown={(event) => {
          if (event.key === "Escape" && menuRef.current?.getClientRects().length && !document.querySelector('[role="dialog"]')) {
            setMenuOpen(false);
            menuRef.current?.focus();
          }
        }}>
        <div className={styles.brand}>
          <span className={styles.brandmark} aria-hidden="true"><Icon name="library" size={24} /></span>
          <span className={styles.brandText}>Board</span>
          <button type="button" className={styles.railToggle} data-testid="rail-toggle"
            aria-controls="workspace-navigation" aria-expanded={!railCollapsed}
            aria-label={railCollapsed ? "Expand menu" : "Collapse menu"} title={railCollapsed ? "Expand menu" : "Collapse menu"}
            onClick={() => setRailCollapsed(!railCollapsed)}>
            <Icon name={railCollapsed ? "forward" : "back"} size={18} />
          </button>
        </div>

        <nav className={styles.nav} aria-label="Sections">
          {NAV.map((item) => (
            <Link key={item.to} to={item.to}
              className={`${styles.navItem} ${activeFamily === item.to ? styles.active : ""}`}
              aria-current={activeFamily === item.to ? "page" : undefined}
              {...copyProps("sidebar", item.copy)}>
              <span className={styles.icon} data-nav-icon><Icon name={item.icon} size={18} /></span>
              <span className={styles.navLabel}>{item.label}</span>
              {counts && typeof counts[item.count] === "number" ? <span className={styles.count}>{counts[item.count]}</span> : null}
            </Link>
          ))}
          <div className={styles.divider} />
          <Link to="/me" className={`${styles.navItem} ${activeFamily === "/me" ? styles.active : ""}`}
            aria-current={activeFamily === "/me" ? "page" : undefined} {...copyProps("sidebar", "decisions")}>
            <span className={styles.icon} data-nav-icon><Icon name="warning" size={18} /></span>
            <span className={styles.navLabel}>Needs you</span>
            {counts && typeof counts.decisions === "number" ? <span className={`${styles.count} ${styles.coral}`}>{counts.decisions}</span> : null}
          </Link>
          <CurrentEpic />
        </nav>

        <div className={styles.lower}>
          <div id="shell-usage-slot" data-testid="usage-slot">
            {whoami.data ? <UsageWidget key={whoami.data.participant.id} actor={whoami.data.participant.id} /> : null}
          </div>
          <button ref={findBtnRef} className={styles.railBtn} type="button" aria-label="Find (Ctrl-K)"
            {...copyProps("sidebar", "find")} aria-haspopup="dialog" aria-expanded={findOpen}
            onClick={() => setFindOpen(true)} data-testid="find-open">
            <Icon name="find" size={18} />
            <span className={styles.navLabel}>Find</span>
            <span className={styles.key}>Ctrl K</span>
          </button>
          <div className={styles.divider} />
          <button ref={accountRef} className={styles.account} type="button" aria-label="Account and preferences"
            {...copyProps("sidebar", "identity")} aria-haspopup="dialog" aria-expanded={accountOpen}
            onClick={() => { setMenuOpen(true); setAccountOpen((o) => !o); }} data-testid="account-open">
            <Avatar id={as} size={36} className={styles.avatar} />
            <span className={styles.accountText}>
              <strong data-testid="identity">{as}</strong>
              <small>
                <span data-testid="whoami-handle">{handle !== as ? handle : role || "member"}</span>
                {handle !== as && role ? ` · ${role}` : ""} · Preferences
              </small>
            </span>
          </button>
          {accountOpen ? (
            <AnchoredPanel anchor={accountRef} label="Account and preferences" heading="Account" onClose={closeAccount} width={340}>
              <p className={styles.accountWho}><strong>{as}</strong>{role ? ` · ${role}` : ""}</p>
              <div className={styles.accountLinks}>
                <Link to="/settings" className={styles.accountLink} data-testid="settings-open" onClick={closeAccount}><Icon name="preferences" size={18} /> Settings</Link>
              </div>
              {/* S17 c-066a9b347a: "What am I looking at?" is the floating top-right help button and
                  Notifications (Enable / Test) live on Settings → Notifications; neither is in this menu.
                  The worker poll and S5 authorization keep running in the always-mounted
                  NotificationCenter provider that wraps the shell. */}
              <ThemePicker />
              <AvatarPicker />
            </AnchoredPanel>
          ) : null}
        </div>
      </aside>

      {/* S17 c-066a9b347a (owner: "the what am I looking at can be a tooltip icon in a floating button
          top-right"): an icon button pinned top-right; its name shows as a tooltip on hover AND focus. */}
      <button ref={helpRef} type="button" className={styles.helpFab} data-testid="glossary-open" aria-haspopup="dialog"
        aria-expanded={helpOpen} aria-label="What am I looking at? (Ctrl /)" aria-describedby="help-fab-tip"
        onClick={() => { setAccountOpen(false); setHelpOpen((o) => !o); }}>
        <Icon name="help" size={18} />
        <span id="help-fab-tip" role="tooltip" className={styles.helpTip}>What am I looking at? <span className={styles.tipKey}>Ctrl /</span></span>
      </button>

      <main className={styles.main}>
        <p className={styles.pageFraming} data-testid="page-framing" data-route={location.pathname}>{pageFraming}</p>
        {pending > 0 ? (
          <div className={styles.liveBanner} role="status" aria-live="polite">
            <span>{pending} new {pending === 1 ? "update" : "updates"} on the board.</span>
            <button type="button" className={styles.liveBtn} data-testid="live-new" onClick={flush}>Refresh</button>
          </div>
        ) : null}
        <DocDrawerProvider>
          <Outlet />
        </DocDrawerProvider>
      </main>

      <GlossaryPanel open={helpOpen} onClose={closeHelp} framing={pageFraming} terms={terms} page={pageKey} />
      <CopyDescriptions page={pageKey} />
      <CommandPalette open={findOpen} onClose={closeFind} />
    </div>
  );

  // The notification worker/authorization run for the whole session, so the provider ALWAYS wraps the
  // shell (NotificationPanel in the account menu reads its state). It is deliberately NOT remounted by
  // key on identity change — that would remount the whole shell + Outlet — the provider resets its own
  // selectors when `actor` changes. An empty actor before whoami resolves keeps every effect a no-op.
  return <NotificationCenter actor={whoami.data?.participant.id ?? ""}>{shell}</NotificationCenter>;
}
