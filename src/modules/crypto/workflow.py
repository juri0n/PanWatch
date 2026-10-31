"""Optional host workflow. Public reads only; isolated SQLite state, no stock writes."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .adapter import SpotReader, Quote, number, DataUnavailable
from .contracts import Holding, Instrument, Snapshot
from .portfolio import validate_positions
from .__main__ import collect
from .technical import TechnicalCache, public_snapshot, current as technical_current
from .validation import validate_position_fields, validate_threshold_price


DEFAULT_CONFIG = {"exchange": "okx", "interval_seconds": 60, "positions": [], "alerts": []}


def validate_config(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_CONFIG):
        raise ValueError("Only exchange, interval_seconds, positions and alerts are accepted")
    if not isinstance(value["exchange"], str):
        raise ValueError("Exchange must be a supported identifier")
    if type(value["interval_seconds"]) is not int or not 60 <= value["interval_seconds"] <= 3600:
        raise ValueError("Refresh interval must be 60..3600 seconds")
    positions = value["positions"]
    if not isinstance(positions, list) or len(positions) > 8:
        raise ValueError("At most eight manual positions are supported")
    if positions:
        validate_position_fields(value["exchange"], positions)
        validate_positions(positions)
    # Validate exchange even for an empty portfolio.
    Instrument(value["exchange"], "BTC/USDT")
    for p in positions:
        Instrument(value["exchange"], p["symbol"])
    alerts = value["alerts"]
    if not isinstance(alerts, list) or len(alerts) > 16:
        raise ValueError("At most sixteen thresholds are supported")
    seen = set()
    for index, rule in enumerate(alerts):
        if not isinstance(rule, dict) or set(rule) != {"symbol", "op", "price", "cooldown_minutes", "notify"}:
            raise ValueError("Invalid threshold fields")
        if (not isinstance(rule["symbol"], str) or not isinstance(rule["op"], str)
                or rule["symbol"] not in {p["symbol"] for p in positions} or rule["op"] not in {">=", "<="}):
            raise ValueError("Threshold requires a holding and >= or <=")
        validate_threshold_price(rule, index)
        if type(rule["cooldown_minutes"]) is not int or not 1 <= rule["cooldown_minutes"] <= 10080:
            raise ValueError("Cooldown must be 1..10080 minutes")
        if type(rule["notify"]) is not bool:
            raise ValueError("Notification opt-in must be boolean")
        identity = (rule["symbol"], rule["op"])
        if identity in seen:
            raise ValueError("Duplicate threshold")
        seen.add(identity)
    return deepcopy(value)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
            # Never resume an ambiguous external call after a process restart.
            for key, raw in db.execute("SELECT id,value FROM reports"):
                report = json.loads(raw)
                if report["status"] == "running":
                    report.update(status="interrupted", error_type="ProcessRestart")
                    db.execute("UPDATE reports SET value=? WHERE id=?", (json.dumps(report), key))
                elif report.get("delivery", {}).get("status") == "sending":
                    report["delivery"] = {"status": "unknown"}
                    db.execute("UPDATE reports SET value=? WHERE id=?", (json.dumps(report), key))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else deepcopy(default)

    def put(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value, allow_nan=False)))

    def report(self, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO reports VALUES (?,?)", (value["id"], json.dumps(value, allow_nan=False)))
            db.execute("DELETE FROM reports WHERE rowid NOT IN (SELECT rowid FROM reports ORDER BY rowid DESC LIMIT 50)")

    def reports(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT value FROM reports ORDER BY rowid DESC LIMIT 50")]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def snapshot_from(result):
    captured = result["host_snapshot"]
    rows = captured["positions"]
    return Snapshot(tuple(Holding(p["account_id"], Instrument(p["exchange"], p["symbol"]), p["quantity"]) for p in rows),
        tuple(Quote(p["exchange"], p["symbol"], p["quote_currency"], number(p["price"], positive=True),
                    p["source_ms"], p["observed_ms"]) for p in rows),
        datetime.now(timezone.utc), captured["max_age_seconds"])


class CryptoWorkflow:
    def __init__(self, path, context_builder, *, reader_factory=SpotReader):
        self.store = Store(path)
        self.context_builder = context_builder
        self.reader_factory = reader_factory
        self.lock = asyncio.Lock()
        self.report_task = None
        self.poll_task = None
        self.readers = {}
        self.stopping = False
        self.changed = asyncio.Event()
        self.technical_cache = TechnicalCache()

    def view(self):
        config = self.store.get("config", DEFAULT_CONFIG)
        result = self.store.get("snapshot", {"status": "empty"})
        if result["status"] == "ok":
            try:
                snapshot_from(result)
            except (ValueError, KeyError, TypeError):
                result = {**result, "status": "stale"}
        if "technical" in result:
            result = {**result, "technical": [public_snapshot(item) for item in result["technical"]]}
        reports = [{k: v for k, v in r.items() if k not in {"research", "snapshot", "technical"}} for r in self.store.reports()[:10]]
        return {"config": config, "snapshot": result, "reports": reports,
                "events": self.store.get("events", []), "mode": "public-readonly"}

    async def save(self, value):
        config = validate_config(value)
        async with self.lock:
            self.store.put("config", config)
            self.store.put("snapshot", {"status": "empty"})
            self.changed.set()
        return self.view()

    def event(self, event):
        self.store.put("events", [{"at": utc_now(), **event}, *self.store.get("events", [])][:100])

    async def refresh(self):
        async with self.lock:
            config = self.store.get("config", DEFAULT_CONFIG)
            if not config["positions"]:
                self.store.put("snapshot", {"status": "empty"})
                return self.view()
            try:
                def read():
                    exchange = config["exchange"]
                    if exchange not in self.readers:
                        self.readers[exchange] = self.reader_factory(exchange)
                    reader = self.readers[exchange]
                    technical = self.technical_cache.collect(exchange, [p["symbol"] for p in config["positions"]], reader)
                    if hasattr(reader, "prepare"):
                        reader.prepare([p["symbol"] for p in config["positions"]])
                    return {**collect(config, reader), "technical": technical}
                result = await asyncio.to_thread(read)
                snapshot_from(result)  # Collection may have consumed the freshness window.
                self.store.put("snapshot", result)
            except Exception as exc:
                self.store.put("snapshot", {"status": "error", "at": utc_now(), "error_type": type(exc).__name__})
                return self.view()
        # External delivery must not hold the configuration/collection lock.
        await self.alerts(config, result)
        return self.view()

    async def deliver(self, context, title, content):
        # Existing manager owns quiet-hours, per-channel retries, deduplication and proxies.
        # Persist a bounded, secret-free result; raw upstream exceptions may contain tokens.
        try:
            result = await asyncio.wait_for(context.notifier.notify_with_result(title, content), timeout=60)
            return {"status": "sent" if result.get("success") else "skipped" if result.get("skipped") else "failed"}
        except Exception as exc:
            return {"status": "failed", "error_type": type(exc).__name__}

    async def alerts(self, config, result):
        prices = {p["symbol"]: number(p["price"], positive=True) for p in result["positions"]}
        for rule in config["alerts"]:
            if config != self.store.get("config", DEFAULT_CONFIG):
                return
            try:
                snapshot_from(result)  # A preceding delivery may have taken a long time.
            except DataUnavailable:
                return
            price, limit = prices[rule["symbol"]], number(rule["price"], positive=True)
            if not (price >= limit if rule["op"] == ">=" else price <= limit):
                continue
            key = json.dumps([config["exchange"], rule["symbol"], rule["op"], rule["price"]])
            cooldowns = self.store.get("cooldowns", {})
            if time.time() - cooldowns.get(key, 0) < rule["cooldown_minutes"] * 60:
                continue
            # Claim before sending: crashes never automatically resend an ambiguous notification.
            cooldowns[key] = time.time()
            self.store.put("cooldowns", cooldowns)
            delivery = {"status": "disabled"}
            if rule["notify"]:
                try:
                    context = await asyncio.to_thread(self.context_builder, "daily_report")
                    delivery = await self.deliver(context, f"Crypto {rule['symbol']}",
                        f"{config['exchange']} {rule['symbol']}: {price} {rule['op']} {limit}\n"
                        f"Source: {result['observed_at']}\nPublic spot data / manual holdings / no execution")
                except Exception as exc:
                    delivery = {"status": "failed", "error_type": type(exc).__name__}
            self.event({"type": "threshold", "symbol": rule["symbol"], "price": str(price), "delivery": delivery})

    async def start_report(self, notify=False):
        if self.report_task and not self.report_task.done():
            raise RuntimeError("A crypto report is already running")
        if not self.store.get("config", DEFAULT_CONFIG)["positions"]:
            raise ValueError("Save manual holdings first")
        report = {"id": uuid.uuid4().hex, "at": utc_now(), "status": "running", "delivery": {"status": "disabled"}}
        self.store.report(report)
        self.report_task = asyncio.create_task(self.run_report(report, notify))
        return report

    async def research(self, prepared, context):
        from pan_investment_research import InvestmentResearch, ResearchPolicy
        from src.modules.research.orchestration.gateway import EvidenceTools
        from .research import crypto_model_gateway
        policy = ResearchPolicy(profile="intraday", graph="intraday_fast", specialists=["technical"],
            trigger_mode="always", debate=False, max_feedback=0, deadline_seconds=90,
            max_attempts=4, max_tools=2, max_total_tokens=min(160000, 64000 + 12000 * len(prepared.securities)),
            max_output_tokens=8192)
        return await asyncio.wait_for(InvestmentResearch().run(prepared, model=crypto_model_gateway(context.ai_client),
            tools=EvidenceTools(prepared.evidence), policy=policy), timeout=95)

    async def run_report(self, report, notify):
        try:
            await self.refresh()
            config = self.store.get("config", DEFAULT_CONFIG)
            result = self.store.get("snapshot")
            if not result or result.get("status") != "ok":
                raise DataUnavailable("No current quote snapshot")
            snapshot = snapshot_from(result)
            from .research import to_research_input
            from src.modules.research.orchestration.reporting import build_report
            context = await asyncio.to_thread(self.context_builder, "daily_report")
            language = context.report_language
            technical = result.get("technical", [])
            captured_technical = [item for item in technical if technical_current(item)]
            prepared = to_research_input(snapshot, run_id=report["id"], language=language, technical=technical)
            research = await self.research(prepared, context)
            if config != self.store.get("config", DEFAULT_CONFIG):
                raise DataUnavailable("Holdings changed while report was running")
            # A report is historical evidence. Never let late recommendations trigger delivery.
            snapshot_from(result)
            payload = research.model_dump(mode="json")
            markdown = build_report("intraday_monitor", payload, securities=[s.model_dump(mode="json") for s in prepared.securities],
                evidence=[e.model_dump(mode="json") for e in prepared.evidence], as_of=prepared.as_of.isoformat(), language=language)["content"]
            notice = ("Public spot data and manual holdings; current completed-bar indicators use the stock calculator. Models see presence, never quantities. Missing timeframe indicators, news, onchain, cost basis and tax data are unavailable. No execution capability."
                      if language == "en-US" else "公共现货数据与手动持仓；有效的已收盘K线指标复用股票计算器。模型只接收是否持仓的标记，不接收数量。缺失周期的指标、新闻、链上、成本或税务数据均不可用。不具备交易执行能力。")
            facts = [f"- {p['symbol']} · {p['quantity']} · {p['price']} {p['quote_currency']} · {p['source_time']}" for p in snapshot.as_dict()["positions"]]
            markdown = markdown.replace("## 个股分析", "## 现货标的分析").replace("## Stock analysis", "## Spot instrument analysis")
            technical_lines = []
            for item in technical:
                label = f"{item['symbol']} / {item['timeframe']}"
                if item in captured_technical:
                    values = item["indicators"]
                    metrics = " · ".join(f"{name}={values[name]:.8g}" for name in ("ma20", "rsi6", "macd_hist", "atr", "volume_ratio") if values.get(name) is not None)
                    technical_lines.append(f"- {label} · {item['bar_count']} bars · close {datetime.fromtimestamp(item['source_close_ms']/1000, timezone.utc).isoformat()} · {metrics}")
                else:
                    technical_lines.append(f"- {label}: {item['status']} ({item.get('reason', 'not_current')})")
            expired = any(not technical_current(item) for item in captured_technical)
            if expired:
                technical_lines.append("技术快照已跨越 K 线边界，仅作历史记录，本次不推送。 / Candle boundary passed: historical record, delivery suppressed.")
            markdown = "# PanWatch Crypto · 24/7\n\n" + notice + "\n\n" + "\n".join(facts) + "\n\n" + "\n".join(technical_lines) + "\n\n" + markdown
            report.update(status=research.completion, markdown=markdown, research=payload, snapshot=snapshot.as_dict(),
                          technical=[public_snapshot(item) for item in technical])
            self.store.report(report)  # Persist evidence before attempting external delivery.
            if notify and expired:
                report["delivery"] = {"status": "skipped", "reason": "technical_expired"}
            elif notify and research.completion == "complete":
                report["delivery"] = {"status": "sending"}
                self.store.report(report)
                report["delivery"] = await self.deliver(context, "PanWatch Crypto", markdown)
        except asyncio.CancelledError:
            report.update(status="interrupted", error_type="ServiceShutdown")
            raise
        except Exception as exc:
            report.update(status="failed", error_type=type(exc).__name__)
        finally:
            self.store.report(report)

    async def poll(self):
        while not self.stopping:
            self.changed.clear()
            await self.refresh()
            interval = self.store.get("config", DEFAULT_CONFIG)["interval_seconds"]
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    def start(self):
        self.poll_task = asyncio.create_task(self.poll())

    async def stop(self):
        self.stopping = True
        tasks = [t for t in (self.poll_task, self.report_task) if t and not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
