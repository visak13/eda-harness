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
    { key: "epics", label: "Epics", text: "Every epic in the fleet with its progress.", control: true },
    { key: "seats", label: "Seats", text: "Every agent seat, running or closed, and what it last said.", control: true },
    { key: "library", label: "Library", text: "Knowledge first — strategies, domains and lessons every epic can link (approve proposals, import from skills.sh) — then every document, artifact and ticket.", control: true },
    { key: "code", label: "Code", text: "A full VS Code on the board host, filling the page. Tag a code selection to anyone from inside it.", control: true },
    { key: "design", label: "Design", text: "The workflows epics run on: roles, who spawns and checks whom, the status flow, gates, hooks and caps. Everyone reads every version. An admin duplicates one into a draft, checks it (a rules check and a trial run) and publishes it.", control: true },
    { key: "admin", label: "Admin", text: "Admins only: run this install — services, settings, teammates, remote access, integrations, seats and models.", control: true },
    { key: "find", label: "Find (Ctrl K)", text: "Full-text search across tickets, documents, messages and seats. Enter opens the hit.", control: true },
    { key: "identity", label: "Account (bottom)", text: "Who you are on this board. Opens the account menu: Settings, What am I looking at?, theme, avatar.", control: true },
    { key: "new-epic", label: "New epic", text: "On the Epics page: records your words verbatim as a new epic and offers to spawn its architect. The preview lists who is woken before you confirm.", control: true },
    { key: "quick-task", label: "Quick task", text: "On the Epics page: opens a small task of your own with your words verbatim and starts an engineer on the model you pick. You review the result when it shows as done, no architect or qa needed.", control: true },
    { key: "notifications", label: "Notifications", text: "Browser alerts for questions and approval requests while a board tab stays open. Enable, test or disable them here.", control: true },
  ],
};

export const RULES: CopyItem[] = [
  { key: "who-is-woken", label: "Who is woken by a message", text: "The seat you address is woken. A note with no recipient wakes every seat on that ticket. A question or a steer also wakes the architect. An @mention wakes that person anywhere." },
  { key: "recorded", label: "Recorded by the board", text: "A verdict, a status move and a gate answer are recorded by the board and wake by the same rules. Nothing in the UI wakes anyone silently." },
];

