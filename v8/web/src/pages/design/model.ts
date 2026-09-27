import type { Precondition, Problem, RoleDef, Transition, WorkflowDef } from "../../api/workflows";

// S14: pure helpers the Design tab's panels share — no fetching, so vitest drives them with fixtures.

// t-0c16c00424 (owner m-b841864899: "easy to understand as the admin tab is"): the sections in the order a
// person works through a workflow (pages/admin/README.md reading order): what it is, who works on it, who
// checks and where a person says yes, the board's automatic behaviours and limits, then check and publish.
export const PANELS = [
  { key: "overview", label: "Overview", hint: "What this workflow does: who works on an epic and the path a ticket takes." },
  { key: "roles", label: "Roles", hint: "Each kind of seat: its instructions, model, tools and what it may do." },
  { key: "checks", label: "Checks and gates", hint: "Who checks each kind of work, and where a person must answer before work goes on." },
  { key: "policy", label: "Hooks and caps", hint: "What the board does on its own, and the limits it keeps on every epic." },
  { key: "publish", label: "Validate and publish", hint: "Check the draft, walk a test epic through it, see what changes, then publish." },
] as const;
export type PanelKey = (typeof PANELS)[number]["key"];

/** Section keys before t-0c16c00424, so an old ?panel= link still opens the right section. */
const LEGACY_PANEL: Record<string, PanelKey> = {
  pipeline: "overview", gates: "checks", hooks: "policy", caps: "policy", validate: "publish", dryrun: "publish", diff: "publish",
};
export function panelOf(key: string | null): PanelKey {
  if (!key) return "overview";
  if (PANELS.some((p) => p.key === key)) return key as PanelKey;
  return LEGACY_PANEL[key] ?? "overview";
}

/** One-line page header: what a workflow is and when you would change one. */
export const DESIGN_SCOPE = "A workflow is the rulebook an epic runs on: which roles work on it, how a ticket moves from idea to done, "
  + "and where a person must say yes. Change one when your team needs other roles, checks or limits; running epics keep the version they started on.";

/** A status or key in plain words: in_progress → "in progress". */
export const plain = (key: string): string => key.replaceAll("_", " ");

/** The board's main status path, in order; every other status is a side status (blocked, partial, dropped). */
export const MAIN_PATH = ["drafted", "designed", "signed_off", "ready", "in_progress", "in_review", "done"];
export const KINDS = ["epic", "story", "task", "topic"];
export const KIND_PLURAL: Record<string, string> = { epic: "epics", story: "stories", task: "tasks", topic: "topics" };
export const DOC_TYPES = ["design", "strategy_hl", "strategy_ll", "domain", "report", "note"];
export const EFFORTS = ["low", "medium", "high"];

/** One line per hook: what the board does when it is on (design §4.14(b); edp8/workflow.py HOOKS). */
export const HOOK_HELP: Record<string, string> = {
  epic_auto_advance: "The board moves an epic through in progress, in review and signed off from the facts of its stories.",
  release_cascade: "When a ticket is released, signed-off tickets waiting on it become ready; a review story waits for the rest.",
  criteria_auto_done: "A ticket in review becomes done once every criterion passed; an epic also needs its acceptance checker's criteria.",
  signoff_before_start: "A quick task starts only after the owner signs off its design note.",
  evidence_before_review: "A ticket reaches in review only when every check (criterion) has evidence attached.",
  acceptance_pairs_checker: "When an epic reaches review, the board spawns one checker seat of this role for it.",
  resident_designer: "The epic's own designer seat (this role) walks its epic and is addressed by its role.",
  review_story_last: "The adversarial review story waits for its sibling stories and never blocks them.",
  knowledge_tickets: "Knowledge tickets (craft docs) are checked by this role.",
  one_checker_per_epic: "A checker seat named <role>.<epic> may verdict only its own epic.",
  quick_task: "The owner's parentless story tagged quick is a quick task the owner checks.",
};

