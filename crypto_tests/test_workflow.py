"""PC workflow: real persistence and production collection; fake external services."""
import asyncio
from copy import deepcopy
from decimal import Decimal
import time
from types import SimpleNamespace

import pytest

from src.modules.crypto.adapter import Quote
from src.modules.crypto.workflow import CryptoWorkflow, Store, validate_config


CONFIG = {"exchange": "okx", "interval_seconds": 60,
          "positions": [{"symbol": "BTC/USDT", "quantity": "0.1234567890123456789"}], "alerts": []}


class Reader:
    max_age_ms = 120000

    def __init__(self, exchange):
        self.exchange = exchange

    def quote(self, symbol):
        now = int(time.time() * 1000)
        return Quote(self.exchange, symbol, symbol.split('/')[1], Decimal("100.123456789"), now, now)


def make(tmp_path, notifier=None, reader=Reader):
    async def notify(*args):
        return {"success": True}
    context = SimpleNamespace(report_language="zh-CN", notifier=SimpleNamespace(notify_with_result=notifier or notify))
    return CryptoWorkflow(tmp_path / "crypto.sqlite3", lambda name: context, reader_factory=reader)


def run(coro):
    return asyncio.run(coro)


def test_decimal_restart_and_failure_never_zero(tmp_path):
    async def scenario():
        service = make(tmp_path)
        await service.save(CONFIG)
        result = await service.refresh()
        assert result["snapshot"]["status"] == "ok"
        assert result["snapshot"]["positions"][0]["quantity"] == CONFIG["positions"][0]["quantity"]
        restart = make(tmp_path)
        assert restart.view()["config"] == CONFIG
        assert restart.view()["snapshot"]["totals_by_quote_currency"] == result["snapshot"]["totals_by_quote_currency"]
        service.readers['okx'].quote = lambda _: (_ for _ in ()).throw(RuntimeError("secret upstream payload"))
        error = await service.refresh()
        assert error["snapshot"] == {"status": "error", "at": error["snapshot"]["at"], "error_type": "RuntimeError"}
        assert "secret" not in str(error)
    run(scenario())


def test_stale_quote_visible_and_no_alert(tmp_path):
    async def scenario():
        service = make(tmp_path)
        await service.save(CONFIG)
        result = await service.refresh()
        result["snapshot"]["host_snapshot"]["positions"][0]["source_ms"] -= 121000
        service.store.put("snapshot", result["snapshot"])
        assert service.view()["snapshot"]["status"] == "stale"
        assert service.view()["events"] == []
    run(scenario())


def test_threshold_claim_survives_restart_and_quiet_hours(tmp_path):
    calls = []
    async def notify(*args):
        calls.append(args)
        return {"success": False, "skipped": "quiet_hours"}
    async def scenario():
        config = deepcopy(CONFIG)
        config["alerts"] = [{"symbol": "BTC/USDT", "op": ">=", "price": "100", "cooldown_minutes": 60, "notify": True}]
        service = make(tmp_path, notify)
        await service.save(config)
        await service.refresh()
        assert service.view()["events"][0]["delivery"]["status"] == "skipped"
        restart = make(tmp_path, notify)
        await restart.refresh()
        assert len(calls) == 1
        assert len(restart.view()["events"]) == 1
    run(scenario())


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(apiKey="forbidden"),
    lambda c: c.update(exchange="custom-url"),
    lambda c: c.update(interval_seconds=True),
    lambda c: c["positions"][0].update(quantity=0.1),
    lambda c: c["positions"][0].update(symbol="BTC/USDT:USDT"),
    lambda c: c.update(alerts=[{"symbol": "BTC/USDT", "op": ">=", "price": "NaN", "cooldown_minutes": 1, "notify": False}]),
])
def test_configuration_rejects_execution_and_ambiguous_input(mutate):
    config = deepcopy(CONFIG)
    mutate(config)
    with pytest.raises((ValueError, TypeError)):
        validate_config(config)


def test_restart_interrupts_pending_job(tmp_path):
    store = Store(tmp_path / "crypto.sqlite3")
    store.report({"id": "one", "status": "running"})
    assert Store(store.path).reports()[0]["status"] == "interrupted"


