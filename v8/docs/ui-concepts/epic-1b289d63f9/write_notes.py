import sys
sys.dont_write_bytecode=True
from pathlib import Path
from build_concepts import THEMES, contrast

root=Path(__file__).resolve().parent
text='''# edp8 board — three visual directions

**Recommendation: A / Signal, then C / Studio, then B / Folio.** Signal gives the best balance for an all-day board: continuous white reading surfaces, a quiet navigation selection, and ruled epic rows that make status and progress easy to scan. Studio ranks second because its soft grouping makes separate work areas easier to recognize, though the filled navigation and repeated cards draw more attention. Folio is the most distinctive and strongest for reading narrative reports; its serif epic titles and outlined badges add typographic texture to a tool that also needs rapid operational scanning. These are design judgments, not results from a usability study. The decision for this round is simply **A, B, or C**.

## Open the rendered concepts

View at 100% for an honest assessment of density and type. Desktop pages are **1440 × 900**; compact style tiles are **1200 × 900**. All PNGs are saved locally, with editable HTML/CSS alongside them.

| Direction | My inbox | Epics | Style tile |
|---|---|---|---|
| A · Signal | [Inbox](concept-A-inbox.png) | [Epics](concept-A-epics.png) | [Palette & components](concept-A-tiles.png) |
| B · Folio | [Inbox](concept-B-inbox.png) | [Epics](concept-B-epics.png) | [Palette & components](concept-B-tiles.png) |
| C · Studio | [Inbox](concept-C-inbox.png) | [Epics](concept-C-epics.png) | [Palette & components](concept-C-tiles.png) |

The screenshot content is held constant: owner identity; 8 waiting items; 0 open gates; 5 conversations; 5 documents awaiting sign-off; the expanded S2 engineer report; three humans and the architect seat; and the existing conversation/kind/recipient/message/Send composer. Epics retains the 21 count, filter controls, and the eight identifiable rows visible in the reference, with their IDs, order, dates, progress and statuses. Only those eight known rows are rendered; the other 13 are not invented. Long epic titles preserve the visible source excerpts and wrap to two lines. Sidebar snippets retain ellipsis behavior. The report continues behind the composer as in the reference viewport; these are static visual studies, not interactive application substitutes.

The supplied epic and ticket screenshots inform the shared sign-off, thread, document and status vocabulary. This round renders the two requested pages in each direction. The production `ui.py` has not been edited.

## A — Signal

A precise light workspace with cool neutral panels, white report paper, and continuous ruled epic rows.  
Small rounded controls and restrained semibold headings make a dense operational surface feel orderly.

**Orange allowed:** the small brand mark, a 3 px active-nav rail with a pale selected wash, primary buttons, focus outline, the sign-off edge, epic-row stripes, and the existing live-update pill when new events actually arrive. **Orange excluded:** body prose, metadata, generic links, context-panel backgrounds, avatars, progress completion, and neutral status badges. No live-update count is invented for the mockups.

**Shape and type:** Segoe UI interface and report; Consolas IDs. Page 24/32 px; channel 18/26; report 14/24 with 17/25 headings. Controls and cards use 6 px radius; list rows have square edges and 1 px bottom rules. The report summary uses a neutral header band. The selected item is visible without a large saturated fill.

**Accessibility:** deep orange `#B94712` against white is **5.29:1**, equally valid for orange text on white or white text on the orange button. Orange against the selected wash must also meet 4.5:1. Neutral secondary text stays dark enough to remain useful. Pale borders distinguish surfaces; darker dedicated control borders identify inputs.

**Token implications:** replace the dark root colors with column A below; switch `color-scheme` to `light`. Add separate control-border, brand-hover/active, selected-background, semantic foreground/background, radius and type tokens. Continuous epic rules and the neutral report-summary band require selector changes in addition to root values.

## B — Folio

A white editorial workspace with warm paper side panels, fine rules, and square control edges.  
Georgia headings and report text give long evidence narratives a deliberate reading rhythm while controls remain sans serif.

**Orange allowed:** the square brand mark, active-nav text and 3 px rail, primary action, focus, sign-off top rule, epic stripes, and the conditional live-update pill. **Orange excluded:** full navigation fills, broad paper washes, report paragraphs, dates, code, completion bars and all semantic status backgrounds. The active nav remains unfilled; its orange text and rail carry selection.

**Shape and type:** Georgia page 30/34 px, channel 21/26, report 16/26 with 20/25 headings; Segoe UI controls and report summaries; Consolas IDs. Cards and controls use 2 px radius. Badges are square, lightly filled and outlined in their status color. The epic list begins with a 2 px dark rule; rows remain flat. Shadows are absent.

**Accessibility:** burnt orange `#A74317` against white is **6.07:1** for either text/fill polarity. Thin warm surface rules are decorative; input boundaries use `#928B7D`, with a measured white-ground contrast above 3:1. Serif text is 16 px in the report and epic titles; identifiers and operational controls remain sans/monospace for clarity.

**Token implications:** use column B; add distinct heading and report font tokens instead of changing every element to serif. Root colors alone cannot create the square outlined badges, sign-off top rule, flat document treatment, and serif hierarchy; these need the corresponding selector overrides. Warm panel color belongs to side surfaces, with a pure-white central canvas.

## C — Studio

A soft, modular workspace using rounded neutral cards and white context blocks to separate related information.  
A filled orange active-nav item provides a firm location cue while charcoal text keeps the working content calm.

**Orange allowed:** the compact brand mark, one filled active-nav item, primary buttons, focus, sign-off edge, epic stripes and conditional live-update pill. **Orange excluded:** report backgrounds, context cards, paragraph text, conversation snippets, non-selected nav items, completion bars and neutral metadata. Review remains a muted plum semantic color, not an orange alert.

**Shape and type:** Segoe UI throughout, with 24/32 px semibold page titles, 18/26 channel headings and 14/24 report text. Cards and controls use 14 px radius; nav uses 12 px; badges use pills. Rounded epic cards have 6 px gaps. The report sits on a neutral inset surface; context empty state and people list sit on white cards. Shadows are limited to 4 px vertical offset / 16 px blur at about 3% opacity for primary cards.

**Accessibility:** terracotta `#B84016` against white is **5.55:1**, supporting white active-nav text and white primary-button text. The 14 px control radius does not reduce the 40 px control height. Status text is measured against each pale fill; hue is reinforced by an explicit written label.

**Token implications:** use column C, add role-specific surface and radius tokens, and route the selected nav background to `--brand` with white text. Keep white canvas and raised surfaces separate from the neutral inset report/epic cards. White context blocks, soft shadows and a 12 px nav radius require local selector changes.

## Exact existing root-token replacements

Source reviewed: `C:/Projects/Learning/eda-base3/v8/src/edp8/ui.py`, `_CSS`, starting at the `/* Tokens */` block. Values below describe a later implementation of the selected direction; they are not a patch applied to the live board.

Keep `--rail-w:64px` and `--side-w:272px` for this re-skin. Keep the existing responsive layout rules. The unused legacy rail width should not be used to shift the composer. Set `color-scheme:light` for all three.

| Existing token | A · Signal | B · Folio | C · Studio |
|---|---|---|---|
'''
mapping={'--rail':'panel','--app':None,'--panel':'panel','--raised':'raised','--hover':'hover','--border':'border','--text':'text','--secondary':'secondary','--muted':'muted','--brand':'brand','--cyan':'brand','--success':'success','--warning':'review','--danger':'danger','--link':'link','--focus':'brand'}
for token,key in mapping.items():
    vals=[('#FFFFFF' if key is None else ('#775B19' if token=='--warning' and k=='C' else t[key])) for k,t in THEMES.items()]
    text+='| `'+token+'` | '+' | '.join('`'+v+'`' for v in vals)+' |\n'
