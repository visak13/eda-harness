// G2-owned view types NOT in api/types.ts (which G3a owns during G2∥G3a). At G4 these fold into
// api/types.ts in one commit (architect ruling m-1a5413aceb). Everything else G2 needs
// (DecisionsHome, SignoffRow, PersonRow, ConversationRow, ResolvedRow, EpicSummaryRow, DocHtml,
// MessageSent, Verdict, MessageKind) is imported read-only from api/types.ts.

// MessageKind wire values (schemas.py MessageKind) — G2-owned here since api/types.ts (G3a) does
// not export it; folds in at G4. The composer sends `kind`; gate/verdict paths reuse these.
export type MessageKind = "question" | "answer" | "steer" | "status" | "finding" | "deviation" | "note";

// board.resolve() shape (board.py:1191) — the composer wake preview (design §16.1). `wakes` and
// `plan` are the SAME list; the criterion names it `wakes`, the design §16.1 names it `plan`.
export interface WakeRow {
  recipient: string;
  reason: string; // primary Reason enum value (addressed | mention | on_ticket | … | recovery)
  reasons: string[]; // every reason this recipient is woken for (overlap yields >1)
  why: string; // the one-clause `why` the board attaches per recipient
  alive: boolean | null; // seat presence (alive/parked → true); null for a human/thread recipient
}

export interface ResolveResult {
  to: string | null; // the board's resolved recipient id (or null for a thread note)
  wakes: WakeRow[];
  plan: WakeRow[]; // === wakes
  note: string; // verbatim board note ("'reviewer' resolved to seat …", "nobody is woken", recovery)
}

// POST /v1/artifacts/upload → the staged artifact (design §18.1). Minimal shape the composer needs.
export interface UploadedArtifact {
  id: string;
  form: string; // "image" for png/jpeg/gif/webp; else "file"
  uri?: string;
  note?: string;
  [k: string]: unknown;
}
