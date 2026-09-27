# Changelog

All notable changes to Heronry are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Every release is on the
[releases page](https://github.com/visak13/eda-harness/releases).

## [Unreleased]

## [0.9.1]

Fixes found in the first live cutover from a source checkout to the installed app.

### Fixed
- Resuming a seat imported from the old checkout: claude could not find the seat's conversation and closed
  within a second. `heronry import` now copies the claude transcripts into the new claude folder, and a
  resume whose transcript is missing starts the seat fresh (it calls `resume_self()`) instead of closing.
- `irm .../install.ps1 | iex` on Windows PowerShell 5.1: the script shipped with a UTF-8 BOM and failed at
  `[string]$Version`. It ships without a BOM and ASCII-only.
- `heronry import`: the live `.data/models.json` wins over the root `models.json` template; a stale
  `edp8.db-wal`/`-shm` beside the target is removed before the database is replaced (the import reported
  0 epics); the report names the install folder instead of "into None".
- The board's bare address (`/`) opens the UI instead of a 404.

### Documentation
- Cutover runbook: re-point `tailscale serve` to the installed board's port (19400), and verify a fresh
  spawn and a resume with a live seat before retiring the old fleet.

## [0.9.0]

First public release. Verified hands-on on Windows; macOS and Linux are built and tested in CI and
community-tested, so please [report issues](https://github.com/visak13/eda-harness/issues).

### Added
- Heronry: the board, its seats and services, installable on Windows, macOS and Linux.
- Heronry Desktop: a native window and tray icon, shipped as MSI, DMG and deb installers (unsigned).
- The macOS DMG is for Apple Silicon Macs; on an Intel Mac, install with install.sh.
- The `heronry` command line: `init`, `start`, `stop`, `status`, `doctor`, `update`, `import`, `gui`.
- A setup wizard, harness choice (Claude Code, Codex, Pi) and in-app updates.
- One-line installers (`install.ps1`, `install.sh`) that verify every wheel against `SHA256SUMS`.
- The Design tab: workflows, models and role cards as versioned data.
- An admin console: settings, services, teammates and invites, remote access, integrations.

### Changed
- One version, 0.9.0, for the four Python packages (`edp8`, `edp-contracts`, `edp-pool`, `edp-broker`),
  the web app and the VS Code extension.
- The codex consult bridge is gone; codex runs as ordinary seats.
- Licensed under Apache-2.0 everywhere, the VS Code extension included.

### Security
- CI blocks a pull request on a new secret or on personal data (gitleaks with project rules, plus a
  byte-level PII gate over the tree and the release artefacts).
- Every release asset is listed in `SHA256SUMS` and carries a build-provenance attestation.
- Private material was removed from the tree at this release. Older commits still hold it; no live
  credential was found in them.

[Unreleased]: https://github.com/visak13/eda-harness/compare/v0.9.1...HEAD
[0.9.1]: https://github.com/visak13/eda-harness/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/visak13/eda-harness/releases/tag/v0.9.0