export const PAGES: Record<string, PageCopy> = {
  epics: {
    key: "epics",
    title: "Epics",
    framing: "Every epic, its phase, and how far its stories are.",
    items: [{ key: "row", label: "Row", text: "Title (your words), phase, stories done/total, criteria passed/total, open gates. An epic that waits on you carries a dot with its count, sorted first, with a one-line reason such as '2 questions, 1 design sign-off'. Click → Epic page, where the dots continue.", control: true }],
  },
  epic: {
    key: "epic",
    title: "Epic",
    framing: "One epic: your words, the phase, its stories, its documents, its thread.",
    items: [
      { key: "title", label: "Title", text: "The epic's name. It starts as your own words and can be edited." },
      { key: "directive", label: "Architect's brief", text: "The architect's short summary of the plan and the decisions made so far. \"Show all\" opens the full text." },
      { key: "process-strip", label: "Process strip", text: "The steps an epic goes through. The highlighted step is its current status. Under Status history you can see the next expected move and who makes it." },
      { key: "steer", label: "Steer this epic", text: "Set Type to Steer in the composer. It shows who will be reached before you send. Wakes: the architect always, plus the seat you address.", control: true },
      { key: "actions", label: "Actions", text: "The menu holding every control on this page: change status, decisions, assign or spawn, ask a role, add a criterion, the original request and record ids. Each opens in the drawer.", control: true },
      { key: "links", label: "Design · Files & evidence · History · Work", text: "The design opens in the reader. Files, history and the work breakdown (stories, board, criteria, process) open in a side panel.", control: true },
      { key: "overview", label: "Overview", text: "Design link, acceptance criteria with checker and verdict, open decisions.", control: true },
      { key: "work", label: "Work", text: "The stories/tasks table: id, title, assignee role, status, criteria passed/total. Click → Ticket page.", control: true },
      { key: "documents", label: "Documents", text: "Every doc linked to this epic or its stories with its relation (design / strategy / evidence for / note). Click opens the reader.", control: true },
      { key: "thread", label: "Thread", text: "Every message on this epic, with reply links. Reply on a message answers it in place (wakes the sender).", control: true },
      { key: "change-status", label: "Change status", text: "The moves the board allows from the current step, with what each means. Wakes: the page's owner and the architect. An assignee is woken on its own ticket.", control: true },
      { key: "answer-decision", label: "Answer a decision", text: "Open gates on this epic you can rule. Answering records the ruling. Wakes: the gate's opener and the owner.", control: true },
      { key: "raise-decision", label: "Raise a decision", text: "Opens a gate for the owner (a design sign-off, a scope question…). Wakes: the owner, who rules it.", control: true },
      { key: "assign-spawn", label: "Assign or spawn a seat", text: "Set who does a story, or spawn its engineer on the fleet host. Assign wakes the assignee (and the owner). Spawn starts a new seat and wakes it as it starts.", control: true },
      { key: "spawn-architect", label: "Spawn the architect", text: "Starts a new architect seat for this epic. Shown only when seats can be started here. The board's answer is shown as it came. Wakes: the new architect seat as it starts.", control: true },
      { key: "ask-role", label: "Ask a role", text: "Posts a question on the epic thread addressed to a role (architect, engineer, qa, adversary, sme, owner). Wakes: that role's seat on this epic.", control: true },
      { key: "assigned-seats", label: "Assigned seats", text: "The seats holding stories here. Click → the seat's row on Seats. Message wakes that seat. Resume continues its parked seat where it stopped.", control: true },
    ],
  },
  ticket: {
    key: "ticket",
    title: "Ticket",
    framing: "One story or task: its criteria, its evidence, its thread, and the controls to move it.",
    items: [
      { key: "criteria", label: "Criteria", text: "Text, check type (look / verdict / command / path), checker, evidence doc, verdict. Verdict controls appear only for the named checker." },
      { key: "process-strip", label: "Process strip + Change status", text: "As on the epic. \"Ask a role\" messages a role on this ticket with the wake preview.", control: true },
      { key: "documents", label: "Documents / Artifacts", text: "Linked docs and uploaded files (drop or paste to upload). A file link opens with your identity.", control: true },
      { key: "thread", label: "Thread", text: "With Reply per message.", control: true },
      { key: "spawn-seat", label: "Spawn seat", text: "Start an engineer, qa or adversary seat on this story on a model from that role's catalog. An engineer can take the story, qa and adversary check it and never become the assignee.", control: true },
    ],
  },
  doc: {
    key: "doc",
    title: "Document",
    framing: "One document at one version. If a criterion of yours cites it, the sign-off pane is on the right.",
    items: [
      { key: "meta", label: "Meta line", text: "Type · author · scope · version (latest or the pinned one you opened). Versions menu switches version.", control: true },
      { key: "signoff", label: "Sign-off pane", text: "The criterion text, Approve / Needs work, note. The version you rule on is frozen while the pane is open.", control: true },
    ],
  },
  library: {
    key: "library",
    title: "Library",
    framing: "Knowledge every epic can use (strategies, domains, lessons), then every record on the board: documents, artifacts, links, tickets.",
    items: [
      { key: "knowledge", label: "Knowledge", text: "Search, kind, tag and status filters. A doc opens to read, edit (a new version), approve or reject a proposal against its diff, and link or unlink it to an epic. Linked docs reach that epic's briefs as one index line, read on demand.", control: true },
      { key: "import", label: "Import from skills.sh", text: "A skills.sh skill page or raw SKILL.md URL. The board fetches it once and files a high-level strategy with the skill's tags. The same URL again is the next version.", control: true },
      { key: "filters", label: "Filters", text: "Type, epic, author, status, date, tag, text. Row click opens the record.", control: true },
    ],
  },
  settings: {
    key: "settings",
    title: "Settings",
    framing: "Who you are on this board and where its pings reach you: profile, notifications, Slack.",
    items: [
      { key: "tabs", label: "Profile · Notifications · Slack", text: "Display name and time zone. Browser notification preference and quiet hours. Slack member id / webhook and quiet hours for the bridge.", control: true },
      { key: "save", label: "Save", text: "Saves your settings to the board. Slack picks the change up within a minute. Wakes nobody.", control: true },
    ],
  },
  code: {
    key: "code",
    title: "Code",
    framing: "A full VS Code on the board host (code-server), embedded in the board; its FAQ explains the shared tree and git.",
    items: [
      { key: "editor", label: "Editor", text: "VS Code running on the board host. A link can open a folder and put the cursor on a line." },
      { key: "faq", label: "FAQ", text: "Opens docs/operator/code-tab-faq.md in a new tab: the shared tree and live seats, worktrees, the extension set, tagging, and the unguarded git UI.", control: true },
      { key: "reset-layout", label: "Reset layout", text: "The editor lost its menu, activity bar or status bar (Zen mode)? Leaves Zen and puts every view back, in every open editor window. Same as Ctrl+K Z, or Heronry: Reset layout in the command palette.", control: true },
      { key: "new-window", label: "Open in new window", text: "The same editor in its own browser tab, with more room and the browser's shortcuts. Wakes nobody.", control: true },
      { key: "retry", label: "Retry", text: "Asks the board again whether code-server answers. Start it first with heronry start code on the board host.", control: true },
      { key: "start", label: "Start code server", text: "Admins only: starts the code server on the board host, the same as heronry start code or Admin → Services → code-server → Start. It stays loopback-only behind its guard.", control: true },
      { key: "open", label: "Open the Code tab", text: "Back from the FAQ to the editor.", control: true },
    ],
  },
  design: {
    key: "design",
    title: "Design",
    framing: "The workflows epics run on. Everyone reads every version; only an admin edits, and only a draft: a preset or a published version is immutable.",
    items: [
      { key: "list", label: "Workflow list", text: "Presets and custom workflows with each version's state, the version it came from and the epics that pin it. Duplicate to edit makes a draft.", control: true },
      { key: "panels", label: "Pipeline · Roles · Hooks · Gates · Caps · Validate · Dry run · Diff", text: "One panel per part of the definition. Validate links every issue to the panel that fixes it. Edits stay in this tab until Save draft.", control: true },
      { key: "publish", label: "Publish", text: "Saves the draft, runs the board's Validate (a rules check and a trial run on a made-up epic) and, with no error, publishes an immutable version new epics may pin. Wakes nobody.", control: true },
      { key: "upstream", label: "Upstream changed", text: "The version this one was copied from has a newer published version: see the three-way diff and merge it into a new draft. A field both changed keeps yours and is listed.", control: true },
    ],
  },
  admin: {
    key: "admin",
    title: "Admin",
    framing: "Run this install from the browser: restart services, change settings, invite teammates, open remote access and connect integrations.",
    items: [
      { key: "tabs", label: "Services · Seats & models · Teammates · Remote access · Integrations · Settings", text: "One tab per area. Each action is admin-only and shows the board's answer, including a refusal, where you clicked.", control: true },
      { key: "services", label: "Services", text: "Health of every service with Start / Stop / Restart through the supervisor. A board restart shows restarting… until /healthz reports a new start. Also the update banner and the Capacity caps.", control: true },
      { key: "settings", label: "Settings", text: "Every registry setting by group, with its doc line and where its value comes from. Environment values are read-only, secrets write-only. A save names the services to restart.", control: true },
      { key: "teammates", label: "Teammates", text: "Invite (a one-time link and a VS Code sign-in link), revoke, rotate, admin flag, Tailscale auth keys and agent tokens. Wakes nobody.", control: true },
    ],
  },
  join: {
    key: "join",
    title: "Join",
    framing: "The page a teammate's invite link opens: it signs this browser tab in once and links to the board.",
    items: [
      { key: "open", label: "Open the board", text: "Goes to the Epics list, signed in as the invited teammate.", control: true },
    ],
  },
  setup: {
    key: "setup",
    title: "Setup",
    framing: "The first-run wizard heronry start opens: sign in as the admin, pick seat harnesses, optionally open remote access and invite a teammate.",
    items: [
      { key: "next", label: "Next / Skip", text: "Moves to the next step. The optional steps can be done later under Admin.", control: true },
      { key: "finish", label: "Open the board", text: "Records that setup is finished so Heronry stops opening this page on start, then opens Epics.", control: true },
    ],
  },
  seats: {
    key: "seats",
    title: "Seats",
    framing: "The people behind the work: each seat, whether it is running, and what it last said.",
    items: [
      { key: "columns", label: "Columns", text: "Seat state (Working, Stalled, Parked, Closed with the reason), assigned ticket, latest work status, last refresh (presence: silence is not death)." },
      { key: "message", label: "Message", text: "Wakes that seat. The reply appears under Decisions → Replies to you and on the seat row.", control: true },
      { key: "resume", label: "Resume", text: "Continues a parked seat where it stopped.", control: true },
      { key: "close", label: "Close", text: "Ends a running seat. Recorded as \"closed by owner\", never reported as a crash.", control: true },
    ],
  },
};

