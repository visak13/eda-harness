# Harnesses

A **harness** is the agent CLI a seat runs in. A seat is a role card plus one set of board tools, so
the model in the chair is your choice. Heronry supports three harnesses:

| Harness | CLI | Signs in with |
|---|---|---|
| **Claude Code** | `claude` | Your Claude account |
| **OpenAI Codex CLI** | `codex` | Your ChatGPT account |
| **Pi** | `pi` | Any model provider or API key, including local models |

## Pick at least one of claude and codex

Claude Code and Codex are both optional, but at least one must be selected. The setup wizard and
`heronry init --harness claude,codex` refuse to finish with neither. Seats then run on the harnesses
you picked, and the models catalog only offers models for those harnesses.

You pick them in three places:

- the **Harnesses** step of the [setup wizard](first-run.md);
- `heronry init --harness claude`, `--harness codex` or `--harness claude,codex`;
- later, under **Admin → Seats & models → Seat harnesses**, then **Save harnesses**.

Each harness must be installed and signed in on the computer that runs the board. The wizard's
**Your tools** step shows the sign-in command for any harness that is not signed in yet. To check
at any time, run `heronry doctor`, or open **Admin → Integrations → Seat harnesses** and press **Test**.

!!! warning "Adversary risk notice: Fable reviews may be declined or softened"
    The **adversary** seat runs one bounded hostile review of an epic. With codex selected, it runs
    on codex. **When codex is not selected, the adversary runs on Fable (`claude-fable-5-1`).**

    Fable's safety safeguards are strict, so an adversarial or security review may be declined or
    softened. **Review its findings before you trust a clean result.** A clean adversary report on
    Fable is not proof that nothing was found.

    The setup wizard and **Admin → Seats & models** show this notice whenever codex is not selected.
    You acknowledge it once ("I understand; run the adversary on Fable"), and the board records who
    acknowledged it and when. To avoid the fallback, select codex, or run the adversary role on a Pi
    seat (below).

## Pi: any model provider

Pi is a third harness for models neither claude nor codex runs: another vendor's API, a subscription
Pi can sign in to, or a local model. A Pi seat is a normal seat: it reads its role card, calls the
board through a Pi extension that ships with Heronry, and is woken like any other seat.

### 1. Install Pi

```sh
npm install -g @earendil-works/pi-coding-agent
```

Or use **Install** on the `pi` row of the wizard's **Your tools** step, or
`heronry prereqs install --only pi`. Node is needed for Pi. `EDP_PI_BIN` points Heronry at a
different Pi executable.

### 2. Give Pi a provider and key

Pick one way per provider:

- **An environment variable** in the pool's environment, for example `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`,
  `DEEPSEEK_API_KEY` or `XAI_API_KEY`. Pi's own provider docs list every variable.
- **Sign in:** run `pi` once by hand, type `/login`, and choose a subscription or paste an API key.
  Pi saves and refreshes the credential itself.
- **A local or custom endpoint** (Ollama, LM Studio, vLLM, a proxy): declare the provider and its
  models in Pi's own `models.json` with a `baseUrl`, an `api` such as `openai-completions`, and an
  `apiKey` (a dummy value for a keyless local server).

Check it by hand first: `pi --model <provider>/<model-id>` must answer a prompt.

### 3. Add the model and use it

Add the model in **Admin → Models** (below) with harness **pi** and the model id as
`<provider>/<model-id>`.

- **One seat:** pick the model for a role in the **New epic** dialog.
- **A whole role:** tick it for that role under **Models per role** and make it the default.
  `EDP_PI_ROLES` (for example `EDP_PI_ROLES=qa,adversary`) routes whole roles to Pi.
- **Instead of codex:** without codex installed, a Pi seat on `openai-codex/<id>` (ChatGPT sign-in)
  or `openai/<id>` (`OPENAI_API_KEY`) runs the same GPT models.

!!! tip
    A model that does not follow tool-calling instructions well makes a poor seat. Try it on a small
    task first.

## The models catalog (Admin → Models)

**Admin → Seats & models** holds the catalog every seat is picked from.

- **Models:** a table of every model for the selected harnesses: model id, harness, provider, context
  window, compact point, effort cap and the roles that use it. **Add a model**, **Edit** or **Remove**.
  Claude models are capped at medium effort or lower. A Pi model's API key comes from its secret
  setting in **Admin → Settings**.
- **Models per role:** tick the models each role may run on and pick its default. The **New epic**
  dialog offers exactly these. The board refuses a role with no model.
- **Test spawn:** runs a short stub prompt on a private seat of a model and shows its reply. No ticket
  is touched.

The full catalog format is in the [models reference](../reference/models.md).

## Keeping harnesses up to date

Heronry never updates claude, codex or pi on its own, and a seat never updates its harness mid-run.
**Admin → Integrations → Seat harnesses** shows each harness's installed and latest version, and
**Update when idle** runs the vendor's own update only while no seat of that harness is live. See
[Updates](../docs/updates.md).