/** Plain names for hooks (the key stays visible, small, for people reading the board's messages). */
export const HOOK_LABEL: Record<string, string> = {
  epic_auto_advance: "Move epics forward on their own",
  release_cascade: "Start waiting work when a ticket is released",
  criteria_auto_done: "Close a ticket once every check passed",
  signoff_before_start: "Quick tasks wait for the owner's sign-off",
  evidence_before_review: "Review needs evidence on every check",
  acceptance_pairs_checker: "Start one acceptance checker per epic",
  resident_designer: "Each epic keeps its own designer seat",
  review_story_last: "The adversarial review goes last",
  knowledge_tickets: "Who checks knowledge tickets",
  one_checker_per_epic: "A checker only judges its own epic",
  quick_task: "The owner's quick tasks",
};

/** Plain names for hook parameters. */
export const PARAM_LABEL: Record<string, string> = {
  role: "Role", epic_checker: "Epic checker", checked_by: "Checked by", review_work_type: "Review work type",
  work_type: "Work type", tag: "Tag",
};

/** Plain names for gates. */
export const GATE_LABEL: Record<string, string> = {
  design_signoff: "Design sign-off",
  poc: "Proof of concept",
  demo: "First demo",
  adversarial: "Adversarial review ruling",
  budget: "Budget",
  acceptance: "Acceptance",
  scope: "Scope increase",
};

/** Plain names for caps. */
export const CAP_LABEL: Record<string, string> = {
  stories_per_epic: "Stories per epic",
  tasks_per_story: "Tasks per story",
  criteria_per_story: "Checks per story",
};

/** One line per gate id (the answer a human gives). */
export const GATE_HELP: Record<string, string> = {
  design_signoff: "The owner approves the epic's design before any story starts.",
  poc: "The owner decides whether a proof of concept is good enough to build on.",
  demo: "The owner looks at a first artifact and says go on or change course.",
  adversarial: "The owner rules on an adversarial review's findings.",
  budget: "The owner approves spending past a cost or time budget.",
  acceptance: "The owner is asked when an epic reaches acceptance; the checker verdicts its criteria.",
  scope: "The owner raises a story or criteria cap for one epic.",
};

/** Where a gate sits on the status path (the edge it guards), for the pipeline view. */
export const GATE_EDGE: Record<string, [string, string]> = {
  design_signoff: ["designed", "signed_off"],
  acceptance: ["in_review", "done"],
};

export const CAP_HELP: Record<string, string> = {
  stories_per_epic: "Open stories one epic may hold; design sign-off is refused above it until the owner answers a scope gate.",
  tasks_per_story: "Task tickets one story may split into.",
  criteria_per_story: "Fresh criteria one story may carry.",
};

export const FIELD_HELP: Record<string, string> = {
  id: "Lowercase letters, digits and dashes; seats are named <id>.<ticket>. It cannot change once saved.",
  label: "The name people see in the Design tab and pickers.",
  model: "The model a seat of this role runs on unless the epic picks another (from Admin → Seats & models).",
  effort: "Reasoning effort, capped by the model's catalog entry.",
  card: "The role's instructions. The kernel preamble (boot, wake, report, close) is always prepended; write only the role's own part.",
  bundle: "The board tools the seat may call. Kernel tools are always included; a tool its permissions do not allow is dropped.",
  spawnable: "A seat of this role can be started (some role must list it under may spawn).",
  may_spawn: "Roles this role may start seats of.",
  spawned_by: "Roles that may start a seat of this role.",
  may_create: "Ticket kinds this role may create.",
  criterion_author: "Writes acceptance criteria.",
  criterion_checker: "Records pass/fail verdicts on criteria. A role that builds or authors criteria must not also check.",
  gate_answerer: "Answers gates. Only a human role may.",
  capacity_class: "How the pool caps concurrent seats: builder and planner have class caps; checker counts only toward the total.",
  max_concurrent: "This role's own cap on live seats (blank = the class cap).",
  doc_types: "Active document types this role authors.",
  permissions: "Workflow-wide permissions this role holds.",
};

export const PERMISSION_HELP: Record<string, string> = {
  set_title: "set a ticket's short title",
  edit_ticket: "edit a ticket's description and tags",
  assign: "assign a ticket",
  set_design_ref: "set a ticket's design doc",
  claim: "take an unassigned ticket to in progress",
  evidence: "attach evidence to criteria",
  task_verdict: "verdict a task's criteria",
  binding: "record binding decisions",
};

export function roleLabel(r: RoleDef): string {
  return r.label || r.id;
}