def test_report_uses_research_contract_persists_and_does_not_touch_stock_db(tmp_path):
    research = pytest.importorskip("pan_investment_research")
    async def scenario():
        service = make(tmp_path)
        await service.save(CONFIG)
        inputs = []
        async def fake_research(prepared, context):
            inputs.append(prepared)
            return research.ResearchResult(run_id=prepared.run_id, status="skipped", completion="skipped", recommendations=[], artifacts=[])
        service.research = fake_research
        await service.start_report()
        with pytest.raises(RuntimeError):
            await service.start_report()
        await service.report_task
        report = service.store.reports()[0]
        assert report["status"] == "skipped", report
        assert inputs[0].securities[0].key == "CRYPTO:okx:BTC/USDT"
        assert report["snapshot"]["positions"][0]["quantity"] == CONFIG["positions"][0]["quantity"]
        assert report["delivery"]["status"] == "disabled"
        assert [p.name for p in tmp_path.iterdir()] == ["crypto.sqlite3"]
    run(scenario())


def test_api_validates_configuration_and_requires_auth(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from src.modules.crypto.api import router
    app = FastAPI()
    app.state.crypto_workflow = make(tmp_path)
    async def deny():
        raise HTTPException(401)
    app.include_router(router, prefix="/api/crypto", dependencies=[Depends(deny)])
    with TestClient(app) as client:
        assert client.get("/api/crypto").status_code == 401
        assert client.put("/api/crypto/config", json=CONFIG).status_code == 401
    app.dependency_overrides[deny] = lambda: None
    with TestClient(app) as client:
        assert client.put("/api/crypto/config", json=CONFIG).status_code == 200
        assert client.post("/api/crypto/reports", json={"notify": "yes"}).status_code == 422
        assert client.post("/api/crypto/reports", json={"withdraw": True}).status_code == 422
        assert client.post("/api/crypto/order", json={}).status_code == 404


def test_real_research_graph_and_renderer_with_controlled_model(tmp_path, monkeypatch):
    pytest.importorskip("pan_investment_research")
    pytest.importorskip("openai")
    import importlib.util
    from pathlib import Path
    from src.modules.research.orchestration import gateway
    spec = importlib.util.spec_from_file_location("crypto_research_fixture",
        Path(__file__).parents[1] / "packages/pan-investment-research/tests/test_research.py")
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    model = fixtures.Model()
    monkeypatch.setattr(gateway, "ResearchModelGateway", lambda client: model)
    sent = []
    async def notify(title, content):
        sent.append(content)
        return {"success": True}
    async def scenario():
        service = make(tmp_path, notify)
        service.context_builder = lambda _: SimpleNamespace(report_language="en-US", ai_client=None,
            notifier=SimpleNamespace(notify_with_result=notify))
        await service.save(CONFIG)
        await service.start_report(notify=True)
        await service.report_task
        report = service.store.reports()[0]
        assert report["status"] == "complete", report
        assert report["delivery"]["status"] == "sent"
        assert sent and "PanWatch Crypto" in sent[0] and "BTC/USDT" in sent[0]
        assert model.calls["technical"] == 1
        assert all(p["input"]["securities"][0]["key"].startswith("CRYPTO:") for _, p in model.payloads if "input" in p)
    run(scenario())


def test_holdings_change_during_research_prevents_delivery(tmp_path):
    research = pytest.importorskip("pan_investment_research")
    async def scenario():
        service = make(tmp_path)
        await service.save(CONFIG)
        async def changed(prepared, context):
            config = deepcopy(CONFIG)
            config["positions"][0]["quantity"] = "2"
            await service.save(config)
            return research.ResearchResult(run_id=prepared.run_id, status="ready", recommendations=[], artifacts=[])
        service.research = changed
        await service.start_report(notify=True)
        await service.report_task
        report = service.store.reports()[0]
        assert report["status"] == "failed" and report["error_type"] == "DataUnavailable"
        assert report["delivery"]["status"] == "disabled"
    run(scenario())


def test_real_sqlite_backup_and_restore(tmp_path):
    from scripts.crypto_backup import backup, restore
    source = tmp_path / 'data'
    service = make(source)
    run(service.save(CONFIG))
    archive = tmp_path / 'backup.zip'
    backup(source, archive, stopped_confirmed=True)
    restore(archive, tmp_path / 'restored')
    restored = make(tmp_path / 'restored')
    assert restored.view()["config"] == CONFIG
