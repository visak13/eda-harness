# graphify / `graphifyy` — supply-chain provenance

**Action:** s30 a1b (Stage A gate-blocker). **Date:** 2026-07-11.
**Question:** the official repo declares `graphify`, but an install pulls a package
named **`graphifyy` (doubled y)** at a wildly different version. Doubled letter +
version gap is the textbook typosquat signature. Is `graphifyy` the real
distribution channel of the `graphify` project, or an impostor?

**Method — published metadata ONLY. NOTHING WAS INSTALLED.** No `pip install`, no
`uv tool install`, no sandbox, no execution of the artifact. Every fact below comes
from a read-only HTTPS GET against the GitHub REST API, the PyPI JSON API, the PyPI
PEP 691 simple index, and the PyPI PEP 740 integrity endpoint. *Running the artifact
is not how you find out whether you should run the artifact.*

**The package's own README is NOT used as evidence anywhere in this document.** Action
a1 found the packaged README saying *"The PyPI package is `graphifyy` (double-y)... Other
`graphify*` packages on PyPI are not affiliated."* That is the package vouching for
itself — exactly what a competent impostor would also ship. It is the claim under test,
not the proof. Every link below is established from a source the impostor would **not**
control.

---

## VERDICT: **SUBSTANTIALLY STRONGER THAN SELF-ATTESTATION, SHORT OF PROOF.**

**That is the shipped sentence, and it is deliberately NOT upgraded.** The evidence for
`graphifyy` being the genuine distribution channel of the `safishamsi/graphify` →
`Graphify-Labs/graphify` repository is strong and comes from sources an impostor would not
control. The doubled-y name and the version gap are both fully **explained**, not merely
explained-away. But **two residuals stand, and one of them is a NEGATIVE RESULT, not a gap**
(§Residual risk). The user is shown them rather than told to trust us.

The single strongest fact: **the official repo's own build input declares the package
name.** `pyproject.toml` on the repo's default branch reads `name = "graphifyy"`. The
repo does not merely *mention* the package — the repo **is what builds it**.

> **Do not restate this verdict any more warmly than the sentence above.** No phrasing that
> upgrades it — not "verified", not "closes", not "safe" — is licensed by what was measured.

---

## Q1 — REPO → PACKAGE: does the official repo itself publish/reference `graphifyy`?

**YES. Decisively, and from the repo side, which is independent of the package's
self-attestation.**

First, the repo moved, and GitHub itself proves the move is genuine rather than a
lookalike account:

```
GET https://api.github.com/repos/safishamsi/graphify
  -> HTTP 301 -> https://api.github.com/repositories/1200597263
GET https://api.github.com/repositories/1200597263
  -> full_name = "Graphify-Labs/graphify"   owner = Graphify-Labs (Organization)
```

GitHub only issues that 301 for a **renamed or transferred repository object**. The repo
id `1200597263` is the *same object* under both names — so `safishamsi/graphify` (the URL
the package points at) and `Graphify-Labs/graphify` are literally the same repository,
not two similarly-named ones. Repo facts: 82,303 stars, MIT, not a fork, not archived,
created 2026-04-03, last pushed 2026-07-11, **default branch `v8`**, homepage
`https://www.graphify.com`.

**The build input** — `GET /repos/Graphify-Labs/graphify/contents/pyproject.toml?ref=v8`:

```toml
[project]
name = "graphifyy"
version = "0.9.13"
```

The official repo's packaging config **names the package `graphifyy`**. Anything built
from this repo *is* a `graphifyy` distribution. This is the tightest possible repo→package
link short of a cryptographic attestation.

**The repo's own install instructions** — `README.md` on branch `v8` (the repo's file, not
the package's):

