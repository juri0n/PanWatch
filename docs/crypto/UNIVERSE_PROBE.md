# Public universe probe (stage A/B)

Scope agreed after the candidate-pool/rule-reuse analysis at main `20c3de6`:
implement an isolated public capability probe and bounded spot candidate pool.
No stock strategy extraction, UI, host scheduling, AI, alerts or trading in this stage.

## Boundaries

- Existing stock paths and manual-holding quote/bars behavior are unchanged.
- New SpotReader methods project public markets, bulk ticker statistics and top-of-book.
  No raw SDK/client, arbitrary method/URL/params, credentials or private operations.
- One isolated CCXT process and instance per bounded probe. No overlapping automatic
  scans are launched. Before production scheduling, add shared exchange request
  coordination with holdings/alerts; per-instance rate limiting alone is insufficient.
- Keep the existing pinned CCXT environment separate from stock dependencies.
  This change adds no package or dependency version.
- Native turnover fields are audited against CCXT 4.5.91: Binance `quoteVolume`/
  `amount`, OKX spot `volCcy24h`. Kraken's unified quoteVolume is derived from
  volume*VWAP and is deliberately unavailable for this strict pool.
- Current, explicit market flags, instrument identity and operator-reviewed plain
  base assets are required. Unknown classifications are excluded, never guessed
  from a symbol substring. Known stable assets cannot be reviewed as plain bases.
  The reviewed list is a classification boundary, not a fallback seed universe.
  Markets must actually exist, be active spot markets and pass all data gates.
- USD and USDT pools are separate. Defaults in the example are engineering trial
  thresholds, not calibrated strategy or investment thresholds.
- Quote turnover must be native, finite, positive, in quote units and <=120s old.
  Public orderbook source time is mandatory and <=15s old; receiving time cannot
  substitute for missing exchange time. Crossed/invalid/wide books are excluded.
- Daily history requires 120 consecutive completed UTC candles with traded volume.
  Hourly history is independently recorded, with missing/stale confirmation explicit.
  No indicators or scores are invented by this data-only probe.
- Histories are collected before fresh statistics/books. Evidence is checked again
  at publication, at the host boundary and on SQLite readback. A completed run is
  captured historical evidence, never a promise that its books stay current.

## Explicit CLI

Run from this checked-out source using a host interpreter and existing isolated
CCXT interpreter; configure an administrator proxy using
`PANWATCH_CRYPTO_HTTPS_PROXY` if required. The worker does not receive host AI/auth
variables or PYTHONPATH. It never loads the production settings or a .env file.

```sh
python -m src.modules.crypto.universe_probe \
  --config deploy/crypto/example-universe.json \
  --python /path/to/isolated-crypto/python \
  --store /dedicated/probe-directory/universe.sqlite3 \
  --output /dedicated/probe-directory/new-run.json
```

The example classifies only BTC/ETH; expanding the reviewed list requires explicit
asset review. `limit=10` is an upper bound, not a guarantee of ten eligible rows.
The CLI refuses production DB names, foreign database tables and existing output
files. Every run has a unique ID; duplicate IDs never overwrite prior evidence.
The dedicated SQLite file retains at most 20 runs. No production router/lifecycle
registration exists: nothing scans merely because PanWatch starts.

The output records directory/market/statistics/turnover counts, budget omissions,
actual history/book attempts, per-item exclusions and sampled capabilities.
Capability `null` means not exercised, not confirmed unsupported. `partial` and
`empty` must be shown with their coverage/reasons, never as "no market opportunities".
Source-time failures do not silently relax policy or change exchanges.

Tests: `python -m pytest crypto_tests -q`. Live exchange results must be reported
separately from fixtures, with configuration, times and source identity. Per-exchange
capabilities are sampled, not guarantees for all markets or future versions.
This stage is disabled by default; rollback consists of no longer invoking the
standalone CLI. The independent probe DB is never a production migration.
