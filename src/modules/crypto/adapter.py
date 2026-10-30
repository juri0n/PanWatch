"""Credential-free CCXT spot reads. No generic exchange/method/params passthrough."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os
from urllib.parse import urlsplit

EXCHANGES = frozenset({"kraken", "binance", "okx"})
TIMEFRAMES = {"1m": 60_000, "5m": 300_000, "1h": 3_600_000, "1d": 86_400_000}


class DataUnavailable(ValueError):
    """Missing/invalid data must not become a zero price or an executable signal."""


def number(value, *, positive=False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise DataUnavailable("invalid number") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise DataUnavailable("invalid number range")
    if (len(result.as_tuple().digits) > 32 or not -64 <= result.as_tuple().exponent <= 20
            or (result and not -24 <= result.adjusted() <= 20)):
        raise DataUnavailable("number exceeds supported precision/range")
    return result


def utc_ms(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DataUnavailable("missing/invalid source timestamp")
    return value


@dataclass(frozen=True)
class Quote:
    exchange: str
    symbol: str
    quote_currency: str
    price: Decimal
    source_ms: int
    observed_ms: int

    def as_dict(self):
        return {"exchange": self.exchange, "symbol": self.symbol,
                "quote_currency": self.quote_currency, "price": str(self.price),
                "source_ms": self.source_ms, "observed_ms": self.observed_ms,
                "source_time": datetime.fromtimestamp(self.source_ms / 1000, timezone.utc).isoformat(),
                "volume_unit": "base asset", "change_window": "rolling 24h"}


class SpotReader:
    """Public market data only. Exchange instances are private implementation details.

    This boundary is not a Python code sandbox. Do not hand arbitrary Python tools
    to an Agent. No credentials can be supplied through this API or its config.
    """

    def __init__(self, exchange: str, *, max_age_seconds: int = 120):
        if exchange not in EXCHANGES:
            raise ValueError("unsupported exchange")
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 300:
            raise ValueError("max age must be 1..300 seconds")
        import ccxt
        settings = {
            "enableRateLimit": True, "timeout": 15_000,
            "options": {"defaultType": "spot"},
        }
        # Explicit infrastructure setting only, never an Agent/config JSON option.
        # Do not enable requests.trust_env: that would also read .netrc credentials.
        proxy = os.environ.get("PANWATCH_CRYPTO_HTTPS_PROXY")
        if proxy:
            parsed = urlsplit(proxy)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("invalid crypto HTTPS proxy")
            settings["httpsProxy"] = proxy
        self.__client = getattr(ccxt, exchange)(settings)
        self.exchange = exchange
        self.max_age_ms = max_age_seconds * 1000

    def _market(self, symbol):
        if not isinstance(symbol, str) or symbol.count("/") != 1 or ":" in symbol:
            raise ValueError("use an exact CCXT spot pair, e.g. BTC/USDT")
        markets = self.__client.load_markets()
        market = markets.get(symbol)
        if not market or market.get("spot") is not True or market.get("contract"):
            raise ValueError("unknown or non-spot market")
        if market.get("active") is False or market.get("quote") not in {"USD", "USDT"}:
            raise ValueError("inactive market or unsupported quote currency")
        return market

    def quote(self, symbol: str, *, now_ms: int | None = None) -> Quote:
        market = self._market(symbol)
        ticker = self.__client.fetch_ticker(symbol)
        observed = utc_ms(now_ms if now_ms is not None else self.__client.milliseconds())
        source = utc_ms(ticker.get("timestamp"))
        if source > observed or observed - source > self.max_age_ms:
            raise DataUnavailable("future or stale quote")
        if ticker.get("symbol") != symbol:
            raise DataUnavailable("ticker identity mismatch")
        return Quote(self.exchange, symbol, market["quote"],
                     number(ticker.get("last"), positive=True), source, observed)

    def bars(self, symbol: str, *, timeframe="1h", limit=120, now_ms=None) -> list[dict]:
        self._market(symbol)
        if timeframe not in TIMEFRAMES or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("unsupported timeframe or limit")
        if not self.__client.has.get("fetchOHLCV") or timeframe not in (self.__client.timeframes or {}):
            raise DataUnavailable("exchange does not support this OHLCV timeframe")
        raw = self.__client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        now = utc_ms(now_ms if now_ms is not None else self.__client.milliseconds())
        result, previous = [], 0
        for row in raw:
            if len(row) != 6:
                raise DataUnavailable("invalid OHLCV row")
            stamp = utc_ms(row[0])
            if stamp <= previous or stamp > now:
                raise DataUnavailable("unordered, duplicate or future OHLCV")
            previous = stamp
            op, high, low, close = [number(v, positive=True) for v in row[1:5]]
            volume = number(row[5])
            if not low <= min(op, close) <= max(op, close) <= high:
                raise DataUnavailable("inconsistent OHLCV range")
            if stamp + TIMEFRAMES[timeframe] > now:
                continue  # CCXT may include an incomplete latest candle.
            result.append(dict(timestamp_ms=stamp, open=str(op), high=str(high),
                               low=str(low), close=str(close), volume=str(volume)))
        if not result:
            raise DataUnavailable("no completed candles")
        return result
