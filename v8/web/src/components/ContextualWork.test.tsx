import { it, expect } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '../test/setup';
import { renderRoute } from '../pages/testUtils';
import { ContextualWork } from './ContextualWork';

it("files-to-doc is one modal transition and preserves source context", async () => {
  const okJson = (value: unknown) => HttpResponse.json({ ok: true, value });
  server.use(
    http.get("/v1/tickets/epic-ctx/contextual", () => okJson({ ticket_id: "epic-ctx", title: "Context source", kind: "epic", status: "designed", owner: "owner", requester: "owner", assignee: null, design_ref: "design-ctx", scope: "Direct source", gates: [], events: [], records: [{ type: "doc", group: "Design", relation: "design_ref", record: { id: "design-ctx", title: "Readable design", version: 1 } }] })),
    http.get("/v1/docs/design-ctx/html", () => okJson({ id: "design-ctx", title: "Readable design", version: 1, versions: [1], scope: "epic-ctx", doc_type: "design", owner_role: "architect", html: "<p>Content</p>", body_md: "Content" })),
  );
  renderRoute("/epic/epic-ctx?view=files", "/epic/:id", <ContextualWork ticketId="epic-ctx" />);
  fireEvent.click(await screen.findByRole("button", { name: "Readable design v1" }));
  await screen.findByText("Content");
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.queryByRole("dialog", { name: "Files & evidence" })).toBeNull();
  expect(screen.getByRole("link", { name: "Open in tab" })).toHaveAttribute("href", expect.stringContaining("source=epic-ctx"));
});

it('shows unanswered requests rather than gate-only all-clear on either source kind', async () => {
  server.use(http.get('/v1/tickets/:id/contextual', () => HttpResponse.json({ ok: true, value: {
    owner: 'Morgan', requester: null, assignee: null, gates: [], blockers: [], records: [], events: [],
    unresolved_asks: [{ id: 'm-question', kind: 'question', to: 'owner' }],
  } })));
  renderRoute('/epics/test', '/epics/:id', <ContextualWork ticketId="test" />);
  await waitFor(() => expect(screen.getByText('1 unanswered request')).toBeInTheDocument());
  expect(screen.queryByText('No open requests')).toBeNull();
});
