"""Versioned completed-bar evidence using the original PanWatch stock calculator."""
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import time

from .adapter import TIMEFRAMES, DataUnavailable, number, utc_ms
from .contracts import Instrument

PERIODS = ("1d", "1h")
LOOKBACK = 120
PARAMS = {"ma": [5, 10, 20, 60], "macd": {"fast": 12, "slow": 26, "signal": 9, "histogram_multiplier": 2},
          "rsi": {"periods": [6, 12, 24], "smoothing": "simple_mean"},
          "kdj": {"n": 9, "m1": 3, "m2": 3}, "boll": {"period": 20, "num_std": 2},
          "atr": {"period": 14, "smoothing": "simple_mean"}, "volume_ratio": {"period": 5, "includes_last_bar": True}}


def stamp(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


@lru_cache(maxsize=1)
def algorithm_version():
    source = Path(__file__).resolve().parents[2] / "platform/marketdata/collectors/kline_collector.py"
    return "panwatch-stock/" + hashlib.sha256(source.read_text(encoding="utf-8").replace("\r\n", "\n").encode()).hexdigest()[:16]


def normalize_bars(rows, timeframe, now_ms):
    duration = TIMEFRAMES[timeframe]
    if not isinstance(rows, list) or not rows or len(rows) > 500:
        raise DataUnavailable("invalid candle collection")
    normalized, previous = [], None
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"timestamp_ms", "open", "high", "low", "close", "volume"}:
            raise DataUnavailable("invalid candle fields")
        opened = utc_ms(row["timestamp_ms"])
        if opened % duration or opened > now_ms or (previous is not None and opened - previous != duration):
            raise DataUnavailable("candle grid, gap, duplicate or order failure")
        previous = opened
        values = {key: number(row[key], positive=key != "volume") for key in ("open", "high", "low", "close", "volume")}
        if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
            raise DataUnavailable("invalid candle price range")
        if opened + duration <= now_ms:
            normalized.append({"timestamp_ms": opened, **{k: format(v, "f") for k, v in values.items()}})
    if normalized and normalized[-1]["timestamp_ms"] != (now_ms // duration - 1) * duration:
        raise DataUnavailable("latest completed candle is missing")
    return normalized[-LOOKBACK:]


def build_snapshot(exchange, symbol, timeframe, rows, *, now_ms=None):
    Instrument(exchange, symbol)
    if timeframe not in PERIODS:
        raise ValueError("technical timeframe must be 1d or 1h")
    now_ms = utc_ms(now_ms if now_ms is not None else int(time.time() * 1000))
    bars = normalize_bars(rows, timeframe, now_ms)
    duration = TIMEFRAMES[timeframe]
    item = {"schema_version": 1, "algorithm_version": algorithm_version(), "params": PARAMS,
            "instrument_key": Instrument(exchange, symbol).key, "exchange": exchange, "symbol": symbol,
            "timeframe": timeframe, "bar_count": len(bars), "required_bars": LOOKBACK, "timezone": "UTC",
            "volume_unit": "base_asset", "bar_status": "completed_only", "computed_at": stamp(now_ms),
            "valid_until_ms": (now_ms // duration + 1) * duration,
            "source_close_ms": bars[-1]["timestamp_ms"] + duration if bars else None,
            "period_start": stamp(bars[0]["timestamp_ms"]) if bars else None,
            "bars_sha256": hashlib.sha256(json.dumps(bars, sort_keys=True).encode()).hexdigest(),
            "bars": bars, "indicators": None, "summary": None,
            "unavailable_domains": ["quote_turnover", "orderbook_depth", "news", "onchain", "company_fundamentals"]}
    if len(bars) < LOOKBACK:
        return {**item, "status": "insufficient", "reason": "insufficient_history"}
    if not any(number(b["volume"]) > 0 for b in bars):
        return {**item, "status": "insufficient", "reason": "no_traded_volume"}
    # The host has the original stock stack; the isolated CCXT child never imports it.
    from src.platform.marketdata.collectors.kline_collector import KlineCollector, KlineData
    klines = [KlineData(date=stamp(b["timestamp_ms"]), **{key: float(b[key]) for key in ("open", "high", "low", "close", "volume")}) for b in bars]
    calculated = KlineCollector.calculate_indicators(klines)
    values = asdict(calculated)
    summary = KlineCollector.summarize_klines(klines, indicators=calculated)
    summary.update(timeframe=timeframe, asof=stamp(item["source_close_ms"]),
                   period_end=stamp(item["source_close_ms"]), computed_at=stamp(now_ms), params=PARAMS)
    for mapping in (values, summary):
        for old, new in (("change_5d", "change_5_bars"), ("change_20d", "change_20_bars"), ("macd_cross_days", "macd_cross_bars")):
            if old in mapping:
                mapping[new] = mapping.pop(old)
    summary["recent_5_up_bars"] = summary.pop("recent_5_up")
    summary["macd_status"] = (str(calculated.macd_cross) + f" ({calculated.macd_cross_days} bars)"
                              if calculated.macd_cross_days is not None else calculated.macd_cross)
    return {**item, "status": "ok", "indicators": values, "summary": summary}


def current(item, *, now_ms=None):
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    try:
        duration = TIMEFRAMES[item["timeframe"]]
        return (item["status"] == "ok" and item["algorithm_version"] == algorithm_version()
                and item["source_close_ms"] == now_ms // duration * duration
                and item["source_close_ms"] <= now_ms < item["valid_until_ms"])
    except (KeyError, TypeError):
        return False


def public_snapshot(item, *, now_ms=None):
    result = {k: v for k, v in item.items() if k != "bars"}
    if item["status"] == "ok" and not current(item, now_ms=now_ms):
        result.update(status="stale", indicators=None, summary=None)
    return result


class TechnicalCache:
    def __init__(self, clock=None):
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.cache = {}

    def collect(self, exchange, symbols, reader):
        now = self.clock()
        active = {(exchange, symbol, timeframe) for symbol in symbols for timeframe in PERIODS}
        self.cache = {key: value for key, value in self.cache.items() if key in active}
        requests = []
        for symbol in symbols:
            for timeframe in PERIODS:
                cached = self.cache.get((exchange, symbol, timeframe))
                if cached is None or now >= cached[0]:
                    requests.append({"symbol": symbol, "timeframe": timeframe})
        batches = None
        if requests and hasattr(reader, "history"):
            try:
                batches = reader.history(requests, limit=LOOKBACK + 1)
            except Exception:
                batches = None  # One bounded fallback per request is avoided below.
                batches = [{"error_type": "HistoryBatchUnavailable"} for _ in requests]
        for index, request in enumerate(requests):
            symbol, timeframe = request["symbol"], request["timeframe"]
            try:
                if batches is not None:
                    entry = batches[index]
                    if "error_type" in entry:
                        raise DataUnavailable("history source unavailable")
                    rows = entry["bars"]
                else:
                    rows = reader.bars(symbol, timeframe=timeframe, limit=LOOKBACK + 1)
                item = build_snapshot(exchange, symbol, timeframe, rows, now_ms=self.clock())
                expires = item["valid_until_ms"] if item["status"] == "ok" else self.clock() + 60000
            except Exception as exc:
                item = {"schema_version": 1, "algorithm_version": algorithm_version(), "exchange": exchange,
                        "symbol": symbol, "instrument_key": Instrument(exchange, symbol).key,
                        "timeframe": timeframe, "status": "unavailable", "reason": "invalid_or_missing_bars",
                        "bar_count": 0, "required_bars": LOOKBACK, "error_type": type(exc).__name__,
                        "indicators": None, "summary": None}
                expires = self.clock() + 60000
            self.cache[(exchange, symbol, timeframe)] = (expires, item)
        return [self.cache[(exchange, symbol, timeframe)][1] for symbol in symbols for timeframe in PERIODS]