/** Roles that may spawn `id`. */
export function spawnersOf(wf: WorkflowDef, id: string): string[] {
  return wf.roles.filter((r) => (r.may_spawn ?? []).includes(id)).map((r) => r.id);
}

/** The kinds each role checks, from the checker map (first matching rule wins, as on the board). */
export function checksByRole(wf: WorkflowDef): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const k of wf.kinds) {
    const rule = wf.checkers.find((c) => {
      const w = c.when ?? {};
      const kinds = w.kinds as string[] | undefined;
      const notKinds = w.not_kinds as string[] | undefined;
      if (kinds && !kinds.includes(k)) return false;
      if (notKinds && notKinds.includes(k)) return false;
      return w.quick !== true && w.quick_root !== true;
    });
    if (rule) (out[rule.role] ??= []).push(k);
  }
  return out;
}

/** Who may take a transition, in words, from its declared preconditions. */
export function whoTakes(wf: WorkflowDef, t: Transition): string {
  const who = new Set<string>();
  for (const p of t.requires) {
    const params = p.params ?? {};
    if (p.check === "role_in") {
      for (const r of (params.roles as string[] | undefined) ?? []) who.add(r);
      if (params.roles_from === "checkers") for (const r of Object.keys(checksByRole(wf))) who.add(r);
    }
    if (p.check === "assignee_or_claim") for (const r of wf.permissions.claim ?? []) who.add(r);
    if (p.check === "actor_is_assignee") who.add("assignee");
  }
  if (t.auto) who.add("board (auto)");
  return who.size ? [...who].join(", ") : "anyone";
}

export function preconditionText(p: Precondition): string {
  // S14 reopen: words only; the check's key (for reading board refusals) goes in a tooltip, from preconditionKey
  const label = p.message ? p.message.replace(/\{[a-z_]+\}/g, "…") : PRECONDITION_LABEL[p.check] ?? plain(p.check);
  return p.hook ? `${label}, while "${HOOK_LABEL[p.hook] ?? plain(p.hook)}" is on` : label;
}
export const preconditionKey = (p: Precondition): string => `${p.check}${p.hook ? ` · hook ${p.hook}` : ""}`;

/** Roles laid out in spawn layers: humans first, then whom they spawn, and so on; a spawnable role no live
 *  role can reach is `unreached`. Roles in no relation at all (e.g. expert) are left out and listed. */
export function roleLayers(wf: WorkflowDef): { layers: string[][]; unreached: string[]; idle: string[] } {
  const byId = new Map(wf.roles.map((r) => [r.id, r]));
  const checks = checksByRole(wf);
  const gateAnswerers = new Set(wf.gates.flatMap((g) => g.answerers));
  const inFlow = (r: RoleDef) => r.spawnable || (r.may_spawn ?? []).length > 0 || Boolean(checks[r.id]) || gateAnswerers.has(r.id)
    || wf.roles.some((o) => (o.may_spawn ?? []).includes(r.id));
  const idle = wf.roles.filter((r) => !inFlow(r)).map((r) => r.id);
  const layerOf = new Map<string, number>();
  let frontier = wf.roles.filter((r) => r.human && inFlow(r)).map((r) => r.id);
  frontier.forEach((id) => layerOf.set(id, 0));
  let depth = 0;
  while (frontier.length) {
    depth += 1;
    const next: string[] = [];
    for (const id of frontier) {
      for (const s of byId.get(id)?.may_spawn ?? []) {
        if (byId.has(s) && !layerOf.has(s)) { layerOf.set(s, depth); next.push(s); }
      }
    }
    frontier = next;
  }
  const layers: string[][] = [];
  for (const r of wf.roles) {
    const l = layerOf.get(r.id);
    if (l === undefined) continue;
    (layers[l] ??= []).push(r.id);
  }
  const unreached = wf.roles.filter((r) => inFlow(r) && !layerOf.has(r.id)).map((r) => r.id);
  return { layers: layers.filter(Boolean), unreached, idle };
}

