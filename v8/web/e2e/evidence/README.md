# e2e evidence (not version-controlled)

Playwright specs write their run evidence (screenshots, measurement JSON) into this directory,
e.g. `e2e/evidence/s3-final-layout/*.png`, `e2e/evidence/r1/*.json`. Everything here except this
README is git-ignored (`v8/web/.gitignore`, S16 / owner ask m-669eca70f3): evidence is a run
output, not source.

To make evidence durable, attach it on the board — `artifact_upload(path=...)` then
`message_send(artifacts=[...])`, or cite it in a report doc — not in git. Visual-regression
baselines are different: they live in `e2e/__screenshots__/` and `*-snapshots/` and stay tracked.
