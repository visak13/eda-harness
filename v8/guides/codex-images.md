# Asking a codex seat for images
<!-- roles: architect, engineer, adversary -->

A codex seat is a normal fleet seat running on the codex harness (a GPT model from the role's catalog, e.g.
`gpt-6-astra`), spawned on a task ticket like any other seat. This page covers only how to get images out of it
and back to the board. How to spawn, brief and check the seat is in your role card and the ticket's strategy.

## 1. Generate: native `image_gen` into a named directory
- The seat has codex's built-in image generator (`image_gen`); no API key is needed.
- In the brief, name ONE output directory inside the agent home, for example
  `.data/codex-images/<ticket-id>/`, and say: *"generate with image_gen and save every PNG into
  `.data/codex-images/<ticket-id>/` with these file names: …"*.
- Without a named directory, the PNGs land in `~/.codex/generated_images/`. That is outside the seat's
  workspace, so no one else can find them.
- The seat must be workspace-write (every doing role is; the adversary is read-only and cannot save files).
- The seat cannot return an image inline in a message. A path on disk is the only hand-back.

## 2. View: point the seat at image paths
- To have the seat look at a render, screenshot or reference, give it the file paths in the brief or a
  steer (`message_send` on its ticket). It opens each one with its native `view_image` tool.
- One image per path, named explicitly. A directory name alone is not viewed.

## 3. Pick up: collect and attach
- When the seat reports done, list the named directory and check every file you asked for is there.
- Attach each image to the board with `artifact_upload(path=…)`, then `message_send(…, artifacts=[id])`
  on the ticket, or `artifact_create(form=image, …)` for a URI. The board artifact is the record; a file
  left only in `.data/` is not.
