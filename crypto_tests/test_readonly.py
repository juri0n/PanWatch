"""Offline contract tests. No exchange traffic or notification sends."""
import json
from decimal import Decimal

import ccxt
import pytest

from src.modules.crypto.adapter import SpotReader, Quote, DataUnavailable
from src.modules.crypto.portfolio import value_positions
from src.modules.crypto.__main__ import load_config, capture, scheduler_for

NOW = 1_800_000_000_000


@pytest.fixture
def reader(monkeypatch):
    # Patch the real pinned CCXT class methods, not a separate invented SDK.
    monkeypatch.setattr(ccxt.kraken, "load_markets", lambda self: {
        "BTC/USD": {"spot": True, "contract": False, "active": True, "quote": "USD"},
        "BTC/USDT": {"spot": True, "quote": "USDT"},
        "BTC/USD:BTC": {"spot": False, "contract": True, "quote": "USD"},
    })
    monkeypatch.setattr(ccxt.kraken, "fetch_ticker", lambda self, symbol: {
        "symbol": symbol, "last": "60000.01", "timestamp": NOW - 1000})
    return SpotReader("kraken")


def test_public_surface_and_sdk_credentials(reader):
    quote = reader.quote("BTC/USD", now_ms=NOW)
    assert quote.price == Decimal("60000.01")
    assert quote.as_dict()["source_time"].endswith("+00:00")
    client = reader._SpotReader__client  # Inspect only inside tests.
    assert not client.apiKey and not client.secret
    assert client.enableRateLimit and client.timeout == 15000
    assert reader.exchange == "kraken"  # An identifier, never the raw client.
    for method in ["create_order", "withdraw", "fetch_balance", "request"]:
        assert not hasattr(reader, method)
    with pytest.raises(TypeError):
        SpotReader("kraken", apiKey="forbidden")


def test_explicit_infrastructure_proxy_does_not_enable_netrc(monkeypatch):
    monkeypatch.setenv("PANWATCH_CRYPTO_HTTPS_PROXY", "http://127.0.0.1:8080")
    reader = SpotReader("okx")
    client = reader._SpotReader__client
    assert client.httpsProxy == "http://127.0.0.1:8080"
    assert client.session.trust_env is False
    assert not client.apiKey and not client.secret
    monkeypatch.setenv("PANWATCH_CRYPTO_HTTPS_PROXY", "file:///bad")
    with pytest.raises(ValueError):
        SpotReader("okx")


@pytest.mark.parametrize("pair", ["BTC", "btc/usd", "BTC/USD:BTC", "UNKNOWN/USD", "BTC/USDC"])
def test_fail_closed_market(reader, pair):
    with pytest.raises(ValueError):
        reader.quote(pair, now_ms=NOW)


@pytest.mark.parametrize("stamp", [None, NOW + 1, NOW - 120001, True, 0])
def test_quote_timestamp(reader, monkeypatch, stamp):
    monkeypatch.setattr(ccxt.kraken, "fetch_ticker", lambda *args: {
        "symbol": "BTC/USD", "last": 60000, "timestamp": stamp})
    with pytest.raises(DataUnavailable):
        reader.quote("BTC/USD", now_ms=NOW)


@pytest.mark.parametrize("price", [None, "NaN", "Infinity", "-1", "0"])
def test_quote_prices(reader, monkeypatch, price):
    monkeypatch.setattr(ccxt.kraken, "fetch_ticker", lambda *args: {
        "symbol": "BTC/USD", "last": price, "timestamp": NOW})
    with pytest.raises(DataUnavailable):
        reader.quote("BTC/USD", now_ms=NOW)


def test_closed_candles(reader, monkeypatch):
    rows = [[NOW - 7200000, 10, 12, 9, 11, 1], [NOW - 1000, 11, 12, 10, 11, 2]]
    monkeypatch.setattr(ccxt.kraken, "fetch_ohlcv", lambda *a, **kw: rows)
    result = reader.bars("BTC/USD", now_ms=NOW)
    assert len(result) == 1 and result[0]["volume"] == "1"
    rows[1][0] = rows[0][0]
    with pytest.raises(DataUnavailable):
        reader.bars("BTC/USD", now_ms=NOW)


