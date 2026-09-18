# Current subscription-source research — 2026-09-18 14:43–14:47 UTC

Requested by owner via architect `m-f4bd578067`, after owner questioned manual-session ergonomics. This is a **new public-web check**, not a claim that this engineer had previously browsed: earlier implementation used S0's documented web research plus legitimate installed-source probes. Retrieved public documentation/repository files using HTTPS GET only. No undocumented endpoint calls, credentials/keychain/cookie reads, new login, model prompts or wiring changes.

## Bottom line
**There is a Claude subscription-usage HTTP endpoint used by established tools. Saying “there is no API” would be wrong.** The distinction is *a documented, supported third-party subscription API versus a native-app OAuth endpoint implemented by community clients*. We found evidence for the latter, not a public general-purpose Pro/Max quota API contract or permission to intermediate subscription credentials. API billing/admin usage is a different product and cannot substitute.

Manual `--settings` on every session was a reversible validation method, **not a necessary final UX**. One-time authorized integration can remove that manual step. Truly fresh readings while no normal Claude session is running require another collector strategy; rerunning a statusline command or board refresh cannot conjure a new provider observation.

## Primary sources actually retrieved
1. **Claude Code statusline**: https://code.claude.com/docs/en/statusline.md (human page https://code.claude.com/docs/en/statusline#rate-limit-usage).
   - Documented `rate_limits.five_hour/seven_day` `used_percentage` and `resets_at`; Pro/Max after first API response; windows independently absent and dropped after reset.
   - User/project settings can permanently configure `statusLine.command`; settings reload automatically. Windows PowerShell/Git Bash configuration is documented.
   - Current docs also expose optional `statusLine.refreshInterval` (minimum1s) in addition to event-driven updates. **This reruns the local command; docs do not say it refreshes provider quota.** Its presence does not justify using receipt time as original observation time. Statusline runs locally without consuming API tokens.
2. **Claude Code costs and /usage**: https://code.claude.com/docs/en/costs.md.
   - `/usage` shows plan usage bars on subscription accounts, distinct from API session cost/token totals. It can report last-known bars cached within60min after a rate-limited request, explicitly labelled; `r` retries.
   - This gives a native CLI user surface that community PTY collectors automate. It is not documented here as a stable machine-readable quota RPC/JSON endpoint; screen parsing must handle stale labels and auth/trust prompts rather than pretend every panel is fresh.
3. **Authentication / legal boundaries**: https://code.claude.com/docs/en/authentication.md and https://code.claude.com/docs/en/legal-and-compliance.md#authentication-and-credential-use.
   - Subscription OAuth is designed for ordinary Claude Code/native-app use. Legal page says third-party developers may not offer Claude.ai login in their own apps, route subscription requests on users' behalf, or collect/store/intermediate Claude.ai credentials/session tokens. It explicitly permits end-user sign-in to the unmodified CLI, subject to terms.
   - This is a support/security constraint, **not our legal opinion that every local personal monitor is prohibited**. A community endpoint/client existing does not establish vendor approval. For uncertain product use, request vendor clarification rather than assert permission.
   - `claude setup-token` is documented for long-lived automated authentication. It is not, by itself, evidence of the `user:profile` permission required by community usage clients; do not mint a token to experiment.
4. **Usage & Cost Admin API**: https://platform.claude.com/docs/en/build-with-claude/usage-cost-api.
   - Historical organization API tokens/costs, `/v1/organizations/usage_report/messages` and `/cost_report`; admin credentials/appropriate admin OAuth scope, not individual Max5h/weekly quota. Page explicitly distinguishes Claude Enterprise analytics as another API. Buying/creating an API key would not solve this requirement.
5. **Codex App Server**: https://developers.openai.com/codex/app-server/.
   - Supported `account/read`, `account/rateLimits/read`, `account/rateLimits/updated`; `rateLimitsByLimitId` vs compatible single pool, `usedPercent`, duration minutes and reset epoch explicitly documented. Separate `account/usage/read` token-activity is **not** quota. Existing S6 architecture already uses the right API; continuous opted-in collector is ergonomic once operator starts/installs it.

Documentation index checked: https://code.claude.com/docs/llms.txt. Absence of a public quota API contract in these researched sources is a bounded finding, not a proof no other API exists.