- line 18: `<a href="https://pypi.org/project/graphifyy/"><img src="https://img.shields.io/pypi/v/graphifyy" .../></a>`
- line 41: `uv tool install graphifyy      # install the CLI (or: pipx install graphifyy)`
- line 159/162/163: `uv tool install graphifyy` / `pipx install graphifyy` / `pip install graphifyy`
- extras, line 241+: `uv tool install "graphifyy[pdf]"`, `"graphifyy[mcp]"`, `"graphifyy[neo4j]"` …
- line 193: *"Name the package, not the command: `uvx --from graphifyy graphify install`. Plain `uvx graphify …` fails … because `uv tool run` reads the first word as a package, and the package is `graphifyy` — the `graphify` command lives inside it."*

So the **repo** — the 82k-star artifact the user actually trusts — tells its users to install
`graphifyy` and badges its PyPI page. This is the direction a1 was missing.

**Caveat, stated rather than hidden:** there is **no PyPI-publishing workflow** in the repo.
`.github/workflows/` contains only `ci.yml` and `release-graph.yml`; neither uploads to PyPI
(grep for `pypi|publish|twine|id-token` across `ci.yml` returns nothing relevant, and
`release-graph.yml` only builds a graph asset and attaches it to the GitHub release). Releases
are therefore **uploaded manually**. This is the reason no attestation exists (§Q2) — the two
absences are *consistent with each other*, which is itself corroborating rather than alarming:
a manual upload **cannot** produce a Trusted-Publisher attestation.

## Q2 — PACKAGE → REPO: does PyPI point back, and is there an attestation?

**Metadata link: YES. Cryptographic attestation: NO — and I looked for it by name.**

`GET https://pypi.org/pypi/graphifyy/json` → `info.project_urls`:

```json
{"Homepage":   "https://github.com/safishamsi/graphify",
 "Issues":     "https://github.com/safishamsi/graphify/issues",
 "Repository": "https://github.com/safishamsi/graphify"}
```

Latest release `0.9.12`; `requires_python >=3.10`; not yanked; **180 releases**, 356 files;
`info.author`, `info.maintainer` are `null`; the embedded license text reads
`MIT License / Copyright (c) 2026 Safi Shamsi`.

**This direction is WEAK ON ITS OWN and must not be oversold.** `project_urls` is free text
in the uploader's own metadata — an impostor can point it anywhere, including at the real
repo. It corroborates; it proves nothing by itself. Its value is only in combination with
Q1 and Q3.

**The Trusted-Publisher / PEP 740 attestation — the strongest single artifact available — is
ABSENT.** Checked three independent ways:

```
pypi/graphifyy/json  -> urls[*].provenance = None   (both wheel and sdist)
PEP 691 simple index -> files[*].provenance = None  (both files for 0.9.12)
GET https://pypi.org/integrity/graphifyy/0.9.12/graphifyy-0.9.12-py3-none-any.whl/provenance
  -> HTTP 404 {"message":"No provenance available for graphifyy-0.9.12-py3-none-any.whl"}
```

There is **no cryptographic chain** tying the release to the repo's workflow, because there is
no publishing workflow to tie it to (§Q1). The chain that closes here is a **metadata +
authorship + timeline** chain, not a signature chain. That distinction is real and is carried
into the recommendation below rather than smoothed over.

Artifact digests for `0.9.12` (so the user can pin and verify):

| file | sha256 |
|---|---|
| `graphifyy-0.9.12-py3-none-any.whl` | `94f9d0d7ef68455a2055c7623fb9574c7a781afb1473d26c7936d1abfc14d62c` |
| `graphifyy-0.9.12.tar.gz` | `ed25f955a29e4a792395b087eceb55ffbcb53e75e68c1d2b045208e5a1a31c6a` |

## Q3 — IDENTITY: does the PyPI maintainer correspond to the repo owner?

## ⚠️ **NO — AND THAT IS A MEASURED NEGATIVE RESULT, NOT A GAP. CORRECTED s30, 2026-07-12.**

**The PyPI maintainer handle IS `captainturbo`. The repo owner is `safishamsi`. They do NOT
match.**