/** The panel (and role) a lint problem belongs to, so Validate can link each issue to where it is fixed. */
export function panelFor(p: Problem): { panel: PanelKey; role?: string; field?: string } {
  const role = /role '([^']+)'/.exec(p.message)?.[1];
  switch (p.code) {
    case "cap_below_1":
      return role ? { panel: "roles", role, field: "max_concurrent" } : { panel: "policy", field: /caps\.([a-z_]+)/.exec(p.message)?.[1] };
    case "schema":
      return /caps\./.test(p.message) ? { panel: "policy" } : { panel: "overview" };
    case "unknown_hook":
    case "hook_param":
      return { panel: "policy", field: /hook '([^']+)'/.exec(p.message)?.[1] };
    case "gate_without_precondition":
    case "gate_unanswerable":
    case "self_approval":
      return { panel: "checks", field: /gate '([^']+)'/.exec(p.message)?.[1] };
    case "dry_run_stall":
      return { panel: "publish", field: "dryrun" };
    case "role_without_spawner":
    case "card_missing":
    case "unknown_capacity":
    case "kernel_stripped":
    case "bundle_missing":
    case "self_check":
    case "escalation":
    case "unusable_tool":
      return { panel: "roles", role, field: FIELD_OF[p.code] };
    case "unknown_role":
      return role ? { panel: "roles", role } : { panel: "overview" };
    default:
      return { panel: "overview" };
  }
}

const FIELD_OF: Record<string, string> = {
  role_without_spawner: "spawned_by",
  card_missing: "card",
  unknown_capacity: "capacity_class",
  kernel_stripped: "bundle",
  bundle_missing: "bundle",
  self_check: "criterion_checker",
  escalation: "bundle",
  unusable_tool: "bundle",
};

/** Roles with at least one error-level problem (their chips turn red). */
export function rolesWithErrors(problems: Problem[]): Set<string> {
  return new Set(problems.filter((p) => p.severity === "error").map((p) => panelFor(p))
    .filter((x) => x.panel === "roles" && x.role).map((x) => x.role as string));
}

/** A definition without the read-only extras the GET adds (problems). */
export function bodyOf(d: WorkflowDef & { problems?: unknown }): WorkflowDef {
  const { problems: _p, ...rest } = d;
  void _p;
  return rest;
}

export function short(v: unknown): string {
  if (v === null || v === undefined) return "—";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > 160 ? `${s.slice(0, 157)}…` : s;
}

export const ROLE_ID = /^[a-z][a-z0-9-]{0,30}$/;
/** A person's role (owner m-da9a2ae62f): never a seat, so Add role and Spawn seat never offer or take one.
 *  Mirrors edp_contracts.roles.NON_AGENT_ROLES; the board and the pool refuse it too. */
export const NON_AGENT_ROLES: ReadonlySet<string> = new Set(["owner", "expert", "human"]);

// S14 reopen (qa m-c4f23e49f0, owner m-b841864899: "as easy to understand as the admin tab"): the Roles section and
// Validate speak in plain words; an internal id shows only in a tooltip or a small monospace detail.

/** Plain names for the board's tools (the id stays in the tooltip). An unknown tool falls back to its id in words. */
export const TOOL_LABEL: Record<string, string> = {
  artifact_create: "Record a produced thing", artifact_read: "Read an artifact", artifact_upload: "Upload a file",
  assemble_ruleset: "Build a ticket's working rules", board: "See an epic's tickets at a glance", close: "Close an epic",
  close_self: "End its own shell", context: "Load its tickets", context_delta: "Read what changed",
  criterion_create: "Write checks (criteria)", criterion_query: "List a ticket's checks", criterion_update: "Attach evidence or give a verdict",
  dense_search: "Search by meaning (diagnostic)", describe: "Look up an object's fields", describe_objects: "List object types",
  doc_create: "Write a document", doc_edit: "Edit a document", doc_query: "List documents", doc_read: "Read a document",
  doc_update: "Replace a document", doctor_dead_mail: "See undelivered messages", doctor_feed_lag: "See which seats lag behind",
  doctor_health: "Check service health", doctor_logs: "Read the logs", doctor_pains: "See reported tool problems",
  doctor_pool: "Check the seat pool", events_query: "Read the event log", find: "Search the board",
  gate_answer: "Answer a gate (a person's decision)", gate_open: "Ask a person (open a gate)", gates: "List open gates",
  get_guide: "Read a guide", inbox: "Read its inbox", link_create: "Link two records", link_delete: "Remove a link",
  link_query: "List links", lookup: "Look up decisions and lessons", message_query: "Read a ticket's thread",
  message_read: "Read one message", message_send: "Send a message", participants: "List the team",
  preflight: "Check host memory before starting seats", propose_fix: "Propose a fix for an admin",
  reap: "Stop a seat's shell", record_claim: "Record a claim", record_decision: "Record a decision",
  record_lesson: "Record a lesson", record_status: "Report its outcome", resume: "Resume a paused seat",
  resume_self: "Resume after a restart", session_query: "List seat sessions", set_binding: "Make a decision binding",
  spawn: "Start a seat", subscribe: "Turn on its event feed", ticket_create: "Create tickets", ticket_query: "Find tickets",
  ticket_read: "Read a ticket", ticket_update: "Change a ticket", topic_propose: "Propose a Library document",
  topic_research: "Research a Library topic", whoami: "Know who it is", why_stuck: "Explain why a ticket is stuck",
  withdraw_claim: "Withdraw a claim", withdraw_decision: "Withdraw a decision", workflow_check: "Check a workflow",
};
export const toolLabel = (id: string): string => TOOL_LABEL[id] ?? plain(id);

