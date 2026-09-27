# Context-pack exam: boot `context()` at 8, 16 and 40 KB

Task t-d6fe520371 (epic-7f3d64e6de), owner approval m-e09a1fe3dd, architect steer m-081adcf0a9.

## What is here
| Path | What |
|---|---|
| `exam.json` | 14 seats from this epic (architect, 2 qa, 1 sme, 10 engineers), 3 questions each |
| `packs/8k/`, `packs/16k/`, `packs/40k/` | each seat's boot `context()` pack, rendered by the real `edp8.bundles._context` bounding code with `EDP8_CONTEXT_BUDGET_B` = 8000 / 16000 / 40000 |
| `key.json` | the answer key, written from the board record (criteria rows, the message table, ticket descriptions) |
| `fable-score.json` | Fable's score per seat, size and question, plus bytes and tokens per pack |

## How the packs were made
- A private copy of the board DB (SQLite backup API, taken 2026-09-27 ~08:20Z) was opened in-process with `edp8.board.Board`. No server ran, and the fleet was never touched.
- `Board.context(participant)` produced each seat's full snapshot. `bundles._context` then bounded it at each budget, exactly as the MCP tool does.
- Packs are rendered from the record as it stands now, not as it stood at each seat's original boot. Each question asks what that seat needs to act on now.
- PII is redacted with the rules of `.github/scripts/pii_gate.py` (`<user>`, `<name>`, `<email>`, `<drive>/<projects>/`).

## Rules for a taker (Opus 5.5, Sol)
1. Do NOT open `key.json` or `fable-score.json` until you have written every answer.
2. For each seat and each size, read ONLY `packs/<size>/<seat>.json`. Answer that seat's Q1 to Q3 from that pack alone.
3. Give each answer one mark:
   - `ANSWERED`: the pack contains the answer. Write it.
   - `FETCH`: the pack names where the answer is, but doesn't hold it. Write the exact single tool call that would return it.
   - `MISSING`: the pack gives no pointer to it.
4. Write `answers-<model>.json` in this folder: `[{seat, size, qid, mark, answer}]`.
5. Then score yourself against `key.json`:
   - Q1 is correct when your id set equals the key's.
   - Q2 is correct when the message id matches and your summary matches the key text's instruction.
   - Q3 is correct when the owner ids match and your gist matches.
   - A `FETCH` is correct when the call you named returns the key's content.
6. Post a table on t-d6fe520371 with correct / FETCH-correct / wrong / missing per size, and your tokens read per size.

## Fable's own score (automatic, from the pack text)
- `in_pack` means every key id and a 50 to 60 character snippet of the key text are in the pack.
- `one_fetch` means the key id, or the ticket that holds it, is in the pack, but the content isn't.
- `missing` means neither is in the pack.
- Tokens are bytes / 4 of the ASCII-escaped JSON the MCP client receives.
