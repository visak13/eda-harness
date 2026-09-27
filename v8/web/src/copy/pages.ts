// The UI copy contract (human defect #31, 2026-09-10; architect note-8be9cd1f31, scope
// epic-1b289d63f9). Every page declares its regions and controls here; the "What am I looking at?"
// panel renders framing → regions → controls for the CURRENT page from this copy, and every
// control carries its "does / wakes" line as tooltip + aria-describedby (copyProps). The strings
// are the note's strings, verbatim — no paraphrasing. copy.test.ts fails on any route without a
// page entry and on any rendered control without copy.

export interface CopyItem {
  key: string;
  label: string;
  text: string;
  /** A control (something the reader acts on) as opposed to a region (something shown). */
  control?: boolean;
}

export interface PageCopy {
  key: string;
  title: string;
  framing: string;
  items: CopyItem[];
}

export const SIDEBAR: PageCopy = {
  key: "sidebar",
  title: "Sidebar (every page)",
  framing: "",
  items: [
    { key: "epics", label: "Epics", text: "every epic in the fleet with its progress. Source: /v1/epics/summary.", control: true },
    { key: "seats", label: "Seats", text: "every agent shell, alive or closed, and what it last said. Source: pool sessions mirrored into the board.", control: true },
    { key: "library", label: "Library", text: "knowledge first — strategies, domains and lessons every epic can link (approve proposals, import from skills.sh) — then every document, artifact and ticket. Source: /v1/knowledge and the board's records.", control: true },
    { key: "code", label: "Code", text: "a full VS Code (code-server) on the board host, embedded full-bleed; tag a code selection to anyone from inside it. Source: /v1/code.", control: true },
    { key: "design", label: "Design", text: "the workflows epics run on: roles, who spawns and checks whom, the status flow, gates, hooks and caps. Everyone reads every version; an admin duplicates one into a draft, validates it (lint + dry run) and publishes it. Source: /v1/workflows.", control: true },
    { key: "admin", label: "Admin", text: "admins only: run this install — services, settings, teammates, remote access, integrations, seats and models. Source: /v1/admin/*.", control: true },
    { key: "find", label: "Find (Ctrl K)", text: "full-text search across tickets, documents, messages and seats; Enter opens the hit.", control: true },
    { key: "identity", label: "Account (bottom)", text: "who you are on this board; opens the account menu: Settings, What am I looking at?, theme, avatar. Source: /v1/whoami.", control: true },
    { key: "new-epic", label: "New epic", text: "on the Epics page: records your words verbatim as a new epic and offers to spawn its architect; the preview lists who is woken before you confirm.", control: true },
    { key: "quick-task", label: "Quick task", text: "on the Epics page: opens a small task of your own with your words verbatim and starts an engineer on the model you pick; you check its criteria when its dot appears on the quick task, no architect or qa needed.", control: true },
    { key: "notifications", label: "Notifications", text: "browser alerts for questions and approval requests while a board tab stays open; enable, test or disable them here.", control: true },
  ],
};

export const RULES: CopyItem[] = [
  { key: "who-is-woken", label: "Who is woken by a message", text: "the seat you address; a note with no recipient wakes every seat on that ticket; a question/steer also wakes the architect; an @mention wakes that person anywhere." },
  { key: "recorded", label: "Recorded by the board", text: "A verdict, a status move and a gate answer are recorded by the board and wake by the same rules; nothing in the UI wakes anyone silently." },
];

