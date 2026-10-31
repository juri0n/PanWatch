# Shared stock rules and Crypto technical profile

Scope: extract the original pure market-scan decision and base-score functions,
keep stock defaults identical, and rank the isolated public candidate pool with
a separate Crypto profile. Stacked on the universe probe (PR #6).

- `strategy/signal_rules.py` owns the two rule implementations, their labels and
  base action scores. Existing private entry-candidate functions retain their
  signatures and delegate; stock discovery, final ranking, DB, news, plans and
  learned weights are unchanged. No strategy-catalog migration is needed here.
- 49 frozen JSONL cases were generated from the pre-extraction source at
  `20c3de6132956bcb32cf5ee504def9da475942f2`, before changing its implementations.
  They cover boundary/missing values, actions, labels/reason order and scores.
  Tests check both pure functions and actual stock wrappers, not a copied algorithm.
- `CryptoProfile` has independent immutable parameters and a version including
  the shared rule source fingerprint. Stock absolute-turnover bonuses are forbidden.
  Initial comparable thresholds are an uncalibrated baseline, not learned weights.
- Shared stock-calculator snapshots remain authoritative. Raw completed bars are
  captured only with an explicit bounded worker option; existing probe behavior
  remains the default. No additional OHLCV calls or second indicator library.
- The host verifies raw-bar hashes and recomputes indicators before scoring.
  Snapshot IDs cover instrument/timeframe/calculator/parameters/bar-close/input
  hash; scores also reference the rule and Crypto-profile versions.
- Momentum uses close-to-close return of one completed bar of its own timeframe.
  It never substitutes rolling 24h change for hourly change. Daily is the default
  primary period; hourly results stay separate, never averaged into confirmation.
  A missing primary period blocks ranking; missing secondary evidence is explicit.
- Crypto labels explain the actual heuristic: volume condition is not a confirmed
  breakout; MACD golden is a state, not necessarily a new cross; proximity to
  support is not a confirmed pullback. Rules remain unchanged for stocks.
- Output is a technical reference score, not the stock final portfolio/news score,
  win probability or execution advice. Risk is unknown and calibration false.
  No stock risk labels, history win rates, turnover bonuses or learned weights.
- Current views reject expired book/quote/bar evidence, changed profile versions
  and changed calculator versions; persistence never renews source times.

## Opt-in CLI

From this checked-out source, using the existing isolated CCXT interpreter:

```sh
python -m src.modules.crypto.technical_scan --config deploy/crypto/example-universe.json \
  --python /isolated/crypto/python --store /dedicated/probe.sqlite3 \
  --output /new/technical-result.json --min-score 0
```

`--profile` may specify JSON with exactly `primary_timeframe` and `rules`; the
rules object must contain the fields returned by `dataclasses.asdict(CryptoProfile())`.
The default profile is daily and disables stock turnover bonuses. Source probe
data is retained in a dedicated SQLite file, while versioned scores/snapshots are
written to a new JSON file. No production tables, models, alerts or routing change.

This stage has no API/UI/lifecycle registration and is not automatically deployed.
Stock opportunity UI is unchanged. Next: production request coordination and a
separate Crypto opportunities interface, after review and acceptance. Multi-day
availability, broad asset coverage, 30/100-pair capacity, strategy profitability,
weight calibration and future upstream changes are not claimed by this stage.