**This section originally recorded the maintainer handle as unreadable — a bot challenge, an
absence, a hole in the evidence. That framing was WRONG, and the difference is not cosmetic.**
An absence is neutral: it invites the reader to assume the answer would have been reassuring.
A **NOT-MATCHED** is a *finding*, and it points the other way. `captainturbo` is a real,
readable handle that **does not correspond to the repo owner**, and the record must say so in
those words. **An unread field and a field that was read and disagrees are not the same
evidentiary object, and the first must never be shipped in place of the second.**

**What this does and does not mean.** It is **not** proof of an impostor: a maintainer
account name legitimately need not equal a GitHub handle (people use different usernames,
handles get squatted or renamed, an org may upload under a shared or personal account). But
it is **the one identity check that could have closed the person↔account link, and it came
back NEGATIVE.** The identity case therefore rests **entirely** on the indirect evidence
below — which is genuinely strong, and is genuinely not the same thing.

What *is* established, from the GitHub side (which the PyPI uploader does not control):

- **GitHub releases are authored by `safishamsi`** — the exact handle the package's
  `project_urls` point to:

  | GitHub release | published | PyPI `graphifyy` upload | Δ |
  |---|---|---|---|
  | `v0.9.12` by **safishamsi** | 2026-07-10T10:42:19Z | 2026-07-10T10:40:52Z | PyPI **87 s earlier** |
  | `v0.9.11` by **safishamsi** | 2026-07-09T00:31:26Z | 2026-07-09T00:28:08Z | PyPI **~3 min earlier** |

  **This timeline lock is the load-bearing identity evidence.** Each PyPI upload lands one to
  three minutes *before* the corresponding GitHub release is cut, repeatedly — the exact
  signature of one human running `twine upload` and then tagging the release. An outsider
  controlling the PyPI name would have to publish the correct version number minutes ahead of a
  release they do not control, every time. The ordering and the tightness are very hard to fake
  and easy to check.

- **Person↔org↔domain agree:** GitHub user `safishamsi` (id 216348667, name "Safi", **company
  "Graphify Labs"**, blog `graphify.com`); org `Graphify-Labs` (name "Graphify Labs", blog
  `https://www.graphify.com`, email `founders@graphifylabs.ai`). The package's own license text
  names `Safi Shamsi` and its long description links `graphifylabs.ai` — consistent, though
  package-side and therefore only corroborating.

- Org public membership is empty (`/orgs/Graphify-Labs/members` → `[]`, i.e. members are
  private), so membership could not be confirmed that way; the repo-transfer 301 (§Q1) and the
  release authorship above carry this instead. Recent `v8` commits come from `safishamsi` plus
  outside contributors (`erichkusuki`, `CJNA`, `balloon72`, `krishnateja7`, `EmilNyg`) — a
  normal OSS pattern.

## Q4 — THE NEIGHBOURHOOD: is there a single-y `graphify` on PyPI?

**NO. `https://pypi.org/pypi/graphify/json` → HTTP 404. No project of that name is registered.**
Also checked: `graphifylabs`, `graphify-cli`, `graphify-ai` → all **404**.

**This inverts the red flag, and it is the second key finding.** A typosquat works by mimicking an
**existing, popular** name so that a typo or a misremembered install lands on the impostor. **There
is no single-y `graphify` package to squat.** `graphifyy` is not impersonating anything — it is the
*only* `graphify*` package in the namespace, and it is the one the official repo's own build config
produces and the official README tells you to install. The doubled-y is a **name-availability
artifact**, not a lure.

It also means the dangerous direction is currently *empty*: a user who typos `pip install graphify`
(single-y) today gets a **404 — nothing installs**, rather than landing on an impostor. (Worth
re-checking if that name is ever registered by a third party.)

## The version gap — fully explained, not explained away

The "wildly divergent version number" was an artifact of **reading stale branches**. The repo's
default branch is **`v8`** (`pyproject.toml` version `0.9.13`), not `v1` (0.1.15) or `main` (0.1.14).
And the package's release history *passes straight through the very versions those stale branches
declare*:

```
graphifyy 0.1.14 uploaded 2026-04-05T22:18:54Z
graphifyy 0.1.15 uploaded 2026-04-05T22:40:41Z   <- the stale branches' versions, as real releases
graphifyy 0.9.11 uploaded 2026-07-09T00:28:08Z
graphifyy 0.9.12 uploaded 2026-07-10T10:40:52Z   <- current; repo default branch is at 0.9.13 (next bump)
```

180 releases from `0.1.1` to `0.9.12` form one continuous lineage that tracks the repo's own history
(April 2026 → July 2026), and the repo currently sits exactly **one patch bump ahead** of the newest
published release — the normal state of a repo between releases. There is no divergence to explain:
`0.1.14/0.1.15` vs `0.9.12` was **stale-branch vs current-branch**, not **impostor vs real**.

---

## Residual risk — what this verdict does NOT certify

**Three things, all named rather than buried**, because the user is going to be shown *why* we
trust this, not just told that we do. **Residuals 1 and 2 are the two that bound the verdict;
both must be carried wherever the verdict is quoted — neither is retired.**

1. **RESIDUAL — no cryptographic attestation exists** (no PEP 740 / Trusted-Publisher
   attestation; confirmed by name against the integrity endpoint, §Q2). The tie is metadata +
   authorship + timeline, not a signature. Consequence: if the maintainer's PyPI credentials
   were ever compromised, a malicious release could be pushed and **no attestation check would
   catch it** — because there is no attestation to check. Mitigation offered to the user:
   install by the **exact** name `graphifyy`, **pin the version**, and verify against the
   sha256 digests recorded in §Q2.

2. **RESIDUAL — the PyPI maintainer does NOT match the repo owner.** `captainturbo` (PyPI)
   vs `safishamsi` (repo). **This is a NOT-MATCHED finding, not an unread field** (§Q3). It is
   not evidence of an impostor — but it is the one direct identity check available, and it did
   not come back clean. The person↔account link therefore rests on the release-authorship and
   timeline-lock evidence, which is indirect.

3. **Provenance is not safety.** What the evidence supports is *"`graphifyy` is the distribution
   channel of the `Graphify-Labs/graphify` repo"* — at the strength stated in the VERDICT, and no
   higher. It does **not** certify that the code is benign. It converts the question "do I trust
   this package?" into "do I trust this repo?" — which is the right question, and one the user can
   now answer with the repo in front of him (82k stars, MIT, active, public contributors). Nothing
   was installed or executed, so **no claim whatsoever is made here about the package's runtime
   behaviour.** Any such claim would need its own evidence.

## What the user should be shown

The install of `graphifyy` can be recommended **at the strength stated in the VERDICT —
substantially stronger than self-attestation, short of proof** — with these artifacts attached
as the *reason*, and **both residuals shown alongside them, not after them**:

- The official repo's own `pyproject.toml` (default branch `v8`) declares `name = "graphifyy"` — the
  repo builds this package. → `https://github.com/Graphify-Labs/graphify/blob/v8/pyproject.toml`
- The official repo's own README says `uv tool install graphifyy`. → `https://github.com/Graphify-Labs/graphify`
- GitHub's 301 proves `safishamsi/graphify` and `Graphify-Labs/graphify` are the **same repo object**
  (id `1200597263`) — the URL the package points at is the repo it claims.
- GitHub releases `v0.9.11`/`v0.9.12` are authored by **safishamsi**, and each PyPI upload lands
  1–3 minutes *before* its GitHub release.
- There is **no single-y `graphify`** on PyPI (404) — `graphifyy` squats nothing.
- **BOTH RESIDUALS, DISCLOSED AS FINDINGS:** (1) there is **no PyPI Trusted-Publisher / PEP 740
  attestation** (confirmed by name against the integrity endpoint); (2) the **PyPI maintainer
  handle is `captainturbo`, which does NOT match the repo owner `safishamsi`** — a **NOT-MATCHED
  result**, not a hole in the evidence. Neither residual overturns the verdict; together they are
  exactly why the verdict stops where it does.
