import type { Query } from "@tanstack/react-query";
import type { FeedEvent } from "./feed";

const ticketEvents = new Set(["message_sent", "status_recorded", "status_changed", "gate_opened", "gate_answered", "gate_closed", "design_reviewed", "assigned", "ticket_created", "ticket_updated", "criterion_checked", "criterion_checker_overridden"]);
const presenceEvents = new Set(["shell_dead", "shell_stalled"]);
const stable = new Set(["avatar", "whoami", "resolve", "pool", "doc-frozen"]);

/** Query-local relationships only; never guess an epic from an id prefix. */
function containsId(value: unknown, id: string): boolean {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some((item) => containsId(item, id));
  const v = value as Record<string, unknown>;
  return v.id === id || v.epic_id === id || v.ticket_id === id ||
    ["board", "epic", "ticket", "children", "docs", "artifacts", "links", "rows", "record"].some((key) => containsId(v[key], id));
}

export function affectedBy(event: FeedEvent, query: Query, cache: Query[] = []): boolean {
  const [family, id] = query.queryKey;
  if (stable.has(String(family)) || (family === "me" && id === "avatar")) return false;
  const kind = event.kind ?? "";
  const subject = event.subject_id;
  const data = (event.data ?? {}) as Record<string, unknown>;
  if (!ticketEvents.has(kind) && kind !== "doc_updated" && !presenceEvents.has(kind)) return true; // bounded fallback
  if (family === "activity" || family === "find") return true;
  if (presenceEvents.has(kind)) return family === "seats" || (family === "me" && id === "people");
  if (family === "me") return id !== "people" || kind === "assigned";
  if (family === "seats") return ["assigned", "status_recorded", "status_changed"].includes(kind);
  const related = (scope: unknown) => {
    if (!scope) return true; // unscoped index
    if (scope === subject || scope === data.scope || scope === data.parent_id || scope === data.epic_id) return true;
    if ([subject, data.parent_id].some((target) => typeof target === "string" && containsId(query.state.data, target))) return true;
    return cache.some((entry) => entry.queryKey[0] === "epic" && entry.queryKey[1] === scope &&
      [subject, data.parent_id, data.ticket].some((id) => typeof id === "string" && containsId(entry.state.data, id)));
  };
  if (family === "review-context") return id === subject || (kind === "doc_updated" && query.queryKey[2] === subject);
  if (family === "contextual") return id === subject || id === data.scope || (kind === "doc_updated" && containsId((query.state.data as { records?: unknown })?.records, subject ?? ""));
  if (family === "doc-sources") return kind === "doc_updated" || kind === "ticket_updated";
  if (family === "library") {
    // Messages cannot change an archive's docs/artifact/link inventory.
    return kind === "doc_updated" && related(query.queryKey[2]);
  }
  if (family === "epics") return kind !== "doc_updated";
  if (family === "tickets") {
    if (kind === "message_sent" || kind === "status_recorded") return false;
    const scope = query.queryKey[2] === "library"
      ? new URLSearchParams(String(query.queryKey[3] ?? "")).get("epic") : query.queryKey[2];
    return related(scope);
  }
  if (!subject) return false;
  if (family === "doc" || family === "doc-versions") return kind === "doc_updated" && id === subject;
  if (family === "artifact") return false;
  if (family === "messages") return id === subject;
  if (family === "ticket" || family === "epic") {
    return id === subject || id === data.parent_id || id === data.ticket || id === data.scope ||
      [subject, data.parent_id, data.ticket].some((target) => typeof target === "string" && containsId(query.state.data, target));
  }
  return false;
}
