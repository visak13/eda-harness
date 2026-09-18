# Revision 2 — conversation first

This revision supersedes the earlier interaction proposal. The everyday surface is the epic/ticket and its conversation. Documents receive space only when opened. Folio informs the serif/sans typography and quiet paper palette, not the layout. All content is synthetic; these images are concepts, not working screens or proof of behavior.

## Delivered references and judgment

- **revision2-epic-usage.png** — 1536 × 1024. The composer capabilities, metadata strip, document link and anchored Usage grouping are useful structural references. **Reject its visual finish:** generated dark, cloudy shading obscures the thread and violates readability. The Needs you indicator is missing. This is not an approved appearance.
- **revision2-design-review.png** — 1536 × 1024. The viewer's document/feedback arrangement is the stronger visual direction: readable engineering Markdown, shared toolbar and feedback visibly addressed to the original conversation. Its background navigation differs from the requested shell and must not be copied.

Two built-in generations succeeded; neither was retried or retouched. Exact prompts are in `revision2-prompts.md`. Source paths, source/destination SHA-256 hashes and preservation checks are in `revision2-provenance.json`.

## Layout and measurable visual bars

Paper `#F7F6F0`, sage rail/selection `#E4EADF`, ink `#252C26`, muted text `#586257`, action `#365846`, white action text. Flat solid fills; **no backdrop dimming, blur or spotlight when Usage is open**. Only the modal design viewer dims its background, using one uniform veil. Keep text contrast at least 4.5:1 and control/focus contrast at least 3:1 where required.

At 1440–1536px width, use a 192px rail and a broad conversation lane beginning around x=352, ending 32px before the right edge. The left gutter accommodates a 304px Usage widget without covering conversation or composer. On a 1440 × 900 viewport, metadata, contextual links and the entire 200–220px composer must fit initially; earlier messages scroll above the composer. Conversation plus composer receives at least 65% of the main region's height. Zero permanent design-preview panes or metric-card grids.

Page title 36/42px serif; document title 30/38px; body 16–17/24–26px sans; metadata and widget text at least 14/20px. Use 24–32px section gaps, 8px spacing increments, 6px corners, 1px rules, 20px monoline icons with 1.75px round strokes. Controls have 44px minimum targets and visible keyboard focus. Help icons retain explanatory tooltips on hover and focus. Existing help content and capabilities must survive the revision; a generic question mark does not replace them.

Viewer target: 32px vertical viewport margins, maximum width 1280px, roughly 62% document / 38% feedback. Pin the complete toolbar while document content scrolls; keep Send feedback reachable. At narrower widths stack feedback below text and preserve the toolbar actions. The document excerpt is selectable rendered Markdown, never a screenshot or split code editor. Generated screen coordinates are illustrative, not measurements of implemented components.

## Everyday epic/ticket

Primary navigation: **Epics, Seats**; small **Needs you 2** indicator. Lower rail has **Usage immediately above Find**. No primary Library or Usage destination. Needs you entries open the relevant source epic/ticket and the specific question or requested review directly.

Header: **Garden planner**; purpose: “Coordinate the planning service, API and owner workflow.” Compact strip: **Status: In progress; Owner: Morgan; Assigned seat: architect; Needs attention: Design review requested**. If blocked, show **Blocked: [plain-language reason]** in the attention field. Do not hide critical context in tooltips.

Prominent header links: **Design v3 · review requested**, **Files & evidence**, **History**, **Work**. They open contextual material without replacing the source conversation or discarding drafts. Files & evidence is scoped to this epic; cross-epic archive search lives in Find, not a duplicate Library home. Work leads to relevant work items. Rare technical operations remain under **Actions**, with existing supported operations and their help only. No invented Pause/Retry commands.

Composer: **To: architect**, selectable **Type: Message** by default, **@ Mention**, **Attach**, **Expand**, **Send**, and retained help. Keep all existing message types and capabilities; friendly displayed labels map to existing event types, without exposing raw event kinds or reducing functionality. Changing recipient/type, expanding, or opening a document retains text, mentions, attachments and pending uploads. Errors retain drafts; empty submissions are disabled. Message type selection is available to the owner, not just agents.

