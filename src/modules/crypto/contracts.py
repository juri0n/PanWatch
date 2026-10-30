"""Version 1 host boundary. Decimal strings are authoritative; no stock enums/DB."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Protocol

from .adapter import EXCHANGES, Quote, number, utc_ms, DataUnavailable
from .portfolio import value_positions

SCHEMA_VERSION = 1
DATA_GAPS = ("company_fundamentals", "capital_flow", "news", "onchain", "cost_basis", "tax")


class MarketReader(Protocol):
    def quote(self, symbol: str, *, now_ms: int | None = None) -> Quote: ...
    def bars(self, symbol: str, *, timeframe="1h", limit=120, now_ms=None) -> list[dict]: ...


class ReportDelivery(Protocol):
    """Subset of existing NotifierManager; host outbox owns policy and retries."""
    async def notify_with_result(self, title: str, content: str) -> dict: ...


@dataclass(frozen=True)
class Instrument:
    exchange: str
    symbol: str

    def __post_init__(self):
        if self.exchange not in EXCHANGES or not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*/(?:USD|USDT)", self.symbol):
            raise ValueError("invalid crypto spot identity")

    @property
    def key(self):
        return f"CRYPTO:{self.exchange}:{self.symbol}"


@dataclass(frozen=True)
class Holding:
    account_id: str
    instrument: Instrument
    quantity: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.account_id):
            raise ValueError("invalid account identifier")
        if not isinstance(self.quantity, str):
            raise ValueError("quantity must be an exact decimal string")
        number(self.quantity)


@dataclass(frozen=True)
class Snapshot:
    holdings: tuple[Holding, ...]
    quotes: tuple[Quote, ...]
    as_of: datetime
    max_age_seconds: int = 120

    def __post_init__(self):
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if type(self.max_age_seconds) is not int or not 1 <= self.max_age_seconds <= 300:
            raise ValueError("max age must be 1..300 seconds")
        if not isinstance(self.holdings, tuple) or not isinstance(self.quotes, tuple):
            raise ValueError("snapshot collections must be immutable tuples")
        if not 1 <= len(self.holdings) <= 100:
            raise ValueError("provide 1..100 holdings")
        pairs = [(p.account_id, p.instrument.key) for p in self.holdings]
        if len(set(pairs)) != len(pairs):
            raise ValueError("duplicate account/instrument holding")
        required = {p.instrument.key for p in self.holdings}
        found = set()
        cutoff = int(self.as_of.timestamp() * 1000)
        for quote in self.quotes:
            instrument = Instrument(quote.exchange, quote.symbol)
            if instrument.key in found or quote.quote_currency != quote.symbol.split("/")[1]:
                raise ValueError("duplicate quote or currency mismatch")
            found.add(instrument.key)
            if not isinstance(quote.price, Decimal):
                raise ValueError("quote price must be Decimal")
            number(quote.price, positive=True)
            source, observed = utc_ms(quote.source_ms), utc_ms(quote.observed_ms)
            if not source <= observed <= cutoff or cutoff - source > self.max_age_seconds * 1000:
                raise DataUnavailable("stale/future quote at snapshot cutoff")
        if found != required:
            raise DataUnavailable("snapshot requires exactly one quote per instrument")

    def as_dict(self):
        groups = {}
        quotes = {Instrument(q.exchange, q.symbol).key: q for q in self.quotes}
        for holding in self.holdings:
            groups.setdefault((holding.account_id, holding.instrument.exchange), []).append(holding)
        rows = []
        for (account, exchange), holdings in sorted(groups.items()):
            holdings = sorted(holdings, key=lambda p: p.instrument.key)
            result = value_positions([{"symbol": p.instrument.symbol, "quantity": p.quantity} for p in holdings],
                                     {p.instrument.symbol: quotes[p.instrument.key] for p in holdings})
            rows.extend({**row, **{field: format(Decimal(row[field]), "f") for field in ["quantity", "price", "value"]},
                         "account_id": account, "instrument_key": Instrument(exchange, row["symbol"]).key}
                        for row in result["positions"])
        return {"schema_version": SCHEMA_VERSION, "asset_class": "crypto_spot", "market": "CRYPTO",
                "mode": "public-readonly", "market_hours": "24/7",
                "as_of": self.as_of.astimezone(timezone.utc).isoformat(),
                "max_age_seconds": self.max_age_seconds, "positions": rows,
                "capabilities": ["market.read", "portfolio.manual.read"], "unavailable_domains": list(DATA_GAPS)}
