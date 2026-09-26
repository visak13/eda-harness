import { useParams } from "react-router";

// S16 (owner m-cc3a6656ee): a board id pasted from a sentence ("… see /ui/ticket/s-ab12cd34ef.") can carry the
// sentence's trailing punctuation or closing quote into the route. Ids never end in those, so strip them.
const TRAILING = /[.,;:!?)\]}"'”’»]+$/;

export function cleanRouteId(raw: string): string {
  let id = raw;
  try { id = decodeURIComponent(raw); } catch { /* keep the raw text */ }
  return id.trim().replace(TRAILING, "");
}

/** The `:id` route param with trailing punctuation removed. */
export function useRouteId(): string {
  const { id = "" } = useParams();
  return cleanRouteId(id);
}