text+='''
`--cyan` is a legacy token name used for the selected-nav rail and epic stripes; its value becomes orange. Do not substitute orange for all existing links. `--warning` remains amber for gate warnings, including Studio; review has its own semantic pair.

## Additional tokens needed for the specified appearance

| Proposed token | A | B | C |
|---|---|---|---|
'''
newmap={'--brand-hover':'brand_hover','--brand-active':'brand_active','--selected-bg':'tint','--control-border':'control','--radius-control':'radius','--radius-card':'radius','--done-fg':'success','--done-bg':'success_bg','--blocked-fg':'danger','--blocked-bg':'danger_bg','--progress-fg':'progress','--progress-bg':'progress_bg','--review-fg':'review','--review-bg':'review_bg'}
for token,key in newmap.items():
    text+='| `'+token+'` | '+' | '.join('`'+t[key]+'`' for t in THEMES.values())+' |\n'
text+='''
Introduce `--on-brand:#FFFFFF`, `--canvas:#FFFFFF`, and `--header-bg:#FFFFFF` in every direction. Add `--surface-sidebar`, `--surface-context`, `--surface-report`, and `--surface-epic` so existing `--panel` reuse does not force every surface to look the same. Sidebar/context use the panel swatch in each direction. Report and epic surfaces are white in A and B; their C equivalents use the neutral panel swatch. All three main reading canvases remain pure white.

Use `--font-ui:"Segoe UI",sans-serif`, `--font-mono:Consolas,monospace`; A/C heading and report fonts inherit UI, while B uses `Georgia,serif`. Radius and font tokens are new: the current application hard-codes these values. The delivered `concept-*.css` files are self-contained study styles using a shared mockup vocabulary, not drop-in replacements for the application's `_CSS` string.

## Hard-coded CSS that must follow the tokens

Changing the root alone leaves dark remnants. The selected direction must also cover these concrete selectors:

- `.channel-header` currently uses `#25232bf7`; route it to the white header surface.
- `button` must explicitly use white text. It currently inherits light-theme foreground from the form reset. Replace purple `button:hover` with the selected `--brand-hover`; add `:active` using `--brand-active`.
- `input::placeholder` currently uses `#aaa4af`; use the measured muted-text token. Use the darker control-border token on inputs/selects while retaining quiet borders for decorative card divisions.
- `.badge` uses `#3b3744`, and `.s-done/.s-pass`, `.s-blocked/.s-fail`, `.s-in_progress/.s-ready`, `.s-in_review/.s-partial` use hard-coded dark fills. Assign explicit foreground/background pairs from the table. Drafted and Dropped use neutral hover background / secondary foreground.
- `.alert`, `.alert-ok`, `.btn-fail` and their hover states must use pale semantic backgrounds or deliberately dark semantic fills with white text; remove the remaining hard-coded dark alert colors.
- `.signoff-card`, its `details`, `.epic-row`, `.nav-link.active`, `.empty-state` and `.people-list` need the geometry/surface treatment specified for each direction.
- `.composer-card`, `.mention-menu` and `.live-pill` have dark-theme shadows such as `#0008` and black at 40%. Use restrained neutral shadows (none for Folio), with measured text and focus colors on every surface.
- `.live-pill:hover` currently brightens the fill using a filter; use the darker hover token and no brightness filter so white text retains contrast.
- Thread/question cards, kanban cards, document readers and right context panels must consume the same chosen surface, text and status tokens. Preserve all positions, controls and behavior; this is visual scope only.

## Measurable visual acceptance bars

- At **1440 × 900**, sidebar is **272 px**, header **76 px**, inbox context **280 px**, content gutter **24 px**. The context divider is at **x=1160**. No new rail, tabs, widgets, navigation sections or actions.
- Composer occupies the existing content column: **x=296…1136**, **y=786…900**, with its card starting at **x=348**. It does not intrude into the context panel. Conversation, kind, recipient, message and Send remain in that order.
- The eight known epic rows retain aligned progress/date/status columns and fit through the eighth row within the 900 px capture. Epics has no context panel or composer because neither exists on that reference page.
- Main text and active labels: **at least 4.5:1** against their actual background; primary reading text exceeds **14:1** on white in all concepts. Primary button text passes **4.5:1** in default, hover and pressed states. Controls/focus boundaries target **3:1**. Decorative card borders intentionally stay lighter and must not be the only indicator of an interactive control.
- Use **40 px** control/nav height, **2 px** focus outline with **2 px** offset, and a **3 px** epic/sign-off accent. Spacing comes from **4, 8, 12, 16, 24, 32 px**. Main report text is at least **14 px**, or **16 px** for Folio. IDs are **11–12 px**; compact section labels are **10–11 px**, uppercase, and never used for report prose.
- Status is always named in text. Done is green; blocked is red; in progress is blue; review is ochre for A/B and muted plum for C. Empty gates remain neutral. Orange never substitutes for the four semantic states.
- Saturated orange stays below **2% of the page area** in these baseline captures. It is restricted to the enumerated accent roles; no gradients, large orange surfaces or decorative illustrations.
- No horizontal page overflow, clipped controls, missing avatars, unloaded fonts or overlapping context text. Intentionally truncated sidebar snippets, source-truncated epic titles and the continuing report are the only text crops. In the production UI, scrolling must continue to expose the complete report and preserve the existing composer behavior.

## Verification and editable sources

All nine PNGs were rendered from local HTML/CSS in Chromium at device scale factor 1, then visually inspected. `render-checks.json` records viewport, content and composer geometry. `contrast-checks.json` records calculated sRGB relative-luminance ratios for text, button states, input borders and semantic label/fill pairs. These checks establish visual/contrast properties, not a full interactive accessibility audit.

'''
text+='| Contrast pair | A | B | C |\n|---|---|---|---|\n'
for label,key,bg in [('Orange / white','brand',None),('White / hover','brand_hover',None),('White / pressed','brand_active',None),('Muted / white','muted',None),('Input border / white','control',None),('Done label / fill','success','success_bg'),('Blocked label / fill','danger','danger_bg'),('In-progress label / fill','progress','progress_bg'),('Review label / fill','review','review_bg')]:
    text+='| '+label+' | '+' | '.join(f'{contrast(t[key],t[bg] if bg else "#FFFFFF"):.2f}:1' for t in THEMES.values())+' |\n'
text+='''
Editable files: `concept-A.css`, `concept-B.css`, `concept-C.css` and the nine corresponding `.html` files. `build_concepts.py` generates them and reuses the application's existing avatar/icon SVG functions read-only. `render_concepts.mjs` captures PNGs using a local Chromium binary (override its path with `CONCEPT_CHROME`); `qa_concepts.py` checks dimensions and color ratios and creates review contact sheets. `palette.json` holds the raw study values. All generated output is confined to this directory. No production code, stories, rollout plan or design sign-off was created.
'''
(root/'concepts.md').write_text(text,encoding='utf-8')
print('Wrote concepts.md')
