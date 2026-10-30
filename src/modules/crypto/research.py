"""Projection into the EXISTING research contract; does not execute a model or trade."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

from .contracts import Snapshot, Instrument, DATA_GAPS


def to_research_input(snapshot: Snapshot, *, run_id: str, language="zh-CN"):
    # The public worker has no dependency on the research runtime. The host already
    # installs this package; keep this import lazy until that integration is enabled.
    from pan_investment_research import ResearchInput, Security, Evidence

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
        securities.append(Security(key=key, name=f"{quote.symbol} ({quote.exchange})", price=float(quote.price),
            held_quantity=float(quantities[key]), sellable_quantity=None,
            quote_expires_at=source + timedelta(seconds=snapshot.max_age_seconds)))
        evidence.append(Evidence(id=f"{key}/quote/{quote.source_ms}", stock_key=key, domain="technical",
            source=f"CCXT public spot/{quote.exchange}", observed_at=source, available_at=observed,
            content={"quote": {**quote.as_dict(), "current_price": float(quote.price)},
                     "asset_class": "crypto_spot", "market_hours": "24/7",
                     "unavailable_domains": list(DATA_GAPS),
                     "context": "Spot crypto trades 24/7. Company financial statements do not apply. "
                                "Do not invent unavailable fundamentals, news, flow or onchain data."}))
    return ResearchInput(run_id=run_id, as_of=snapshot.as_of, securities=securities, evidence=evidence,
        language=language, portfolio={"crypto_snapshot": snapshot.as_dict(),
        "validation_scope": "Manual holdings only; no exchange balance, cost basis or execution permissions. "
                            "Decimal strings in snapshot are authoritative; Security numbers are display projections."})
