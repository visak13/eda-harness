import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getCodeFaq, getCodeStatus, mintCodeSession } from "../api/endpoints";
import { PageHeader } from "../components/PageHeader";
import { Markdown } from "../components/Markdown";
import { Icon } from "../components/Icon";
import { usePageFrame } from "../components/PageFrame";
import { copyProps } from "../copy/pages";
import { embedUrl, guardBase, isLoopbackHost, lineLabel, loginUrl, parseCodeLink } from "./codeLink";
import styles from "./Code.module.css";

// epic-91fcd3b370 S3 (design-449b628cdd §4): the Code tab. A direct iframe to code-server on the
// board host's loopback (shape A, dec-ea925a2d30); the port and liveness come from GET /v1/code.
// The shell renders this route full-bleed with the rail collapsed (AppShell `bleed`). Never a blank
// frame: a stopped service, a remote browser and an unreachable board each get a named state.
// S8 (s-17c13096e5): the guard relays only for a browser holding its cookie. The frame first loads
// the guard's login URL with a one-time token the board mints for its human owner only; "Open in new
// window" mints its own. Anyone else gets a named state, never an iframe that answers 401.

const FRAMING = "A full VS Code on the board host. Open a folder, edit, search, run a terminal, and tag a selection to anyone on the board.";

function State({ testid, title, children }: { testid: string; title: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <section className={styles.state} data-testid={testid} role="status">
      <h2 className={styles.stateTitle}>{title}</h2>
      {children}
    </section>
  );
}

