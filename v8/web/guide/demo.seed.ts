// The demo project the site's product guide is photographed on (s-bcc0c06de7). Everything here is made up: a small
// team building "Tidewater", an imaginary notes app. It is seeded through the board's real /v1 routes, so every
// screenshot shows the product rendering real records, never a mock. Keep it free of real people, handles, paths,
// hosts and ids: tests/test_site_guide.py scans this file and the guide pages for them.
import { createHash } from "node:crypto";

const BASE = () => process.env.EDP8_E2E_BASE!;
const ADMIN = () => process.env.EDP8_ADMIN_TOKEN ?? "t";

export async function call(method: string, path: string, body?: unknown, who: Record<string, string> = admin()): Promise<any> {
  const r = await fetch(`${BASE()}${path}`, {
    method,
    headers: { "content-type": "application/json", ...who },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = (await r.json()) as { ok: boolean; value?: any; error?: unknown };
  if (!r.ok || !j.ok) throw new Error(`${method} ${path} -> ${r.status} ${JSON.stringify(j.error ?? j)}`);
  return j.value;
}

export const admin = () => ({ "X-Admin": ADMIN() });
export const as = (id: string) => ({ "X-Participant": id });

export async function upload(ticket: string, name: string, bytes: Uint8Array, who: Record<string, string>): Promise<string> {
  const form = new FormData();
  form.append("file", new Blob([bytes as Uint8Array<ArrayBuffer>]), name);
  form.append("ticket_id", ticket);
  const r = await fetch(`${BASE()}/v1/artifacts/upload`, { method: "POST", headers: who, body: form });
  const j = await r.json();
  if (!j.ok) throw new Error(`upload ${name}: ${r.status} ${JSON.stringify(j.error)}`);
  return j.value.id;
}

/** A doc quote: the passage's line range in that version of the body. */
function docQuote(doc: string, version: number, body: string, text: string, note?: string) {
  const lines = body.split("\n");
  const at = lines.findIndex((l) => l.includes(text));
  if (at < 0) throw new Error(`"${text}" is not in ${doc}`);
  return { source: "doc", id: doc, version, text, locator: { line_start: at + 1, line_end: at + 1 }, ...(note ? { note } : {}) };
}

/** A message quote: the passage's character range in that message. */
function msgQuote(id: string, full: string, text: string, note?: string) {
  const at = full.indexOf(text);
  if (at < 0) throw new Error(`"${text}" is not in ${id}`);
  return { source: "message", id, text, locator: { char_start: at, char_end: at + text.length }, ...(note ? { note } : {}) };
}

function codeContext(path: string, line: number, snippet: string) {
  return {
    repo_root: "/srv/tidewater",
    path,
    line_start: line,
    line_end: line + snippet.split("\n").length - 1,
    commit: "4be1c07a9d2f63e8b15a0c7d94e2f6b3a8c51d20",
    dirty: false,
    snippet,
    snippet_sha: createHash("sha256").update(snippet).digest("hex"),
  };
}

/** The engineer's merge function, quoted from the Tidewater repo (src/sync/merge.ts line 18). */
export const MERGE_SNIPPET =
  "export function mergeParagraph(base: Para, mine: Para, theirs: Para): Para | Conflict {\n" +
  "  if (mine.text === theirs.text) return mine;\n" +
  "  if (mine.text === base.text) return theirs;\n" +
  "  if (theirs.text === base.text) return mine;\n" +
  "  return { conflict: true, base, versions: [mine, theirs] };\n" +
  "}";

export const WORDS =
  "Make Tidewater work offline. Edits made on a plane should sync and merge cleanly when you land, and nobody should ever lose a note.";

export const DESIGN_V1 = `# Offline sync for Tidewater

## 1. Words
Make Tidewater work offline. Edits made on a plane should sync and merge cleanly when you land, and nobody should ever lose a note.

## 2. Problem
Today an edit made without a connection is dropped when the app restarts, and two devices that edit the same note
overwrite each other: the last save wins and the other edit is gone.

## 3. Sync model
Every note is a list of paragraphs, each with a stable id. A device keeps a queue of the changes it made offline and
replays them when it reconnects.

### 3.1 Conflict rule
Two edits to different paragraphs both survive. Two edits to the same paragraph keep both versions side by side and
ask the writer to pick one; nothing is merged silently.

### 3.2 Deletes
A deleted paragraph leaves a tombstone for 30 days, so an older device cannot bring it back.

## 4. The conflict screen
It shows both versions of the paragraph, who wrote each and when, and one button per version. It must fit a phone
screen in English and in Japanese without truncating either version.

## 5. Acceptance
- A note edited on two offline devices merges with no lost paragraph.
- The conflict screen fits a 360 px wide phone in English and Japanese.
- A deleted paragraph never comes back after a sync.
`;

export interface Demo {
  epic: string;
  design: string;
  stories: Record<string, string>;
  seats: Record<string, string>;
  people: Record<string, string>;
  question: string; // the architect's question with options
  quoted: string; // the message carrying three quote cards
  attachmentMsg: string;
  videoMsg: string;
}

/** Seed the Tidewater project. `art` supplies the attachment bytes (rendered by the spec in a real browser). */
export async function seedDemo(art: { conflictPng: Uint8Array; replayWebm: Uint8Array }): Promise<Demo> {
  // -- people: the owner (Maya), a teammate (Priya) and a guest teammate across the globe (Kenji, in Tokyo)
  const people = { maya: "maya", priya: "priya", kenji: "kenji" };
  await call("POST", "/v1/participants", { type: "human", role: "owner", handle: "maya", id: "maya" });
  await call("POST", "/v1/participants", { type: "human", role: "owner", handle: "priya", id: "priya" });
  await call("POST", "/v1/participants", { type: "human", role: "guest", handle: "kenji", id: "kenji" });

  const epic = (await call("POST", "/v1/tickets", { kind: "epic", work_type: "feature", title: WORDS, words: WORDS }, as("maya"))).id;
  const arch = `architect.${epic}`;
  const qa = `qa.${epic}`;
  await call("POST", "/v1/participants", { type: "agent", role: "architect", handle: arch, id: arch });
  await call("POST", "/v1/participants", { type: "agent", role: "qa", handle: qa, id: qa });

  // -- the design, then the stories the architect cut from it
  const design = (await call("POST", "/v1/docs", { doc_type: "design", title: "Offline sync for Tidewater", body_md: DESIGN_V1, scope: epic }, as(arch))).id;
  await call("PATCH", `/v1/tickets/${epic}`, { design_ref: design }, as(arch));
  for (const text of [
    "A note edited on two offline devices merges with no lost paragraph.",
    "The conflict screen fits a 360 px wide phone in English and Japanese.",
    "A deleted paragraph never comes back after a sync.",
  ]) await call("POST", "/v1/criteria", { ticket_id: epic, text, check: "command" }, as(arch));

  const storyDefs: [string, string, string][] = [
    ["queue", "S1 Offline change queue: record every edit while offline and replay it on reconnect", "feature"],
    ["merge", "S2 Paragraph merge: edits to different paragraphs both survive; same-paragraph edits become a conflict", "feature"],
    ["screen", "S3 Conflict screen: both versions side by side, one tap to keep either, fits a phone in English and Japanese", "feature"],
    ["tombstones", "S4 Tombstones: a deleted paragraph can never come back from an older device", "feature"],
    ["spike", "S5 Spike: paragraph ids versus a full CRDT, measured on 10,000 real-sized notes", "rnd"],
  ];
  const stories: Record<string, string> = {};
  const seats: Record<string, string> = { arch, qa };
  for (const [key, title, work_type] of storyDefs) {
    stories[key] = (await call("POST", "/v1/tickets", { kind: "story", work_type, title, parent_id: epic }, as(arch))).id;
    const eng = `engineer.${stories[key]}`;
    seats[key] = eng;
    await call("POST", "/v1/participants", { type: "agent", role: "engineer", handle: eng, id: eng });
    await call("PATCH", `/v1/tickets/${stories[key]}`, { assignee: eng }, as(arch));
  }
  const crit: Record<string, string[]> = {};
  const storyCriteria: Record<string, string[]> = {
    queue: ["An edit made offline survives an app restart.", "Replaying the queue twice changes nothing the second time."],
    merge: ["Two devices editing different paragraphs both keep their edits.", "A same-paragraph edit becomes a conflict, never a silent merge."],
    screen: ["Both versions fit a 360 px phone in English and Japanese.", "Keeping either version takes one tap and syncs to every device."],
    tombstones: ["A paragraph deleted on one device stays deleted after an older device syncs."],
    spike: ["A report compares both designs on merge time, storage and lost edits."],
  };
  for (const [key, texts] of Object.entries(storyCriteria)) {
    crit[key] = [];
    for (const text of texts) crit[key].push((await call("POST", "/v1/criteria", { ticket_id: stories[key], text, check: "command" }, as(arch))).id);
  }
  // live seats: a session each (the people panel and the Work drawer show who is on what)
  let n = 0;
  for (const [key, seat] of Object.entries(seats)) {
    const ticket = key === "arch" || key === "qa" ? epic : stories[key];
    await call("PUT", `/v1/sessions/demo-${++n}`, { participant_id: seat, ticket_id: ticket, pool_id: "desk", state: "alive" });
  }
  await call("PUT", `/v1/epics/${epic}/members`, { members: ["kenji"] }, as("maya"));

  // -- the conversation, oldest first
  const say = (ticket: string, who: string, body: Record<string, unknown>) =>
    call("POST", "/v1/messages", { ticket_id: ticket, kind: "note", ...body }, as(who));

  const askText =
    "Two ways to merge an offline edit, and I need your call before S2 starts:\n\n" +
    "- **(a) Last write wins per note.** Simple and fast, but one of two offline edits to the same note is lost.\n" +
    "- **(b) Merge per paragraph.** Edits to different paragraphs both survive; only a same-paragraph clash asks the writer.\n\n" +
    "I recommend (b): your words say nobody should ever lose a note, and (a) loses one by design.";
  const ask = await say(epic, arch, { kind: "question", to: "maya", text: askText });
  const answerText = "Go with (b). Our users write long notes on flights, so losing a whole note is the one thing we can't ship.";
  const answer = await say(epic, "maya", {
    kind: "answer", to: arch, reply_to: ask.id, text: answerText,
    quotes: [msgQuote(ask.id, askText, "Edits to different paragraphs both survive", "This is the behaviour I want.")],
  });
  await say(epic, arch, {
    kind: "status",
    text:
      "Design v1 is up and the work is cut into five stories (S1 to S5). Engineers are on S1, S2 and S5.\n\n" +
      "@kenji, could you check the conflict screen against Japanese text once S3 has a build? §4 of the design says what it must fit.",
  });

  // the guest, nine time zones away, answers with a screenshot from his phone
  const png = await upload(epic, "conflict-screen-ja.png", art.conflictPng, as("kenji"));
  const kenjiText = "Checked on my phone in Tokyo: the Japanese version wraps onto three lines and the Keep button drops below the fold. Screenshot attached.";
  const kenji = await say(epic, "kenji", {
    to: arch, text: kenjiText, artifacts: [png],
    quotes: [docQuote(design, 1, DESIGN_V1, "It must fit a phone", "This is the line that fails today.")],
  });

  // the engineer quotes the code it changed
  const mergeSnippet = MERGE_SNIPPET;
  const engText = "S2's merge is in: different paragraphs merge, and a same-paragraph clash comes back as a conflict instead of a silent overwrite. 41 tests pass.";
  const eng = await say(stories.merge, seats.merge, {
    kind: "status", text: engText,
    quotes: [{ source: "code", code: codeContext("src/sync/merge.ts", 18, mergeSnippet), note: "The four cases, in order." }],
  });

  // qa checks cold and quotes the engineer, the design and the code in one finding
  const qaText = "Criterion fails on S4: a paragraph deleted on the phone came back after the laptop synced. Repro and the three passages below.";
  const quoted = await say(stories.tombstones, qa, {
    kind: "finding", to: seats.tombstones, text: qaText,
    quotes: [
      msgQuote(eng.id, engText, "a same-paragraph clash comes back as a conflict", "Merge itself is fine."),
      docQuote(design, 1, DESIGN_V1, "A deleted paragraph leaves a tombstone for 30 days", "This is the rule the laptop broke."),
      { source: "code", code: codeContext("src/sync/merge.ts", 18, mergeSnippet), note: "No tombstone check before `return theirs`." },
    ],
  });

  const webm = await upload(stories.tombstones, "tombstone-replay.webm", art.replayWebm, as(seats.tombstones));
  const video = await say(stories.tombstones, seats.tombstones, {
    kind: "answer", to: qa, reply_to: quoted.id, artifacts: [webm],
    text: "Fixed: the merge now checks for a tombstone before it restores a paragraph. The recording replays your repro on two devices; the paragraph stays deleted.",
  });
  // the builder attaches evidence; a different seat (qa) gives the verdict
  const evidence = async (key: string, title: string, body: string) => {
    const doc = (await call("POST", "/v1/docs", { doc_type: "report", title, body_md: body, scope: stories[key] }, as(seats[key]))).id;
    for (const c of crit[key]) await call("PATCH", `/v1/criteria/${c}`, { evidence_ref: doc }, as(seats[key]));
    return doc;
  };
  await evidence("tombstones", "S4 evidence: tombstone replay", "# S4 evidence\n\nThe repro replayed on two devices; the paragraph stays deleted.");
  await evidence("queue", "S1 evidence: offline queue", "# S1 evidence\n\nRestart and double-replay runs, 120 cases, all pass.");
  await evidence("spike", "S5 report: paragraph ids versus CRDT", "# S5 report\n\nParagraph ids merge 10,000 notes in 1.8 s with no lost edit.");
  await call("PATCH", `/v1/criteria/${crit.tombstones[0]}`, { verdict: "pass", note: "Replayed the repro on two devices: stays deleted." }, as(qa));
  for (const c of [...crit.queue, ...crit.spike]) await call("PATCH", `/v1/criteria/${c}`, { verdict: "pass", note: "checked cold" }, as(qa));

  await say(epic, "priya", { text: "I'll pair with Kenji on the Japanese copy for the conflict screen this week." });
  await say(epic, "maya", { text: "Can the conflict screen also show which device each version came from? People have a phone and a laptop." });

  // Maya signs the design off at its gate, and the epic moves on
  const tryCall = (m: string, pth: string, body: unknown, who: Record<string, string>) =>
    call(m, pth, body, who).catch((e) => console.log(`[guide] ${pth}: ${e}`));
  await tryCall("PATCH", `/v1/tickets/${epic}`, { status: "designed" }, as(arch));
  await tryCall("POST", `/v1/gates/${epic}/design_signoff/open`, { note: "Design v1 is ready for your sign-off: paragraph merge, tombstones, the conflict screen." }, as(arch));
  await tryCall("POST", `/v1/gates/${epic}/design_signoff/answer`, { answer: "approve" }, as("maya"));

  // where each story stands, walked through the board's own lifecycle: the architect designs, signs off and readies a
  // story; its engineer starts it and hands it in with evidence; only qa, the checker, marks it done
  const walk = async (key: string, to: string) => {
    const order = ["designed", "signed_off", "ready", "in_progress", "in_review", "done"];
    const by = (s: string) => (s === "done" ? qa : ["designed", "signed_off", "ready"].includes(s) ? arch : seats[key]);
    await call("PATCH", `/v1/tickets/${stories[key]}`, { design_ref: design }, as(arch));
    for (const status of order.slice(0, order.indexOf(to) + 1)) await call("PATCH", `/v1/tickets/${stories[key]}`, { status }, as(by(status)));
  };
  await walk("queue", "done");
  await walk("spike", "done");
  await walk("tombstones", "done");
  await walk("merge", "in_progress");
  await walk("screen", "ready");

  // Maya marks two spans as requirements; the architect links the first to a criterion and leaves the second open
  const epicCrit = (await call("GET", `/v1/criteria?ticket_id=${epic}`, undefined, as(arch))) as { id: string; text: string }[];
  const marked = (await call("POST", "/v1/requirements", { message_id: answer.id, text: "losing a whole note is the one thing we can't ship" }, as("maya"))) as { id: string };
  await tryCall("POST", `/v1/requirements/${marked.id}/link`, { criterion: epicCrit[0].id }, as(arch));
  await tryCall("POST", "/v1/requirements", { message_id: ask.id, text: "nobody should ever lose a note" }, as("maya"));

  // the rest of the board: the harness's own epic becomes an earlier Tidewater epic, plus one still being shaped
  await call("PATCH", `/v1/tickets/${process.env.EDP8_E2E_EPIC}`, { title: "Ship the Tidewater web app with sign-in and shared notebooks" }, as("owner")).catch(() => {});
  await call("POST", "/v1/tickets", {
    kind: "epic", work_type: "feature",
    title: "Let people share a notebook with a read-only link that expires",
    words: "Let people share a notebook with a read-only link that expires",
  }, as("priya"));

  return { epic, design, stories, seats, people, question: ask.id, quoted: quoted.id, attachmentMsg: kenji.id, videoMsg: video.id };
}