/** S12-ui2 (qa m-da89ef8294): the one line each Actions item shows in the menu and as its dialog's subtitle.
 *  A plain user sentence: what the action does, sentence case, ending in a period, with no status names or
 *  field lists. Who is woken stays in the item's tooltip (copyProps). */
export const ACTION_GLOSS: Record<"epic" | "ticket", Record<string, string>> = {
  epic: {
    "change-status": "Move this epic to its next step.",
    "answer-decision": "Rule on a decision that is waiting for you.",
    "raise-decision": "Ask the owner to rule on something before the work goes on.",
    "assign-spawn": "Choose who works on this epic, or start a new seat for it.",
    "assign": "Choose who works on this epic.",
    "spawn-architect": "Start a new architect seat to plan this epic.",
    "models": "Choose the model and effort each role's next seats run on.",
    "ask-role": "Ask the architect, an engineer or another role a question.",
    "people": "The guests on this epic. They can read and ask, but not decide.",
    "add-criterion": "Add a check the work must pass to be accepted.",
    "original-request": "Your words, exactly as first written.",
    "record": "The ids to quote in a message or a terminal.",
  },
  ticket: {
    "change-status": "Move this ticket to its next step.",
    "assign-spawn": "Choose who works on this ticket, or start a new seat for it.",
    "assign": "Choose who works on this ticket.",
    "answer-decision": "Rule on a decision that is waiting for you.",
    "spawn-seat": "Start an engineer, QA or adversary seat on this story.",
    "models": "Choose the model and effort the next seats on this epic run on.",
    "raise-decision": "Ask the owner to rule on something before the work goes on.",
    "ask-role": "Ask the architect, an engineer or another role a question.",
    "link-doc": "Attach a document to this ticket.",
    "add-criterion": "Add a check the work must pass to be accepted.",
    "record": "The ids to quote in a message or a terminal.",
  },
};

/** The Actions-menu line for one item; throws on a missing one, like copyItem. */
export function actionGloss(page: "epic" | "ticket", key: string): string {
  const text = ACTION_GLOSS[page][key];
  if (!text) throw new Error(`no Actions gloss for ${page}.${key} (copy/pages.ts)`);
  return text;
}

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
