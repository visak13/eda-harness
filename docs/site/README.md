# The project site

The Heronry website, published to GitHub Pages by `.github/workflows/site.yml` when a release is published.
Built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/); versions with
[mike](https://github.com/jimporter/mike).

- `docs/` — the hand-written pages (Home, Download, Watch, the setup guide, the docs).
- `hooks/heronry_site.py` — the mkdocs hook. At build it takes the names and URLs from `edp8.brand`, generates
  the reference pages, fills the Download buttons from the latest release, copies the brand art and storefront
  stills in, and runs the PII scan over the built site (a finding fails the build).
- `hooks/sitegen.py` — the generators. The reference is never edited by hand: the command line comes from
  `edp8.cli.COMMANDS`, settings from the settings registry, the REST API from the board's OpenAPI, the MCP tools
  from `edp8.bundles`, the workflow schema from `edp8.workflow.WorkflowDef`, the models catalog from
  `edp8.model_catalog.MODEL_FIELD_DOCS`.
- `fixtures/release-latest.json` — a release in the Releases API's shape, for builds without a published release.

## Build it

From the repository root:

```sh
HERONRY_SITE_RELEASE_JSON=docs/site/fixtures/release-latest.json \
  uv run --project v8 --with-requirements docs/site/requirements.txt mkdocs build --strict -f docs/site/mkdocs.yml
```

The site lands in `docs/site/site/` (git-ignored). Leave `HERONRY_SITE_RELEASE_JSON` unset to read the live
latest release. `mkdocs serve -f docs/site/mkdocs.yml` previews it. The Watch page embeds the product video's
live player when `v8/docs/video/player/dist` is built (`npm run player:build` there); otherwise it links the MP4.

Tests: `cd v8 && uv run --with-requirements ../docs/site/requirements.txt pytest tests/test_site_reference.py`.
