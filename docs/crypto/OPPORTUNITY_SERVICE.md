# Authenticated manual opportunity service

The existing authenticated `/api/crypto` router now exposes GET `/opportunities`,
POST `/opportunities/scans` (202) and POST `/opportunities/cancel` (202).
The service is created lazily, so existing holdings startup does not create new
tables/files or automatically scan. All new data stays in crypto_opportunities.sqlite3.

Explicit scans validate UniverseConfig, limit this initial application trial to
ten pairs, reject duplicate jobs and enforce a 60-second start cooldown. No SDK
paths, proxy, credentials, arbitrary methods, AI or notification choices are
accepted from clients. The existing administrator reader factory owns the isolated
interpreter/proxy. Each HTTP call uses the shared host coordinator at scan priority.

Jobs persist running/complete/failed/cancelled/interrupted states. Cancellation
stops the owned public worker; shutdown waits for cleanup. Restart never resumes a
running job. Failure/cancellation keeps the previous captured result, labelled by
its source configuration/time instead of pretending it is a new successful scan.

GET filters completed results by timeframe, shared strategy tag, score, rule state,
holding, freshness and risk. Held means a positive manual amount for the exact
exchange+pair; amounts are not returned to this page. Risk is unknown, not stock
low/medium/high. Historical rows remain inspectable, while current_count and row
fresh explicitly require valid source/profile/calculator versions. Settings changes
also invalidate the current label of earlier results.

There is no scan scheduler and no candidate automatically enters holdings. The
stock opportunities engine, tables, settings and route remain unchanged. The
service assumes one application process; multi-worker coordination is not claimed.
Data capability/asset-review restrictions from the probe still apply. UI is a
separate reviewable change. Production merge/deployment requires acceptance.