/** Plain names for workflow-wide permissions; PERMISSION_HELP is the hint line. */
export const PERMISSION_LABEL: Record<string, string> = {
  set_title: "Rename tickets", edit_ticket: "Edit tickets", assign: "Assign tickets", set_design_ref: "Set a ticket's design",
  claim: "Take unassigned work", evidence: "Attach evidence", task_verdict: "Judge tasks", binding: "Make binding decisions",
};

/** What a tool needs before the board lets a role use it (templates.tool_needs names a role field). */
export const NEED_LABEL: Record<string, string> = {
  gate_answerer: "answers gates", may_spawn: "may start seats", binding: "binding decisions", may_create: "may create tickets",
  criterion_author: "writes checks",
};

export const DOC_TYPE_LABEL: Record<string, string> = {
  design: "Design", strategy_hl: "High-level strategy", strategy_ll: "Low-level strategy", domain: "Domain notes",
  report: "Report", note: "Note",
};

/** The board's preconditions in words (its closed vocabulary; the key stays in the tooltip). */
export const PRECONDITION_LABEL: Record<string, string> = {
  actor_is_assignee: "the person or seat assigned to it", assignee_or_claim: "its assignee, or a role that may take unassigned work",
  blockers_released: "everything blocking it is released", children_released: "its child tickets are released",
  checker_criteria: "its checker's criteria exist", criteria_min: "it has enough checks", design_ready: "its design is ready",
  design_ref: "it names its design", design_signed: "its design is signed off", evidence_all: "every check has evidence",
  human_epic_owner: "the epic's owner is a person", kind_in: "it is the right kind of ticket", not_terminal: "it is not finished",
  role_in: "a named role moves it", signoff_lint: "the design passes the sign-off checks", story_cap: "the epic is under its story cap",
  verdicts_passed: "every check passed",
};

/** A one-line title per Validate problem (the code stays in a small monospace detail). */
export const PROBLEM_TITLE: Record<string, string> = {
  schema: "The definition is malformed", schema_version: "Unknown definition format", unknown_status: "Unknown status",
  unknown_kind: "Unknown ticket kind", unknown_role: "A rule names a role that does not exist",
  unreachable_status: "A status no ticket can reach", dead_end_status: "A status tickets can't leave",
  kind_without_checker: "Nobody checks this kind of work", checker_is_doer: "A builder checks its own work",
  self_approval: "A gate approves itself", gate_unanswerable: "No person can answer a gate",
  role_without_spawner: "Nobody can start this role", card_missing: "The role has no instructions",
  unknown_capacity: "The role has no seat limit", cap_below_1: "A limit of 0 stops all work",
  kernel_stripped: "The role lost the basic tools", unknown_hook: "Unknown automatic behaviour",
  hook_param: "Unknown setting on an automatic behaviour", unknown_predicate: "Unknown board check",
  gate_without_precondition: "A gate with no condition", transition_without_precondition: "Anyone can make this move",
  bundle_missing: "The role has no tools", self_check: "A role judges its own work",
  escalation: "The role can grant itself a person's decision", unusable_tool: "A ticked tool the role can't use",
  dry_run_stall: "A test epic gets stuck", human_spawnable: "A person's role is marked as a seat",
  non_agent_role: "A person's role is marked as a seat", agent_answerer: "A seat answers a gate",
};

