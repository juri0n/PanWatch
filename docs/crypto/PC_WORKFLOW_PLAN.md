# PC workflow: source evidence and acceptance

Baseline: fork main b043d8e, upstream c4b7b23. Existing PC installation:
`D:\Codex\Tradingview\PanWatch`, loopback port 8000, Python 3.13,
`start-local.ps1` and Windows login startup (confirmed from deployment chat).
No secrets are copied into source or test fixtures.

## Verified extension points

- `src/bootstrap/application.py`: protected router registration; existing JWT/PAT authentication.
- `server.py:build_context`: current model fallback routing, report language, notifier and quiet-hours policy. Inject this callable; never import server from crypto.
- `src/modules/research/orchestration/gateway.py`: existing bounded research model gateway and captured-evidence tools.
- `.../reporting.py`: existing Markdown report renderer. Stock research repository commits stock recommendations, so crypto must not call it.
- `src/platform/runtime/paths.py:get_data_dir`: existing persistent data root.
- `frontend/src/router/page-loaders.ts`, `App.tsx`: lazy routes and navigation.
- Existing price-alert engine coerces prices to float and stock market enums/calendars. Do not pass crypto through it. The small decimal threshold comparison belongs in the adapter; delivery, retry and quiet-hours reuse the existing notifier.

## File-level implementation

- `crypto/workflow.py`: SQLite persistence in a separate crypto database, validated manual positions/rules, quote freshness, one collection at a time, bounded research, report/delivery history. No stock tables or exchange credentials.
- `crypto/api.py`: authenticated configuration, snapshot refresh, asynchronous report jobs and history. Disabled by default until holdings are saved. Background polling runs 24/7 without stock calendars. AI and notifications require explicit user action/opt-in.
- Assembly root: one protected router registration. Server lifespan: inject current host context builder and start/stop crypto polling.
- `frontend/src/pages/Crypto.tsx`: manual decimal holdings, exchange/refresh interval, timestamped valuations grouped by quote currency, optional price thresholds, report creation/history; reuse shared UI and API client. Add bilingual namespace and route entries only.
- Tests: offline fake exchange/model/notifier, real SQLite restart persistence, stale/error/config-change races, unauthenticated API rejection, report isolation and notification quiet-hours. Existing stock compatibility checks still required.

No new dependencies beyond audited CCXT/host APScheduler. SQLite, FastAPI, existing research package and notifier are reused. Rotki/Freqtrade/indicator packages remain excluded: this step needs neither accounting imports, execution nor new indicators.

## Acceptance and deployment gate

1. Exact decimal strings survive edits/restarts; USD and USDT totals never combine.
2. Refresh failures/stale quotes are visible and cannot trigger analysis or price alerts.
3. AI uses only captured crypto evidence and records unavailable domains; no stock recommendations/orders are written. Jobs have bounded time and concurrency; interrupted jobs are marked on restart.
4. Alerts have persisted cooldown and delivery state. Report delivery is explicit and uses existing channels/quiet-hours; no credentials accepted by crypto endpoints.
5. Existing auth, stock checks, frontend checks/build and crypto tests pass. Real public quote retrieval is separate from offline tests.
6. Local 390px/desktop light/dark QA and real configured AI/Telegram are recorded as verified only when actually exercised. No fabricated verification.
7. Before touching the live PC installation: stop, back up data and deployment files, stage changes, restart and check health. Preserve startup and existing settings. Rollback restores the saved files/data. Unraid hardware deployment is skipped.

Unverified at planning time: local AI/Telegram configuration, real delivery, UI rendering, current live installation commit/protection; upstream-change PR creation path (no upstream change available).
