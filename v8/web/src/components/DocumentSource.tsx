import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { DesignReview } from "./DesignReview";
import { pendingWork } from "./PendingNavigation";
export function DocumentSource({ docId, version }: { docId: string; version: number }): React.JSX.Element {
  const [source, setSource] = useState("");
  const sources = useQuery({ queryKey: ["doc-sources", docId], queryFn: () => api<{ id: string; title: string }[]>(`/v1/docs/${encodeURIComponent(docId)}/sources`) });
  return <section aria-label="Document conversation source">
    <label>Conversation source <select value={source} onChange={(e) => { if (!pendingWork()) setSource(e.target.value); }}>
      <option value="">Select source before commenting</option>
      {sources.data?.map((s) => <option key={s.id} value={s.id}>{s.title} · {s.id}</option>)}
    </select></label>
    {sources.isError ? <p role="alert">Could not load document sources.</p> : null}
    {sources.data?.length === 0 ? <p>No linked source conversation. Link this document to work before commenting.</p> : null}
    {source ? <DesignReview key={`${source}:${docId}:${version}`} source={source} docId={docId} version={version} /> : null}
  </section>;
}