/** `hostname` defaults to the page's own (tests pass a remote one). */
export function CodePage({ hostname = window.location.hostname }: { hostname?: string } = {}): React.JSX.Element {
  usePageFrame(FRAMING);
  const { search } = useLocation();
  const link = useMemo(() => parseCodeLink(search), [search]);
  const status = useQuery({ queryKey: ["code", "status"], queryFn: getCodeStatus, retry: false, refetchOnWindowFocus: false });
  const local = isLoopbackHost(hostname);
  const s = status.data;
  const src = s ? embedUrl(guardBase(s.url, hostname), link, s.default_folder) : null;
  // the guard answers only these two names, and its SameSite=Strict cookie needs the same one as the page
  const guardHost = ["localhost", "127.0.0.1"].includes(hostname.toLowerCase());
  const showFrame = !!(local && guardHost && src && s?.running && !status.isError);
  // One token per iframe lifetime, spent by the guard on load. Kept out of the query cache: a feed
  // invalidation must not remint (and reload the editor), and a frame shown again after an error state
  // must not reuse a spent token (second opinion 20260925T191655Z-01833b5d).
  const [attempt, setAttempt] = useState(0);
  const [session, setSession] = useState<{ for: string; url?: string; error?: unknown } | null>(null);
  useEffect(() => {
    if (!showFrame || !src) { setSession(null); return; }
    let live = true;
    setSession({ for: src });
    mintCodeSession().then(
      (m) => { if (live) setSession({ for: src, url: m ? loginUrl(src, m.token) : src }); },
      (e: unknown) => { if (live) setSession({ for: src, error: e }); },
    );
    return () => { live = false; };
  }, [showFrame, src, attempt]);
  const frameSrc = session?.for === src ? session.url ?? null : null;
  const openNewWindow = (e: React.MouseEvent<HTMLAnchorElement>): void => {
    if (!src) return;
    e.preventDefault();
    // opened now, inside the click (popup blockers), then pointed at a freshly minted login URL
    const w = window.open("about:blank", "_blank");
    if (!w) return;
    w.opener = null;
    mintCodeSession().then((m) => { w.location.href = m ? loginUrl(src, m.token) : src; }, () => { w.location.href = src; });
  };
  const where = link.file ? `${link.file}${link.line ? ` ${lineLabel(link.line)}` : ""}` : "";

  let body: React.JSX.Element;
  if (!local) {
    body = (
      <State testid="code-host-only" title="Code runs on the board host only">
        <p>The editor listens on the board host's loopback address, so it opens only in a browser on that machine. Nothing is exposed to this one.</p>
      </State>
    );
  } else if (!guardHost) {
    body = (
      <State testid="code-host-name" title="Open the board as 127.0.0.1 or localhost">
        <p>The editor signs in with a cookie that only travels between pages under the same name. Open the board at <code>http://127.0.0.1{window.location.port ? `:${window.location.port}` : ""}/ui/code</code> or at localhost.</p>
      </State>
    );
  } else if (status.isPending) {
    body = <State testid="code-loading" title="Checking the code service…"><p>Asking the board whether code-server is up.</p></State>;
  } else if (status.isError || !s) {
    body = (
      <State testid="code-board-error" title="The board did not answer">
        <p>{status.error instanceof Error ? status.error.message : "GET /v1/code failed."}</p>
        <button type="button" className={styles.retry} onClick={() => void status.refetch()} {...copyProps("code", "retry")}>Retry</button>
      </State>
    );
  } else if (!s.running) {
    body = (
      <State testid="code-down" title="Code service is not running">
        <p>code-server is not answering on port {s.port}. Start it from the repo root on the board host:</p>
        <pre className={styles.command} data-testid="code-start-command"><code>{s.start_command}</code></pre>
        <button type="button" className={styles.retry} data-testid="code-retry" onClick={() => void status.refetch()} {...copyProps("code", "retry")}>
          {status.isFetching ? "Checking…" : "Retry"}
        </button>
      </State>
    );
  } else if (session?.error !== undefined) {
    body = (
      <State testid="code-no-session" title="The board did not open a code session">
        <p>{session.error instanceof Error ? session.error.message : "POST /v1/code/session failed."}</p>
        <p>The editor opens only for the board's owner, signed in on the board host.</p>
        <button type="button" className={styles.retry} onClick={() => setAttempt((n) => n + 1)} {...copyProps("code", "retry")}>Retry</button>
      </State>
    );
  } else if (!frameSrc) {
    body = <State testid="code-loading" title="Opening a code session…"><p>Asking the board for a one-time sign-in to the editor.</p></State>;
  } else {
    body = (
      <iframe
        key={frameSrc}
        className={styles.frame}
        src={frameSrc}
        title="Code editor (code-server)"
        data-testid="code-frame"
        allow="clipboard-read; clipboard-write"
      />
    );
  }

  const state = !local ? "host only" : s ? (s.running ? `code-server ${s.version ?? ""} · running`.replace("  ", " ") : "not running") : status.isError ? "board unreachable" : "checking";
  return (
    <div className={styles.page} data-testid="code-page">
      <header className={styles.strip} data-testid="code-strip">
        <h1 className={styles.title}>Code</h1>
        <span className={styles.chip} data-testid="code-state" data-running={s?.running ? "true" : "false"}>
          <span className={styles.dot} aria-hidden="true" />{state}
        </span>
        {where ? <span className={styles.where} data-testid="code-where" title={link.folder ?? undefined}>{where}</span> : null}
        {link.invalid.length ? <span className={styles.invalid} data-testid="code-invalid">Ignored: {link.invalid.join(", ")}</span> : null}
        <span className={styles.spacer} />
        <Link to="/code/faq" target="_blank" rel="noopener" className={styles.action} data-testid="code-faq" {...copyProps("code", "faq")}>
          <Icon name="help" size={16} /> FAQ
        </Link>
        {src && s?.running && local && guardHost ? (
          <a href={src} target="_blank" rel="noopener noreferrer" onClick={openNewWindow} className={styles.action} data-testid="code-newwindow" {...copyProps("code", "new-window")}>
            <Icon name="external" size={16} /> Open in new window
          </a>
        ) : null}
      </header>
      <div className={styles.body}>{body}</div>
    </div>
  );
}

export function CodeFaqPage(): React.JSX.Element {
  usePageFrame("The Code tab's FAQ: the shared tree, worktrees, the extension set, tagging, and git.");
  const faq = useQuery({ queryKey: ["code", "faq"], queryFn: getCodeFaq, retry: false });
  return (
    <>
      <PageHeader title="Code tab FAQ" subtitle="guides/code-tab-faq.md" />
      <p className={styles.back}><Link to="/code" data-testid="code-faq-back" {...copyProps("code", "open")}>Open the Code tab</Link></p>
      {faq.data ? <Markdown html={faq.data.html} /> : faq.isError
        ? <p role="alert" data-testid="code-faq-error">{faq.error instanceof Error ? faq.error.message : "The FAQ could not be loaded."}</p>
        : <p>Loading…</p>}
    </>
  );
}
