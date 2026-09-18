import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api, BoardApiError } from "../api/client";
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
import { NewEpicDialog } from "./NewEpicDialog";
import { PendingNavigation } from "./PendingNavigation";
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

// S2/v7: everyday destinations plus compact attention; archive stays under Find.
// Counts render only when the summary endpoint actually supplies them.
const NAV = [
  { to: "/epics", label: "Epics", icon: "epics", count: "epics" as const, copy: "epics" },
  { to: "/seats", label: "Seats", icon: "seats", count: "seats" as const, copy: "seats" },
  { to: "/me", label: "Needs you", icon: "decisions", count: "decisions" as const, copy: "decisions" },
] as const;

// Human #38 (m-4e303d7b27, 2026-09-11): the sidebar highlight is by ROUTE FAMILY, not by exact
// path — an epic page or a ticket page is still "Epics", every Library tab is "Library". NavLink's
// own isActive only knows prefixes of its `to`, so the family is computed here from the pathname.
export function navFamily(pathname: string): "/me" | "/epics" | "/seats" | "/library/tickets" | null {
  if (pathname === "/me" || pathname.startsWith("/me/")) return "/me";
  if (/^\/(epics|epic|ticket)(\/|$)/.test(pathname)) return "/epics";
  if (/^\/seats(\/|$)/.test(pathname)) return "/seats";
  if (/^\/(library|doc|artifact)(\/|$)/.test(pathname)) return "/library/tickets";
  return null;
}

function crumbFor(pathname: string): string {
  if (pathname.startsWith("/epic")) return "Epic";
  if (pathname.startsWith("/epics")) return "Epics";
  if (pathname.startsWith("/seats")) return "Seats";
  if (pathname.startsWith("/library")) return "Library";
  if (pathname.startsWith("/ticket")) return "Ticket";
  if (pathname.startsWith("/doc")) return "Document";
  return "Decisions";
}

// AppShell is wrapped in the DraftGuardProvider so the WHOLE chrome (its live pill included) and
// every page share ONE feed subscription and one draft-guarded refresh (design §4.2: "G2 turns
// [the live pill] into the draft-guarded refresh"). The chrome is a child so it can read the
// guard via context.
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