/** The place Validate's "Go to" button names: a role form field, a hook, a gate, a cap or the dry run. */
export const FIELD_NAME: Record<string, string> = {
  ...HOOK_LABEL, ...GATE_LABEL, ...CAP_LABEL,
  spawned_by: "Started by", card: "Card", capacity_class: "Capacity class", bundle: "Tools", criterion_checker: "Checks criteria",
  max_concurrent: "Max concurrent seats", dryrun: "Test walk", label: "Label", model: "Model", effort: "Effort",
};

const FIELD_WORD: Record<string, string> = {
  may_spawn: "May start", card_md: "the card", card: "a shipped card", max_concurrent: "Max concurrent seats",
  capacity_class: "Capacity class", criterion_checker: "Checks criteria", criterion_author: "Writes checks",
  gate_answerer: "Answers gates", role_in: "who may move it", spawnable: "Can be started",
};

/** A board problem message (or its why/fix line) with the ids swapped for the names people see. */
export function plainText(text: string, wf?: WorkflowDef): string {
  const role = (id: string) => { const r = wf?.roles.find((x) => x.id === id); return r ? roleLabel(r) : id; };
  return text
    .replace(/role '([^']+)'/g, (_, id: string) => `the ${role(id)} role`)
    .replace(/gate '([^']+)'/g, (_, id: string) => `the "${GATE_LABEL[id] ?? plain(id)}" gate`)
    .replace(/hook '([^']+)'/g, (_, id: string) => `"${HOOK_LABEL[id] ?? plain(id)}"`)
    .replace(/caps\.([a-z_]+)/g, (_, id: string) => `"${CAP_LABEL[id] ?? plain(id)}"`)
    .replace(/transition ([a-z_]+)→([a-z_]+)/g, (_, a: string, b: string) => `the move ${plain(a)} → ${plain(b)}`)
    .replace(/(status|kind) '([^']+)'/g, (_, w: string, id: string) => `${w} "${plain(id)}"`)
    .replace(/by '([^']+)'/g, (_, id: string) => `by ${role(id)}`)
    .replace(/'([a-z][a-z0-9-]*)', which is not a role/g, (_, id: string) => `"${id}", which is not a role`)
    .replace(/\['([^\]]+)'\]/g, (_, ids: string) => ids.split(/',\s*'/).map(role).join(", "))
    .replace(/no tool bundle/g, "no tools").replace(/ \(`[a-z_]+`\)/g, "")
    .replace(/tool ([a-z]+_[a-z_]+)/g, (_, id: string) => `the tool "${toolLabel(id)}"`)
    .replace(/the ([a-z_]+) permission/g, (_, id: string) => `the "${NEED_LABEL[id] ?? PERMISSION_LABEL[id] ?? plain(id)}" permission`)
    .replace(/`([a-z_]+)`/g, (_, id: string) => `"${FIELD_WORD[id] ?? plain(id)}"`)
    .replace(/\(card_md, or an agent-home card named by "a shipped card"\)/, "")
    .replace(/\b(max_concurrent|capacity_class|card_md)\b/g, (id: string) => FIELD_WORD[id] ?? plain(id))
    .replace(/is spawnable/g, "can be started").replace(/may spawn/g, "may start")
    .replace(/ \(role_in\)/g, "").replace(/declares no precondition/g, "has no rule for who may make it")
    .replace(/\bthis edge\b/g, "this move")
    .replace(/\b[a-z]+(?:_[a-z]+)+\b/g, (id: string) => FIELD_WORD[id] ?? PRECONDITION_LABEL[id] ?? plain(id))
    .replace(/\s{2,}/g, " ").trim();
}

/** A board tool's one-line description with its snake_case words spelled out (tool names by their plain name). */
export const plainHint = (text: string): string =>
  text.replace(/\b[a-z]+(?:_[a-z]+)+\b/g, (id) => (TOOL_LABEL[id] ? `"${TOOL_LABEL[id]}"` : id.replaceAll("_", " ")));