export const PAGES: Record<string, PageCopy> = {
  epics: {
    key: "epics",
    title: "Epics",
    framing: "Every epic, its phase, and how far its stories are.",
    items: [{ key: "row", label: "Row", text: "title (owner's words), phase, stories done/total, criteria passed/total, open gates. An epic that waits on you carries a dot with its count, sorted first, with a one-line reason such as '2 questions, 1 design sign-off'. Click → Epic page, where the dots continue.", control: true }],
  },
  epic: {
    key: "epic",
    title: "Epic",
    framing: "One epic: the owner's words, the phase, its stories, its documents, its thread.",
    items: [
      { key: "title", label: "Title", text: "the owner's words verbatim (never edited by agents)." },
      { key: "directive", label: "Architect's brief", text: "the architect's fold of the flow and current rulings; \"Show all\" expands." },
      { key: "process-strip", label: "Process strip", text: "the phase ladder; the current step is the epic's status; the next expected move and who makes it live in the rail's Status history fold (Astra #36)." },
      { key: "steer", label: "Steer this epic", text: "pick Type = Steer in the composer; the composer resolves who is reached via POST /v1/messages/resolve before you send. Wakes: the architect always, plus the seat you address.", control: true },
      { key: "actions", label: "Actions", text: "the menu holding every control on this page: change status, decisions, assign or spawn, ask a role, add a criterion, the original request and record ids; each opens in the drawer.", control: true },
      { key: "links", label: "Design · Files & evidence · History · Work", text: "the source-bound viewers: the design opens in the reader; files, history and the work breakdown (stories, kanban, criteria, process) open in the drawer.", control: true },
      { key: "overview", label: "Overview", text: "design link, criteria (acceptance) with checker and verdict, gates.", control: true },
      { key: "work", label: "Work", text: "the stories/tasks table: id, title, assignee role, status, criteria passed/total. Click → Ticket page.", control: true },
      { key: "documents", label: "Documents", text: "every doc linked to this epic or its stories with its relation (design / strategy / evidence for / note); click opens the reader.", control: true },
      { key: "thread", label: "Thread", text: "every message on this epic, with reply links; Reply on a message answers it in place (wakes the sender).", control: true },
      { key: "change-status", label: "Change status", text: "the moves the board allows from the current phase, with what each means. Wakes on ready/in_review/done/blocked: the page's owner and the architect; an assignee is woken on its own ticket.", control: true },
      { key: "answer-decision", label: "Answer a decision", text: "open gates on this epic you can rule; answering records the ruling. Wakes: the gate's opener and the owner.", control: true },
      { key: "raise-decision", label: "Raise a decision", text: "opens a gate for the owner (design sign-off, demo, scope…). Wakes: the owner, who rules it.", control: true },
      { key: "assign-spawn", label: "Assign or spawn a seat", text: "set who does a story, or spawn its engineer on the fleet host. Assign wakes the assignee (and the owner); Spawn starts a new shell and wakes it at boot.", control: true },
      { key: "spawn-architect", label: "Spawn the architect", text: "starts a new architect shell for this epic (architect.<epic>) through the pool; shown only when the pool can spawn; the board's answer is shown verbatim. Wakes: the new architect seat at boot.", control: true },
      { key: "ask-role", label: "Ask a role", text: "posts a question on the epic thread addressed to a role (architect, engineer, qa, adversary, sme, owner). Wakes: that role's seat on this epic.", control: true },
      { key: "assigned-seats", label: "Assigned seats", text: "the seats holding stories here; click → the seat's row on Seats. Message wakes that seat; Resume continues its parked shell (POST /v1/sessions/resume).", control: true },
    ],
  },
  ticket: {
    key: "ticket",
    title: "Ticket",
    framing: "One story or task: its criteria, its evidence, its thread, and the controls to move it.",
    items: [
      { key: "criteria", label: "Criteria", text: "text, check type (look / verdict / command / path), checker, evidence doc, verdict. Verdict controls appear only for the named checker." },
      { key: "process-strip", label: "Process strip + Change status", text: "as on the epic; \"Ask a role\" messages a role on this ticket with the wake preview.", control: true },
      { key: "documents", label: "Documents / Artifacts", text: "linked docs and uploaded files (drop or paste to upload; a file link opens with your identity).", control: true },
      { key: "thread", label: "Thread", text: "with Reply per message.", control: true },
      { key: "spawn-seat", label: "Spawn seat", text: "start an engineer, qa or adversary seat on this story on a model from that role's catalog; an engineer can take the story, qa and adversary check it and never become the assignee.", control: true },
    ],
  },
  doc: {
    key: "doc",
    title: "Document",
    framing: "One document at one version. If a criterion of yours cites it, the sign-off pane is on the right.",
    items: [
      { key: "meta", label: "Meta line", text: "type · author · scope · version (latest or the pinned one you opened). Versions menu switches version.", control: true },
      { key: "signoff", label: "Sign-off pane", text: "the criterion text, Approve / Needs work, note; the version you rule on is frozen while the pane is open.", control: true },
    ],
  },
  library: {
    key: "library",
    title: "Library",
    framing: "Knowledge every epic can use (strategies, domains, lessons), then every record on the board: documents, artifacts, links, tickets.",
    items: [
      { key: "knowledge", label: "Knowledge", text: "search, kind, tag and status filters; a doc opens to read, edit (a new version), approve or reject a proposal against its diff, and link or unlink it to an epic. Linked docs reach that epic's briefs as one index line, read on demand.", control: true },
      { key: "import", label: "Import from skills.sh", text: "a skills.sh skill page or raw SKILL.md URL; the board fetches it once and files a high-level strategy with the skill's tags; the same URL again is the next version.", control: true },
      { key: "filters", label: "Filters", text: "type, epic, author, status, date, tag, text. Row click opens the record.", control: true },
    ],
  },
  settings: {
    key: "settings",
    title: "Settings",
    framing: "Who you are on this board and where its pings reach you: profile, notifications, Slack.",
    items: [
      { key: "tabs", label: "Profile · Notifications · Slack", text: "display name and time zone; browser notification preference and quiet hours; Slack member id / webhook and quiet hours for the bridge.", control: true },
      { key: "save", label: "Save", text: "writes your settings to the board (PUT /v1/me/settings); the Slack bridge picks the change up within a minute. Wakes nobody.", control: true },
    ],
  },
  code: {
    key: "code",
    title: "Code",
    framing: "A full VS Code on the board host (code-server), embedded in the board; its FAQ explains the shared tree and git.",
    items: [
      { key: "editor", label: "Editor", text: "code-server on the board host's loopback port (GET /v1/code); a deep link /code?folder=&file=&line=n-m opens a folder and puts the cursor on line n." },
      { key: "faq", label: "FAQ", text: "opens guides/code-tab-faq.md in a new tab: the shared tree and live seats, worktrees, the extension set, tagging, and the unguarded git UI.", control: true },
      { key: "reset-layout", label: "Reset layout", text: "the editor lost its menu, activity bar or status bar (Zen mode)? Leaves Zen and puts every view back, in every open editor window. Same as Ctrl+K Z, or Heronry: Reset layout in the command palette.", control: true },
      { key: "new-window", label: "Open in new window", text: "the same editor in its own browser tab, with more room and the browser's shortcuts. Wakes nobody.", control: true },
      { key: "retry", label: "Retry", text: "asks the board again whether code-server answers; start it first with .\\edp.ps1 start code on the board host.", control: true },
      { key: "open", label: "Open the Code tab", text: "back from the FAQ to the editor.", control: true },
    ],
  },
  design: {
    key: "design",
    title: "Design",
    framing: "The workflows epics run on. Everyone reads every version; only an admin edits, and only a draft: a preset or a published version is immutable.",
    items: [
      { key: "list", label: "Workflow list", text: "presets and custom workflows with each version's state, the version it came from and the epics that pin it. Duplicate to edit makes a draft. Source: /v1/workflows.", control: true },
      { key: "panels", label: "Pipeline · Roles · Hooks · Gates · Caps · Validate · Dry run · Diff", text: "one panel per part of the definition; Validate links every issue to the panel that fixes it. Edits stay in this tab until Save draft.", control: true },
      { key: "publish", label: "Publish", text: "saves the draft, runs the board's Validate (lint and a dry run of a synthetic epic) and, with no error, publishes an immutable version new epics may pin. Wakes nobody.", control: true },
      { key: "upstream", label: "Upstream changed", text: "the version this one was copied from has a newer published version: see the three-way diff and merge it into a new draft; a field both changed keeps yours and is listed.", control: true },
    ],
  },
  admin: {
    key: "admin",
    title: "Admin",
    framing: "Run this install from the browser: restart services, change settings, invite teammates, open remote access and connect integrations.",
    items: [
      { key: "tabs", label: "Services · Settings · Teammates · Remote access · Integrations · Seats & models", text: "one tab per area; each action calls an admin-only /v1/admin route and shows the board's answer, including a refusal, where you clicked.", control: true },
      { key: "services", label: "Services", text: "health of every service with Start / Stop / Restart through the supervisor; a board restart shows restarting… until /healthz reports a new start. Also the update banner and the Capacity caps.", control: true },
      { key: "settings", label: "Settings", text: "every registry setting by group, with its doc line and where its value comes from; environment values are read-only, secrets write-only. A save names the services to restart.", control: true },
      { key: "teammates", label: "Teammates", text: "invite (a one-time link and a VS Code sign-in link), revoke, rotate, admin flag, Tailscale auth keys and agent tokens. Wakes nobody.", control: true },
    ],
  },
  join: {
    key: "join",
    title: "Join",
    framing: "The page a teammate's invite link opens: it signs this browser tab in once and links to the board.",
    items: [
      { key: "open", label: "Open the board", text: "goes to the Epics list, signed in as the invited teammate.", control: true },
    ],
  },
  setup: {
    key: "setup",
    title: "Setup",
    framing: "The first-run wizard heronry start opens: sign in as the admin, pick seat harnesses, optionally open remote access and invite a teammate.",
    items: [
      { key: "next", label: "Next / Skip", text: "moves to the next step; the optional steps can be done later under Admin.", control: true },
      { key: "finish", label: "Open the board", text: "records that setup is finished (POST /v1/admin/setup/done) so heronry start stops opening it, then opens Epics.", control: true },
    ],
  },
  seats: {
    key: "seats",
    title: "Seats",
    framing: "The people behind the work: each seat, whether its shell is alive, and what it last said.",
    items: [
      { key: "columns", label: "Columns", text: "seat / shell state (Alive, Stalled, Parked, Closed with reason), assigned ticket, latest work status, last refresh (presence: silence is not death)." },
      { key: "message", label: "Message", text: "wakes that seat; the reply appears under Decisions → Replies to you and on the seat row.", control: true },
      { key: "resume", label: "Resume", text: "parked seats.", control: true },
    ],
  },
};

