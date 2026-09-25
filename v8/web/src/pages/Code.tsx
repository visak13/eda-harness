import { useMemo } from "react";
import { Link, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getCodeFaq, getCodeStatus } from "../api/endpoints";
import { PageHeader } from "../components/PageHeader";
import { Markdown } from "../components/Markdown";
import { Icon } from "../components/Icon";
import { usePageFrame } from "../components/PageFrame";
import { copyProps } from "../copy/pages";
import { embedUrl, isLoopbackHost, lineLabel, parseCodeLink } from "./codeLink";
import styles from "./Code.module.css";

// epic-91fcd3b370 S3 (design-449b628cdd §4): the Code tab. A direct iframe to code-server on the
// board host's loopback (shape A, dec-ea925a2d30); the port and liveness come from GET /v1/code.
// The shell renders this route full-bleed with the rail collapsed (AppShell `bleed`). Never a blank
// frame: a stopped service, a remote browser and an unreachable board each get a named state.

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
  const src = s ? embedUrl(s.url, link, s.default_folder) : null;
  const where = link.file ? `${link.file}${link.line ? ` ${lineLabel(link.line)}` : ""}` : "";

  let body: React.JSX.Element;
  if (!local) {
    body = (
      <State testid="code-host-only" title="Code runs on the board host only">
        <p>The editor listens on the board host's loopback address, so it opens only in a browser on that machine. Nothing is exposed to this one.</p>
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
  } else {
    body = (
      <iframe
        key={src}
        className={styles.frame}
        src={src ?? undefined}
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
        {src && s?.running && local ? (
          <a href={src} target="_blank" rel="noopener noreferrer" className={styles.action} data-testid="code-newwindow" {...copyProps("code", "new-window")}>
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