## Review is a view of source context

The popup and optional dedicated view share one context: **source ticket/epic + approval gate + document + reviewed version**. In this example the source is Garden planner, the document is Owner workflow, and the reviewed version is v3. These are conceptual identities, not claims about an existing API schema.

Pinned toolbar: **Epics / Garden planner**, **Owner workflow**, **Design · Version 3 · Review requested**, **Approve design**, **Request changes**, **Open in tab**, **Close**. No approval controls remain detached on the epic behind it. Opening a dedicated tab carries this same context, full toolbar, review controls and feedback composer. It does not create a context-free document page. Close in the popup restores focus to the initiating Design link; dedicated view Close returns to the source epic when the browser cannot close the tab.

Request changes opens a composer **inside** the viewer: **To: architect**, **Type: Request changes**, **Regarding: Owner workflow · v3**, **@ Mention**, **Attach**, **Expand**, **Send feedback**, **Cancel**. The note is sent into the **original source conversation**, with its document/version reference. Successful submission records the requested changes and stays in the viewer. Normal **Type: Message** comments also go to that same source conversation but do not change the approval gate. There is no separate document chat.

The everyday epic draft and the review feedback draft are separate drafts with preserved context. Switching view, closing, opening in tab or sending feedback must not overwrite the original epic draft. Share pending feedback between popup and dedicated view; reconcile successful sends to prevent duplicates. Do not discard unsent feedback when an approval action is selected.

Approve design targets only the visible reviewed version. A newer document version or stale gate state must prevent accidental approval and offer **Review latest version**. Submission errors preserve context/draft; successful changes update the source conversation and attention state. These are required behaviors, not tested features.

## History and Usage

History opens a contextual popup with **Conversation / Decisions / Status & assignments / Documents / Activity** and optional **Open in tab**. Keep the same source scope; use plain-language summaries and actor/time. Decisions are a history category, not a place the owner must visit to act.

Usage is a nonmodal anchored widget opened by the bottom button, about 304px wide and no more than 560px tall at desktop size. It may scroll internally on shorter viewports; never obscure the composer. Escape, its Close control or clicking outside dismisses it; focus returns to Usage. It does not change route or require a scrim. Label **Illustrative**, **Updated 2 min ago · IST**.

| Provider / subordinate row | Window | Example usage | Reset |
| --- | --- | --- | --- |
| Claude | 5h | 42% used | Reset today 18:30 |
| Claude | Weekly | 68% used | Reset Mon 09:00 |
| Claude → Fable | Unavailable | No percentage/bar | Reset and freshness unavailable |
| Codex | 5h | 24% used | Reset today 19:10 |
| Codex | Weekly | 51% used | Reset Tue 09:00 |

Fable remains inside Claude, not a third provider. Percentages mean used; real bar lengths must equal their values. Actual integrations must report freshness/reset per source; unknown is unavailable, never zero. These values and relationships are requested illustrative content, not verified provider capabilities.

## Honest limitations and provenance

Image 1 fails thread contrast because of substantial unwanted dark shading; its rail is also wider than specified, Usage is taller than targeted, and Needs you is omitted. Image 2 invents background Conversation/Designs/Files/Activity tabs, places Usage/Find too high, and changes the background identity. Those are generation deviations, not new navigation recommendations. It duplicates the document heading and uses more serif subsection text than specified. The visible document text and main control labels appear legible on inspection; no exhaustive glyph audit is claimed. Static images cannot demonstrate pinning, tooltips, routing, draft persistence, type menus or sending.

Only synthetic text prompts were submitted. No private board data, credentials, application source or reference-image file was sent to generation. No garden artwork appears. No application changes, service changes or icon asset set were made. Prior files were preserved byte-for-byte. The tool saved originals in its managed generated_images directory; agent-authored files and delivered copies are confined to the authorized workspace.
