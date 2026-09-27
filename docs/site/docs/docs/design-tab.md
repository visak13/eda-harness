# The Design tab

The **Design** tab shows the workflows your epics run on: the roles, how work moves, the gates a
human answers and the caps. Open it from the board's navigation, or go to `/ui/design` on your
board (for example `http://127.0.0.1:9400/ui/design`).

Everyone can read every workflow version and its dry run. Only an admin edits workflows. If you are
not an admin, the page says it is read-only.

If you are new to workflows, read [Concepts](concepts.md) first.

## The workflow list

The left side lists every workflow in two groups:

- **Presets**: the workflows that ship with Heronry.
- **Custom**: the workflows you made. Until you make one, it says "None yet. Duplicate a preset to
  make one."

Each row shows the workflow's name and its `id@version`, a **preset**, **published** or **draft**
badge, how many roles it has, which version it came from, and which epics pin it (or "no epic pins
it"). Click a row to open it.

## The presets

| Preset | How work flows |
|---|---|
| **Standard** | The default. Owner, architect, engineers, reviewer, qa, sme, adversary and Help, as described in [Concepts](concepts.md) |
| **Lean** | Owner → engineer → qa, with no architect |
| **Solo** | Owner → engineer, and the owner checks |

A preset and a published version are immutable. To change one, you copy it.

## Duplicate to edit

Press **Duplicate to edit** on a row, or on an open preset or published version.

- A **preset** copy gets its own id (the form suggests `<id>-custom`). It tracks the preset as its
  **upstream**.
- A **custom** workflow can be copied **as the next version** of the same workflow, or **as a new
  workflow** with a new id.

Ids use lowercase letters, digits and dashes, and start with a letter. Epics show a workflow as
`<id>@<version>`. Press **Create draft**. The copy opens as a **draft**, which you can edit.

While you edit, the badge reads **draft · unsaved**. Press **Save draft** to keep your changes.

## The panels

An open workflow has eight panels: **Pipeline**, **Roles**, **Hooks**, **Gates**, **Caps**,
**Validate**, **Dry run** and **Diff**.

### Pipeline

The pipeline view has two parts:

- **Who spawns and checks whom**: a graph of the roles, showing which role spawns which, and which
  role checks the builders' work.
- **Status flow and gates**: the statuses a ticket moves through and the gates between them. Pick an
  edge (or a row below it) to see its **preconditions**: what must be true before a ticket takes that
  step. An edge with no precondition says so: anyone may take it at any time.

### Roles

Pick a role to open its panel. A human role (such as the owner) acts in the UI and has no seat,
model or card. A seat role has these fields:

| Field | What it sets |
|---|---|
| **Label** | The name shown in the UI |
| **Model** and **Effort** | The default from the Models catalog, or the epic's pick |
| **Capacity class** | builder, planner or checker: which pool cap the role counts toward |
| **Max concurrent seats** | An optional cap for this role alone |
| **Tools** | The tool checklist. Tick the board tools the role may use |
| **Permissions** | **May spawn**, **Spawned by**, **May create**, **Authors documents** and **Workflow permissions** |
| **Card** | The role's instructions, in markdown |

Every role also gets the **kernel** tools, which are always on, whatever you tick. The Tools label
shows the count, for example "5 ticked + 7 kernel".

### The card editor

The card editor has a markdown box with a live preview beside it. If the box is empty, the shipped
card is used. **Edit a copy of the shipped card** starts you from it.

Under the editor, **Kernel preamble (always prepended, not editable)** shows the part every seat gets
first: its boot sequence, how it wakes on its feed, and the communication rules. You write only the
role-specific part. An app update ships a new preamble, and it reaches your custom roles on its own.

### Add a role

On a draft, **Add a role** creates a custom role. Pick what to **Start from** (a built-in role
template such as a builder or a checker, or **Blank**), then set its **Id**, **Label** and who it is
**Spawned by**. Press **Add role**, then fill in its fields.

### Hooks

Hooks are built-in board behaviours, such as advancing an epic on its own or keeping the review
story last. Switch one off or change its parameter. Nothing else runs: a workflow cannot add code.

### Gates

A gate stops work until a human answers it. For each gate, pick which roles answer it. The panel
shows which step the gate sits on and how many preconditions it has. A gate that no human answers is
flagged.

### Caps

Caps are the limits the board enforces on every epic pinned to this version. Each must be 1 or
more. A cap of 0 deadlocks work; it does not pause it. Concurrent seats are set per role (Roles →
Max concurrent seats) and per class in **Admin → Services → Capacity**.

## Validate

Press **Validate** to check the draft: the board's lint, then a dry run. Each problem shows as an
**Error** or a **Warning**, with **Why** it matters, the **Fix**, and a **Go to** button that opens
the panel and field where you fix it. Errors block Publish; warnings do not.

Publish is refused unless all of these hold:

- every status is reachable, and every non-final status can be left;
- every ticket kind has a checker that is not its doer;
- every role has a spawner, a card and a tool bundle;
- a human can answer every gate;
- no role can approve its own work;
- every cap is at least 1;
- the kernel preamble and tools are intact.

## Dry run

**Dry run** walks a synthetic epic with one story through the draft on a throwaway board. The
timeline shows who is spawned, which gate asks a human, and where the walk would stall. Tick
**show wakes** to also see who wakes on which event. When it works, it ends with "The synthetic
epic reached done." A stall blocks Publish.

## Diff

**Diff** compares this version with the version it came from, field by field (**Field**,
**Before**, **After**). You can pick another version to compare against.

When a preset you copied changes in a later release, your copy shows **Upstream changed**. Open
the **Three-way diff** to see the base, upstream and your version, then press **Merge into a new
draft**. The merge takes every upstream change you did not also make. A field you both changed
keeps your value and is listed for you to review.

## Publish

Press **Publish** on a draft. Publish saves the draft, runs Validate and the dry run, and publishes
only if nothing fails. Any error stops it and opens Validate.

A published version is immutable, and new epics can now pick it.

## Picking a workflow for a new epic

The **New epic** dialog has a **Workflow** picker. It lists every published version, with Standard
first and chosen by default. The epic pins your pick for its whole life, and its page shows the
`workflow@version`.

Editing or publishing a workflow never changes a running epic. The roles, cards and gates of a new
version reach only the epics pinned to it.

See the [workflow schema reference](../reference/workflow-schema.md) for every field.
