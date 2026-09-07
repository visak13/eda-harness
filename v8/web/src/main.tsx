import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api/client";
import { identity } from "./auth/identity";
import { subscribeFeed, type FeedEvent } from "./live/feed";

interface WhoAmI {
  participant: { id: string; handle: string; role: string };
  tickets: string[];
}

// The walking skeleton: identity round-trips to an authenticated /v1/whoami, and the
// live feed reaches the browser through the fetch-stream. No Folio component yet — this
// only proves the three seams end-to-end (strategy_hl Phase 3 / poc-then-iterate).
function Hello(): React.JSX.Element {
  const [who, setWho] = useState<WhoAmI | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<FeedEvent[]>([]);

  useEffect(() => {
    api<WhoAmI>("/v1/whoami")
      .then(setWho)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    const stop = subscribeFeed(
      (ev) => setEvents((prev) => [...prev, ev].slice(-100)),
      { onError: () => void 0 },
    );
    return stop;
  }, []);

  return (
    <main style={{ fontFamily: "Segoe UI, system-ui, sans-serif", padding: 24, maxWidth: 760 }}>
      <h1>edp8 · walking skeleton</h1>
      <p>
        identity (as): <strong data-testid="identity">{identity()}</strong>
      </p>
      {error ? (
        <p data-testid="whoami-error" style={{ color: "crimson" }}>
          whoami failed: {error}
        </p>
      ) : (
        <p>
          whoami handle:{" "}
          <strong data-testid="whoami-handle">{who ? who.participant.handle : "…"}</strong>
        </p>
      )}
      <h2>
        live feed events (<span data-testid="event-count">{events.length}</span>)
      </h2>
      <ul data-testid="event-list">
        {events.map((e, i) => (
          <li key={e.id ?? i} data-testid="event-item">
            seq {e.seq} · {e.kind ?? "?"} · {e.subject_id ?? ""} · {e.id ?? ""}
          </li>
        ))}
      </ul>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Hello />
  </StrictMode>,
);