/** The copy page for a router pathname (the SPA's own routes, without the /ui base). */
export function pageKeyFor(pathname: string): string {
  if (pathname.startsWith("/epic/")) return "epic";
  if (pathname.startsWith("/epics")) return "epics";
  if (pathname.startsWith("/ticket/")) return "ticket";
  if (pathname.startsWith("/doc/")) return "doc";
  if (pathname.startsWith("/seats")) return "seats";
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/admin")) return "admin";
  if (pathname.startsWith("/design")) return "design";
  if (pathname.startsWith("/join")) return "join";
  if (pathname.startsWith("/setup")) return "setup";
  if (pathname === "/code" || pathname.startsWith("/code/")) return "code";
  if (pathname.startsWith("/records/")) return "epic";
  if (pathname.startsWith("/library") || pathname.startsWith("/tickets") || pathname.startsWith("/activity")) return "library";
  return "epics";
}

export function copyItem(page: string, key: string): CopyItem {
  const p = page === "sidebar" ? SIDEBAR : PAGES[page];
  const item = p?.items.find((i) => i.key === key);
  if (!item) throw new Error(`no UI copy for ${page}.${key} (copy/pages.ts, note-8be9cd1f31)`);
  return item;
}

export function copyId(page: string, key: string): string {
  return `copy-${page}-${key}`;
}

/** Props for a control: its "does / wakes" line as the tooltip and as aria-describedby (the
 *  description element is rendered once per page by <CopyDescriptions>). */
export function copyProps(page: string, key: string): { title: string; "aria-describedby": string; "data-copy": string } {
  const item = copyItem(page, key);
  return { title: `${item.label} — ${item.text}`, "aria-describedby": copyId(page, key), "data-copy": `${page}.${key}` };
}
