"""Projection into the EXISTING research contract; does not execute a model or trade."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

from .contracts import Snapshot, Instrument, DATA_GAPS


def crypto_model_gateway(client):
    """Add crypto semantics without changing the shared privacy-preserving engine."""
    from copy import deepcopy
    from src.modules.research.orchestration.gateway import ResearchModelGateway

    class CryptoModelGateway(ResearchModelGateway):
        async def complete(self, **kwargs):
            messages = deepcopy(kwargs["messages"])
            messages[0]["content"] += (
                " Crypto spot boundary: held_quantity is a redacted presence flag (0/1), NEVER token units or an account balance."
                " Exact holding amounts are withheld from models. Do not state any position amount, unit count or cost basis."
                " This is a 24/7 public spot research workflow, without order or withdrawal capability."
                " Use only captured quotes and explicitly supplied current indicator snapshots."
                " Indicator periods count bars of their stated timeframe, not calendar days."
                " Missing/stale/insufficient timeframes are unavailable, never zero."
                " Do not invent missing indicators, company fundamentals, news or onchain facts.")
            return await super().complete(**{**kwargs, "messages": messages})

    return CryptoModelGateway(client)


def to_research_input(snapshot: Snapshot, *, run_id: str, language="zh-CN", technical=()):
    # The public worker has no dependency on the research runtime. The host already
    # installs this package; keep this import lazy until that integration is enabled.
    from pan_investment_research import ResearchInput, Security, Evidence
    from .technical import PERIODS, current, public_snapshot

    quantities = {}
    with localcontext() as context:
        context.prec = 80
        for holding in snapshot.holdings:
            key = holding.instrument.key
            quantities[key] = quantities.get(key, Decimal(0)) + Decimal(holding.quantity)
    securities, evidence = [], []
    for quote in sorted(snapshot.quotes, key=lambda q: (q.exchange, q.symbol)):
        key = Instrument(quote.exchange, quote.symbol).key
        source = datetime.fromtimestamp(quote.source_ms / 1000, timezone.utc)
        observed = datetime.fromtimestamp(quote.observed_ms / 1000, timezone.utc)
        relevant = [item for item in technical if item.get("instrument_key") == key]
        verified = [public_snapshot(item, now_ms=int(snapshot.as_of.timestamp() * 1000)) for item in relevant
                    if current(item, now_ms=int(snapshot.as_of.timestamp() * 1000))]
        # Keep the canonical full snapshot locally; avoid sending duplicate indicator
        # and summary maps (or OHLCV rows) through every model stage.
        for item in verified:
            item.pop('indicators', None)
        verified.sort(key=lambda item: PERIODS.index(item["timeframe"]))
        expires = source + timedelta(seconds=snapshot.max_age_seconds)
        if verified:
            expires = min(expires, *(datetime.fromtimestamp(item["valid_until_ms"] / 1000, timezone.utc) for item in verified))
        securities.append(Security(key=key, name=f"{quote.symbol} ({quote.exchange})", price=float(quote.price),
            held_quantity=float(quantities[key]), sellable_quantity=None,
            quote_expires_at=expires))
        evidence.append(Evidence(id=f"{key}/quote/{quote.source_ms}", stock_key=key, domain="technical",
            source=f"CCXT public spot/{quote.exchange}", observed_at=source, available_at=observed,
            content={"quote": {**quote.as_dict(), "current_price": float(quote.price)},
                     "asset_class": "crypto_spot", "market_hours": "24/7",
                     "indicators": verified[0]["summary"] if verified else {},
                     "technical_snapshots": verified,
                     "missing_timeframes": [tf for tf in PERIODS if tf not in {item["timeframe"] for item in verified}],
                     "unavailable_domains": list(DATA_GAPS),
                     "context": "Spot crypto trades 24/7. Shared PanWatch stock formulas; periods count timeframe bars. Company financial statements do not apply. "
                                "Do not invent unavailable fundamentals, news, flow or onchain data."}))
    return ResearchInput(run_id=run_id, as_of=snapshot.as_of, securities=securities, evidence=evidence,
        language=language, portfolio={"crypto_snapshot": snapshot.as_dict(),
        "validation_scope": "Manual holdings only; no exchange balance, cost basis or execution permissions. "
                            "Decimal strings in snapshot are authoritative; Security numbers are display projections."})