## Established implementations actually inspected
### CodexBar
- Repository/docs: https://github.com/steipete/CodexBar ; https://github.com/steipete/CodexBar/blob/9a2f5e420ab39b9189a7bf1a6bd57292590c2ee6/docs/claude.md.
- Fetcher source: https://github.com/steipete/CodexBar/blob/9a2f5e420ab39b9189a7bf1a6bd57292590c2ee6/Sources/CodexBarCore/Providers/Claude/ClaudeOAuth/ClaudeOAuthUsageFetcher.swift.
- Source really issues GET `https://api.anthropic.com/api/oauth/usage`, bearer OAuth with beta header `oauth-2025-04-20`; docs require `user:profile` and identify file/keychain credential fallbacks. It also uses `/api/oauth/profile` to match identity. **We read public code; we did not call these endpoints.**
- Alternate path imports browser session cookies and calls claude.ai organization usage endpoints; another launches unmodified CLI in a PTY, sends `/usage`, optionally `/status`, parses rendered quota. The PTY implementation includes automated first-run prompt handling that we should **not copy** into a safe board collector; auth/trust/consent must stop and surface an operator action.
- Handles401/403/429, cooldowns, profile/keychain rotation, stale last-good values and scoped model windows. This is evidence of engineering complexity and richer possible windows (including Fable), not a source guarantee for our account.
- Current README targets macOS/Linux; not evidence of a drop-in supported native Windows deployment for this host.

### Claude-Code-Usage-Monitor
- Repository at retrieved revision: https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/tree/c59a83bf943f329f0e61f1a29c760353ee1860a5.
- README describes official statusline `rate_limits` as the preferred trusted data, with labelled local estimates when unavailable; `--api` is explicitly opt-in experimental.
- Actual API reader: https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor/blob/c59a83bf943f329f0e61f1a29c760353ee1860a5/src/claude_monitor/output/api_usage.py.
- It uses the same OAuth endpoint/beta header, reads OAuth credentials from env/file and caches/backoffs. Module documentation calls the source experimental; it does not outrank fresh official statusline readings. Thus using an official statusline receipt is not an invented workaround unique to this board.
- Its token-derived estimates/predictions are unsuitable replacements for this story's real subscription percentages; do not import that fallback behavior.

### ccusage (cross-check only)
https://github.com/ccusage/ccusage/blob/main/apps/ccusage/README.md (retrieved via redirected ryoppippi/ccusage raw URL). Purpose is local token/cost analysis, not authoritative Pro/Max subscription quota. Root README is a symlink pointer; followed to actual app README. Do not mistake familiar usage dashboards for the required source.

## Recommendation / decision options
1. **Recommended supported-data baseline:** one-time owner-approved account-specific statusline dispatcher preserving existing statusline stdout/exit behavior, plus the current masked receipt adapter; no repeated launch command. Configure durable scoped mapping and owned Codex collector through the operator's normal startup/maintenance process. No paid keepalive prompts. Existing board refresh automatically reflects new receipts. Honest limitation: Claude values update as the official CLI supplies them, not a guarantee of live account-wide refresh with no active session. `refreshInterval` may help UI/capture timing but must not be sold as provider polling.
2. **If “automatic even while Claude is idle/closed” is mandatory:** first propose a bounded **Windows ConPTY/native `/usage` proof** using an unmodified authorized CLI, no model prompt, no auto-accepting login/trust or paid actions, explicit account and last-known/freshness detection, strict timeout/owned-child cleanup/backoff. Community precedent exists, but our Windows parser/lifecycle/support proof does not; this is an engineering follow-on decision, not delivered functionality. Prefer this evaluation before extracting OAuth credentials.
3. **Direct OAuth polling:** technically credible and more direct (community clients prove mechanism), but currently outside approved design's no-OAuth-extraction/no-private-provider-scraping boundary. Needs explicit architectural/security/support/terms decision and appropriate consent/vendor confirmation—not merely a routine refresh implementation. Do not silently implement or use cookies as a workaround. An owner accepting convenience does not waive credential stewardship/vendor terms.

No permanent change made. The architecture can swap in a better approved collector without changing the widget/account ACL/duration contract. We should present these tradeoffs plainly, not force a manual ritual or promise an unverified API.
