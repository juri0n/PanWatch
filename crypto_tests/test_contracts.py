from datetime import datetime, timezone
from decimal import Decimal
import json
import importlib.util
import pytest

from src.modules.crypto.adapter import Quote, DataUnavailable
from src.modules.crypto.contracts import Instrument, Holding, Snapshot

NOW = 1_800_000_000_000


@pytest.fixture
def snapshot():
    return Snapshot((Holding("manual", Instrument("okx", "BTC/USDT"), "0.00000001"),),
                    (Quote("okx", "BTC/USDT", "USDT", Decimal("60000.01"), NOW - 1000, NOW),),
                    datetime.fromtimestamp(NOW / 1000, timezone.utc))


def test_versioned_decimal_snapshot(snapshot):
    result = json.loads(json.dumps(snapshot.as_dict(), allow_nan=False))
    assert result["schema_version"] == 1 and result["market_hours"] == "24/7"
    assert result["positions"][0]["instrument_key"] == "CRYPTO:okx:BTC/USDT"
    assert result["positions"][0]["value"] == "0.0006000001"
    assert result["positions"][0]["quantity"] == "0.00000001"
    assert result["capabilities"] == ["market.read", "portfolio.manual.read"]


def test_exchange_and_account_identity_preserved(snapshot):
    q = snapshot.quotes[0]
    b = Quote("binance", q.symbol, "USDT", Decimal("61000"), q.source_ms, q.observed_ms)
    holdings = snapshot.holdings + (Holding("second", Instrument("okx", q.symbol), "0.1"),
                                  Holding("manual", Instrument("binance", q.symbol), "0.2"))
    result = Snapshot(holdings, (q, b), snapshot.as_of).as_dict()
    assert len(result["positions"]) == 3
    assert len({(p["account_id"], p["instrument_key"]) for p in result["positions"]}) == 3


@pytest.mark.parametrize("exchange,pair", [("okx", "BTC/USDT:USDT"), ("okx", "btc/usdt"),
                                           ("unverified", "BTC/USD"), ("okx", "BTC/USDC")])
def test_invalid_identity(exchange, pair):
    with pytest.raises(ValueError):
        Instrument(exchange, pair)


def test_stale_missing_future_and_duplicate_quotes_rejected(snapshot):
    from dataclasses import replace
    q = snapshot.quotes[0]
    for quotes in [(), (q, q), (replace(q, source_ms=NOW - 120001),),
                   (replace(q, observed_ms=NOW + 1),), (replace(q, quote_currency="USD"),)]:
        with pytest.raises(ValueError):
            Snapshot(snapshot.holdings, quotes, snapshot.as_of)
    with pytest.raises(ValueError):
        Snapshot(snapshot.holdings * 2, snapshot.quotes, snapshot.as_of)


def test_extreme_zero_exponent_rejected_before_serialization():
    with pytest.raises(ValueError):
        Holding("manual", Instrument("okx", "BTC/USDT"), "0E-999999999")


@pytest.mark.skipif(importlib.util.find_spec("pan_investment_research") is None,
                    reason="host research package not installed in the standalone worker")
def test_real_host_research_contract(snapshot):
    # Must run with the repository's actual research package, no stand-in schemas.
    from pan_investment_research import ResearchInput
    from src.modules.crypto.research import to_research_input
    prepared = to_research_input(snapshot, run_id="crypto-contract-test")
    assert isinstance(prepared, ResearchInput)
    assert ResearchInput.model_validate_json(prepared.model_dump_json()) == prepared
    assert prepared.securities[0].key == "CRYPTO:okx:BTC/USDT"
    assert prepared.securities[0].sellable_quantity is None
    assert prepared.evidence[0].available_at <= prepared.as_of
    assert "onchain" in prepared.evidence[0].content["unavailable_domains"]
    assert prepared.portfolio["crypto_snapshot"]["positions"][0]["quantity"] == "0.00000001"