@pytest.mark.parametrize("row", [
    [NOW - 7200000, 10, 9, 11, 10, 1],
    [NOW - 7200000, 10, 12, 9, 10, -1],
    [NOW - 7200000, 10, 12, 9, "NaN", 1],
    [NOW + 1, 10, 12, 9, 10, 1],
    [None, 10, 12, 9, 10, 1],
    [NOW - 1000, 10, 12, 9, 10, 1],
])
def test_invalid_or_incomplete_ohlcv(reader, monkeypatch, row):
    monkeypatch.setattr(ccxt.kraken, "fetch_ohlcv", lambda *a, **kw: [row])
    with pytest.raises(DataUnavailable):
        reader.bars("BTC/USD", now_ms=NOW)


def test_real_ccxt_okx_parser_uses_only_public_get(monkeypatch):
    market = {"id": "BTC-USDT", "symbol": "BTC/USDT", "base": "BTC", "quote": "USDT",
              "type": "spot", "spot": True, "contract": False, "active": True}
    monkeypatch.setattr(ccxt.okx, "load_markets", lambda self: {"BTC/USDT": market})
    monkeypatch.setattr(ccxt.okx, "market", lambda self, symbol: market)
    calls = []
    def request(self, path, api="public", method="GET", params=None, *args, **kwargs):
        calls.append((path, api, method, params))
        return {"code": "0", "data": [{"instType": "SPOT", "instId": "BTC-USDT",
                                          "last": "60000.01", "ts": str(NOW)}]}
    monkeypatch.setattr(ccxt.okx, "request", request)
    quote = SpotReader("okx").quote("BTC/USDT", now_ms=NOW)
    assert quote.price == Decimal("60000.01")
    assert calls == [("market/ticker", ["public"], "GET", {"instId": "BTC-USDT"})]


def test_fractional_holdings_and_currency_separation(reader):
    usd = reader.quote("BTC/USD", now_ms=NOW)
    usdt = reader.quote("BTC/USDT", now_ms=NOW)
    result = value_positions([
        {"symbol": "BTC/USD", "quantity": "0.00000001"},
        {"symbol": "BTC/USDT", "quantity": "0.1"}], {"BTC/USD": usd, "BTC/USDT": usdt})
    assert result["totals_by_quote_currency"] == {"USD": "0.0006000001", "USDT": "6000.001"}
    with pytest.raises(KeyError):
        value_positions([{"symbol": "ETH/USD", "quantity": "1"}], {})


def test_decimal_precision_is_not_default_context_limited():
    quantity = "1.1234567890123456789012345678901"
    quote = Quote("kraken", "BTC/USD", "USD", Decimal("12345678901234567890.12345678901"), NOW, NOW)
    result = value_positions([{"symbol": "BTC/USD", "quantity": quantity}], {"BTC/USD": quote})
    from decimal import localcontext
    with localcontext() as context:
        context.prec = 80
        assert Decimal(result["positions"][0]["value"]) == Decimal(quantity) * quote.price


@pytest.mark.parametrize("extra", [{"apiKey": "x"}, {"secret": "x"}, {"url": "http://bad"}, {"mode": "live"}])
def test_config_disallows_credentials_and_passthrough(tmp_path, extra):
    config = {"exchange": "kraken", "interval_seconds": 120,
              "positions": [{"symbol": "BTC/USD", "quantity": "0.01"}], **extra}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        load_config(path)


def test_failure_replaces_success_without_prices(tmp_path, reader, monkeypatch):
    config = {"exchange": "kraken", "interval_seconds": 120,
              "positions": [{"symbol": "BTC/USD", "quantity": "0.01"}]}
    monkeypatch.setattr(ccxt.kraken, "milliseconds", lambda *a: NOW)
    output = tmp_path / "state.json"
    assert capture(config, reader, output)
    assert json.loads(output.read_text())["status"] == "ok"
    def fail(*a):
        raise TimeoutError("sensitive upstream payload")
    monkeypatch.setattr(ccxt.kraken, "fetch_ticker", fail)
    assert not capture(config, reader, output)
    state = json.loads(output.read_text())
    assert state["status"] == "error" and "positions" not in state
    assert "sensitive" not in output.read_text()
    assert not list(tmp_path.glob(".crypto-*"))


def test_24_7_schedule(reader, tmp_path):
    from datetime import datetime, timezone
    config = {"interval_seconds": 120}
    job = scheduler_for(config, reader, tmp_path / "state.json").get_jobs()[0]
    assert job.max_instances == 1 and job.coalesce
    for day in [31, 1]:  # Saturday October 31 and Sunday November 1, 2026.
        now = datetime(2026, 10 if day == 31 else 11, day, tzinfo=timezone.utc)
        fire = job.trigger.get_next_fire_time(None, now)
        assert fire is not None and fire.tzinfo is not None
