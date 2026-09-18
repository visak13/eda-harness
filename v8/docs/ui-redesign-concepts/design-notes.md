# Garden planner — owner approval direction

**Recommendation:** one dominant design surface, an adjacent approval row, and a plain conversation column. Warm paper is the default; Obsidian retains the same hierarchy. This is a visual proposal for owner approval, not application implementation or tested behavior.

## Delivered images

- `garden-planner-01-approval.png` — 1536 × 1024 desktop concept. Complete design excerpt, approval actions, recipient and message composer visible together.
- `garden-planner-02-supporting-views.png` — 1499 × 1049 contact sheet: ticket reply, scoped Library, embedded Usage, narrow Obsidian.

Both are actual built-in image_gen outputs, copied byte-for-byte. No hand-rendered substitute, raster retouching, or separate icon assets. `generation-prompts.md` contains the exact two prompts; `run-evidence.json` records output paths, dimensions, hashes and review. `visual-tokens.css` specifies proposal tokens only and is not connected to any app.

## Visual judgment and measurable bars

The desktop achieves the strongest hierarchy: the garden design dominates, actions sit above it, and conversation has a clearly subordinate lane. Folio contributes serif/sans contrast and the quiet warm palette only. The proposed layout replaces Folio's text-led overview and information rail.

Implementation targets at 1440 × 960 CSS pixels: 192px sidebar, 32px outer content padding, 32px column gap, 720px design lane and 336px conversation lane. At 1440 × 900, compress header spacing and fit the full preview proportionally. All four excerpt edges, both approval buttons, recipient field and Send must remain visible without initial scrolling. A full-design viewer supplies zoom; fit-to-view must never crop.

- Design occupies at least 60% of the content width below the action row. One dominant bounded preview; zero equal-weight metric cards on the approval screen.
- Title 36/42px; section titles 24/30px; body 16/24px; metadata at least 14/20px. Body lines stay within roughly 45–75 characters. The generated title is larger than this target.
- Use 8px spacing increments, 24–32px section separation, 6px control corners, 1px dividers. No gradients or decorative shadows in the board shell.
- Minimum 44 × 44px interactive targets, 16px button labels, visible 2px focus outline with 2px offset. Keyboard order follows visual order; state must never rely on color alone.
- Body contrast at least 4.5:1; control boundaries/focus at least 3:1 where required. Token pairs pass text contrast by calculation; generated pixels and a real implementation have not been accessibility tested.
- Obsidian canvas and rail must be exactly `#000000`; composer/surface `#111111`. Keep the original design artwork's colors. Use dark ink on the light orange primary button, not white.
- At widths below 1100px, stack preview, approval actions and conversation; collapse sidebar into a labeled navigation menu. At 390px, no horizontal page scroll; actions remain full-width and at least 44px tall. A long design can scroll naturally before conversation.

## Exact labels and intended behavior

**Navigation:** `Epics`, `Library`, `Usage`, `Seats`; compact `Needs you 2`, plus `Find`. Needs you is a notification list, not another dashboard. Each item names its epic/ticket and needed action. One click opens the relevant epic or ticket directly, selects the referenced design/version or question, and focuses that context. No intermediate Decisions visit. Reading a notification does not resolve an outstanding request.

**Epic:** `Garden planner`, `Needs your approval`, `Design ready for review`, `Version 3 · Designer`, `Approve design`, `Request changes`, `Open full design`, `Conversation`, `About this design`. Approve design approves the displayed version only and changes its state to `Design approved`. Disable duplicate submissions while pending; retain context and show a plain error if it fails. If the version changes, refresh the preview and require review of that version. Never imply approval of unseen updates.

Request changes focuses the same conversation composer, addressed to Designer, with visible mode `Changes requested`. Sending the required message records feedback against that version and sets `Changes requested`; `Cancel` exits that mode. A normal message alone does not approve or reject a design. These are proposed interactions, not features verified by the images.

