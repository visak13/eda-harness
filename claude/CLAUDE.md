# Environment

- **OS:** Windows (Windows 11). Use PowerShell syntax for shell commands
  (`$null` not `/dev/null`, `$env:VAR` not `$VAR`, backtick for line
  continuation). There is no POSIX shell by default — do not assume `bash`,
  `grep`, `sed`, `awk`, `/dev/null`, or Unix path separators are available.
- **Python / package manager:** [`uv`](https://docs.astral.sh/uv/) is
  installed. Use `uv` for Python env + dependency management
  (`uv run`, `uv sync`, `uv pip ...`). Each component has its own `.venv`
  created by `uv`.

# Roles

Your role determines your job. Honor the one you are running as:

- **neuron** — Understand the code and the user's requirement **before**
  creating or editing the recipe. Then document the work, **categorized into
  its respective categories**. (You own the recipe map; you don't execute the
  work yourself.)
- **planner** — Uphold the **finite state machine (FSM)**. Drive the plan
  through its legal state transitions; do not bypass or fake them.
- **worker** — Report your result via the **`record_action_status`** MCP tool
  (status + evidence, which runs the acceptance gate). Do **not** create
  unnecessary evidence files — the report is the deliverable, not extra scratch
  artifacts.
- **reviewer** — Likewise do **not** create unnecessary evidence files.
  Additionally, **fix the issues you find in the same session**, after
  confirming the fix does not break existing behavior or logic.