function AppShellChrome(): React.JSX.Element {
  const location = useLocation();
  const as = identity();
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const [newEpicOpen, setNewEpicOpen] = useState(false);
  const closeNewEpic = useCallback(() => setNewEpicOpen(false), []);
  const activeFamily = navFamily(location.pathname);
  const findBtnRef = useRef<HTMLButtonElement>(null);
  const closeFind = useCallback(() => {
    setFindOpen(false);
    findBtnRef.current?.focus();
  }, []);
  const { pending, flush } = useDraftGuard();
  const { framing, terms } = usePageFrameCtx();
  const identityRef = useRef<HTMLButtonElement>(null);
  const closePreferences = useCallback(() => setPopoverOpen(false), []);
  const helpBtnRef = useRef<HTMLButtonElement>(null);
  const pageFraming = framing ?? defaultFraming(location.pathname);
  const pageKey = pageKeyFor(location.pathname);

  const closeHelp = () => {
    setHelpOpen(false);
    helpBtnRef.current?.focus(); // restore focus to the opener (§15 keyboard contract)
  };

  // Ctrl-/ opens (and toggles) the "What am I looking at?" panel from anywhere in the app;
  // Ctrl-K opens Find (human defect #12, m-783e725c2f).
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

  // Live plane is owned by the DraftGuardProvider (one subscription for the whole app). The pill
  // reflects its `pending` count and flushes on click — held while a composer is dirty so a
  // half-typed reply is never wiped (design §4.2).


  const handle = whoami.data?.participant.handle ?? as;
  const role = whoami.data?.participant.role ?? "";
  const counts = summary.data;

  // Design §4.1: a 401 from the identity probe (a wrong token against a board with a tokens.json, or
  // an unknown participant) is NOT silently downgraded to showing `as` — render the inline identity
  // panel so the reader can re-enter a participant id / token. (second-opinion 2026-09-08)
  const authError = whoami.error instanceof BoardApiError && whoami.error.status === 401 ? whoami.error : null;
  if (authError) {
    return <IdentityPanel hint={authError.hint ?? authError.message} />;
  }

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
            <Link
              key={item.to}
              to={item.to}
              className={`${styles.navItem} ${activeFamily === item.to ? styles.active : ""}`}
              aria-current={activeFamily === item.to ? "page" : undefined}
              {...copyProps("sidebar", item.copy)}
            >
              <span className={styles.icon} data-nav-icon>
                <Icon name={item.icon} />
              </span>
              <span className={styles.navLabel}>{item.label}</span>
              {counts && typeof counts[item.count] === "number" ? (
                <span className={styles.count}>{counts[item.count]}</span>
              ) : null}
            </Link>
          ))}
        </nav>

        {/* S6 mounts its Usage trigger here; no placeholder telemetry or duplicate destination. */}
        <div id="shell-usage-slot" data-testid="usage-slot" />
        <button
          ref={findBtnRef}
          className={styles.find}
          type="button"
          aria-label="Find (Ctrl-K)"
          {...copyProps("sidebar", "find")}
          aria-haspopup="dialog"
          aria-expanded={findOpen}
          onClick={() => setFindOpen(true)}
          data-testid="find-open"
        >
          <span className={styles.icon}>
            <Icon name="find" />
          </span>
          <span className={styles.findLabel}>Find</span>
          <span className={styles.key}>Ctrl K</span>
        </button>

        {/* The former "In view" block (recent epic words) is gone: it was not navigation, it printed
            whole epic texts, overflowed the rail and pushed the identity/preferences button off
            screen (human report m-16b1efc68f, 2026-09-10). */}
        <div className={styles.identity}>
          <button
            ref={identityRef}
            className={styles.identityBtn}
            type="button"
            aria-label="Account and preferences"
            {...copyProps("sidebar", "identity")}
            aria-haspopup="dialog"
            aria-expanded={popoverOpen}
            onClick={() => setPopoverOpen((o) => !o)}
          >
            <Avatar id={as} size={32} className={styles.avatar} />
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
            <AnchoredPanel anchor={identityRef} label="Preferences" onClose={closePreferences}>
              <ThemePicker />
              <AvatarPicker />
            </AnchoredPanel>
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
          <button
            ref={helpBtnRef}
            className={styles.helpBtn}
            type="button"
            data-testid="glossary-open"
            aria-label="What am I looking at?"
            aria-haspopup="dialog"
            aria-expanded={helpOpen}
            onClick={() => setHelpOpen((o) => !o)}
          >
            <span className={styles.helpText}>What am I looking at?</span>
            <span className={styles.q} aria-hidden="true">
              <Icon name="help" />
            </span>
          </button>
          {pending > 0 ? (
            <button
              className={styles.btnPrimary}
              type="button"
              data-testid="live-new"
              aria-live="polite"
              onClick={flush}
            >
              {pending} new · refresh
            </button>
          ) : (
            <button
              className={styles.btnPrimary}
              type="button"
              data-testid="new-epic-open"
              aria-haspopup="dialog"
              aria-expanded={newEpicOpen}
              onClick={() => setNewEpicOpen(true)}
              {...copyProps("sidebar", "new-epic")}
            >
              New epic
            </button>
          )}
        </div>
      </header>

      <main className={styles.main}>
        {/* The page-framing sentence, in the main landmark (design §15): one sentence per route,
            what this is and what you can do. Visually the page's own heading block repeats it for
            sighted readers; here it is a stable, findable landmark and a screen-reader intro. */}
        <p className={styles.pageFraming} data-testid="page-framing" data-route={location.pathname}>
          {pageFraming}
        </p>
        <DocDrawerProvider>
          <Outlet />
        </DocDrawerProvider>
      </main>

      <GlossaryPanel open={helpOpen} onClose={closeHelp} framing={pageFraming} terms={terms} page={pageKey} />
      <CopyDescriptions page={pageKey} />
      <CommandPalette open={findOpen} onClose={closeFind} />
      <NewEpicDialog open={newEpicOpen} onClose={closeNewEpic} />
    </div>
  );
}