**Conversation:** `To: Designer`, `Write a message…`, `Send`. Recipient is a named person/seat selector, with Designer selected for this request. Plain author, timestamp, message; no raw event kinds. Empty messages cannot send. Preserve drafts on errors and while switching views; show `Sending…`, then the delivered message. Ticket `Planting labels` uses the same composer under the question `Should labels include sowing dates?`.

**Manage work:** secondary menu labeled `Manage work` holds technical lifecycle operations such as `Pause work`, `Resume work`, `Retry failed work`, `Cancel work`, and `View technical history`, exposed only when relevant. Destructive actions explain consequences before confirmation. Keep raw lifecycle details out of the owner conversation.

**Library:** `Epic: Garden planner` is the visible scope. Four categories exactly `Design`, `References`, `Evidence`, `Deliverables`. Default to Design; lead with `Spring garden concept`, `Version 3 · Awaiting approval`, `Open design`. References contain source material, Evidence contains validation records, Deliverables contains completed outputs. Opening a design preserves its epic/version and contextual approval controls. With no epic selected, ask the owner to choose an epic rather than show every record. Never silently mix projects.

**Usage:** lives inside the board shell. Display `Illustrative data`, `Updated 2 min ago`, `Times shown in IST`, and `Example values only` for this concept. Separate provider sections with rules, not cards. Values mean percent used, not remaining:

| Provider | Window | Illustrative usage | Reset label |
| --- | --- | --- | --- |
| Claude | 5h window | 42% used | Resets today, 18:30 |
| Claude | Weekly | 68% used | Resets Mon, 09:00 |
| Fable | Unavailable | No usage connection | Freshness and reset unavailable |
| Codex | 5h window | 24% used | Resets today, 19:10 |
| Codex | Weekly | 51% used | Resets Tue, 09:00 |

Production behavior must derive freshness and reset labels per provider from actual responses. Mark data older than five minutes `May be out of date`, retain its timestamp, and offer `Refresh`. Unknown usage/reset is unavailable, never zero. Show timezone and an absolute reset date/time on focus or activation. The illustrative numbers do not assert real provider limits or integration support.

## Suggested ten-icon family — semantics only

Use a 24px grid, 20px optical size, 1.75px uniform stroke, round caps/joins, no fill, and one consistent optical weight. Render beside text; icon-only controls require accessible labels.

| Name | Suggested glyph and meaning |
| --- | --- |
| Decisions | Rounded check inside a circle; contextual approval/history, not sidebar destination |
| Epics | Four rounded tiles; project-level group |
| Seats | Person bust with small seat/back curve; assigned agent or human |
| Library | Two-page open book; scoped artifacts |
| Find | Magnifier; search |
| Add | Plus; create |
| Close | Cross; dismiss |
| Chevron | Single directional angle; expand or navigate |
| Copy | Two offset rounded sheets; copy value/link |
| External link | Up-right arrow leaving an open square; open full artifact |

This is a proposed family specification, **not a final icon asset set**. Separate vector generation and optical QA are later work.

## Provenance and shortcomings

All epic, ticket, messages, artwork and usage content are synthetic. Only textual style observations from the user-provided Folio reference informed generation; no private board content, screenshot file, credentials or service data were supplied to image_gen. Two fresh-image calls used text prompts only, with no retries. No application code, services or processes were changed.

The desktop's primary labels are legible on visual inspection. Tiny labels in the contact sheet's Library thumbnails are garbled and must not be transcribed. Some metadata is smaller than the specified 14px minimum. Garden artwork changes across views rather than representing a consistent version; actual views must use one shared artifact. Provider marks and navigation icons are inconsistent and unapproved; use the family above and provider text labels. The generated desktop primary button has subtle shading and the title is oversized. Contact-sheet frames are presentation devices, not four panels for a single screen.

Obsidian is visually near-black but does **not** meet exact true-black pixels: one sampled background pixel is `#090909`. Its light-orange button also uses white text; the token spec corrects this to dark ink. The image limit prevents another generation, so these remain honest raster shortcomings. Exact flat colors are defined in `visual-tokens.css`. Progress lengths are illustrative and must be computed from values in implementation. No interaction, responsiveness or accessibility testing is claimed.
