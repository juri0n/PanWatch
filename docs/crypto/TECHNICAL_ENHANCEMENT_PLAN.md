# Technical evidence and input clarity

Base: 902b4f1 / PC read-only workflow. Scope: visible input labels and localized field validation; shared stock-standard daily/hourly indicator evidence. No screener, new indicator dependency, order capability or notification-setting changes.

## Implementation and boundaries

- `kline_collector.py`: expose the existing calculation and summary as pure static entry points. Keep instance methods and defaults intact, including overrides, formulas, rounding and stock fields. No new library. Crypto uses this same code path; parity fixtures compare identical OHLCV inputs.
- `crypto/technical.py`: schema/version/algorithm fingerprint, exchange+pair identity, `1d` and `1h`, 120 completed UTC-aligned consecutive bars, explicit open/close timestamps and base-volume units. Reject stale/gapped/duplicate/future/invalid candles. Insufficient data is unavailable, never zero. Original day-named counters become bar-named counters in Crypto. Stock defaults remain unchanged. No cross-asset score equivalence is claimed.
- Cache per instrument/timeframe until the next candle boundary; short negative cache on failure. Fetch historical evidence before the fresh quote. Persist it with quote valuation; failure of OHLCV does not erase healthy quotes. Revalidate persisted evidence on read/research, never grant a fresh timestamp to old cached bars.
- Existing isolated CCXT reader obtains a bounded OHLCV batch using one client; only whitelisted public calls. Stock dependencies and private credentials stay outside the child. Freshness is bounded independently for quotes and candles.
- `research.py`/workflow: supply verified daily/hourly evidence to the shared research engine, record missing domains accurately, include concise deterministic technical facts in reports. Existing price-threshold alerts retain their meaning; the versioned snapshot is the future indicator-alert/screener input.
- Crypto UI: visible pair/quantity labels, base-asset quantity hint, field errors and accessible invalid state; update linked threshold pair when a holding pair is edited. Do not overwrite drafts during background polling. Show daily/hourly status, source close time, bar count and indicators; no stock-only calendar assumptions or auto-generated holdings.

## Acceptance

1. `BTC` / quantity `USDT` produces actionable localized field errors before a write. Valid high-precision decimal strings survive save and cancel; editing a pair updates linked threshold drafts. Server enforces the same domain validation.
2. Same OHLCV rows produce identical stock/Crypto MA, MACD, RSI, KDJ, BOLL and ATR values. ATR remains mean TR(14); MACD histogram remains 2*(DIF-DEA). No library substitution or stock-default change.
3. Incomplete last candles are excluded; duplicates, holes, shifted UTC grids, stale tails, missing history and malformed numbers cannot become valid indicators. Hourly fields never masquerade as calendar-day counters.
4. Cache reuse does not refetch closed bars every minute; a new period or expired/failing evidence is handled explicitly. Quotes still work when history is unavailable. AI receives only current valid indicator evidence with captured timestamps and declared gaps.
5. Existing crypto/stock/indicator/startup/frontend tests and required remote compatibility pass. Real CCXT bars and isolated process behavior are checked separately from fixtures. Existing live holdings/reports/configuration and stock package versions must survive a backed-up PC rollout.

Not claimed: crypto universe screening, calibrated stock-vs-crypto scores, indicator-based alert rules, automatic AI schedule, news/onchain inputs, live execution or Unraid hardware deployment.
