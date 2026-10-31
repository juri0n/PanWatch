"""Optional dependency-isolated reader. The host sends only whitelisted public reads."""
import json
import os
from pathlib import Path
import subprocess
import time

from .adapter import Quote, number, utc_ms, DataUnavailable, TIMEFRAMES, SpotReader
from .contracts import Instrument


class ProcessSpotReader:
    max_age_ms = 120000

    def __init__(self, exchange, python, *, https_proxy=None):
        Instrument(exchange, "BTC/USDT")
        self.exchange = exchange
        self.python = str(Path(python).resolve(strict=True))
        self.proxy = https_proxy
        self.prepared = {}

    def _request(self, operation, symbol, **options):
        if operation not in ("quotes", "history"):
            Instrument(self.exchange, symbol)
        payload = {"operation": operation, "exchange": self.exchange,
                   **({"symbols": symbol} if operation == "quotes" else {"requests": symbol} if operation == "history" else {"symbol": symbol}), **options}
        # No host AI/auth keys, .env loading, PYTHONPATH or agent-supplied environment.
        env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATH", "HOME", "USERPROFILE") if k in os.environ}
        env["PYTHONUTF8"] = "1"
        proxy = self.proxy or os.environ.get("PANWATCH_CRYPTO_HTTPS_PROXY")
        if proxy:
            env["PANWATCH_CRYPTO_HTTPS_PROXY"] = proxy
        try:
            reply = subprocess.run([self.python, "-m", "src.modules.crypto.public_rpc"],
                input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                timeout=45, cwd=Path(__file__).resolve().parents[3], env=env, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if reply.returncode or len(reply.stdout) > 1000000:
                raise DataUnavailable("isolated public reader failed")
            result = json.loads(reply.stdout)
            if set(result) != {"result"}:
                raise DataUnavailable("invalid isolated reader response")
            return result["result"]
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            raise DataUnavailable("isolated public reader unavailable") from None

    def _quote(self, symbol, row):
        if (row.get("exchange") != self.exchange or row.get("symbol") != symbol
                or row.get("quote_currency") != symbol.split("/")[1]):
            raise DataUnavailable("isolated quote identity mismatch")
        source, observed = utc_ms(row["source_ms"]), utc_ms(row["observed_ms"])
        now = int(time.time() * 1000)
        if not source <= observed <= now or now - source > self.max_age_ms:
            raise DataUnavailable("isolated quote is not current")
        return Quote(self.exchange, symbol, row["quote_currency"], number(row["price"], positive=True), source, observed)

    def prepare(self, symbols):
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= 8 or len(set(symbols)) != len(symbols):
            raise ValueError("provide one to eight unique spot pairs")
        for symbol in symbols:
            Instrument(self.exchange, symbol)
        self.prepared = {}
        rows = self._request("quotes", symbols)
        if not isinstance(rows, list) or len(rows) != len(symbols) or {r["symbol"] for r in rows} != set(symbols):
            raise DataUnavailable("isolated quote coverage mismatch")
        self.prepared = {row["symbol"]: row for row in rows}

    def quote(self, symbol):
        return self._quote(symbol, self.prepared[symbol] if symbol in self.prepared else self._request("quote", symbol))

    def bars(self, symbol, *, timeframe="1h", limit=120):
        if timeframe not in TIMEFRAMES or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("unsupported timeframe or limit")
        return self._request("bars", symbol, timeframe=timeframe, limit=limit)

    def history(self, requests, *, limit=121):
        if not isinstance(requests, list) or not 1 <= len(requests) <= 16 or type(limit) is not int or not 1 <= limit <= 121:
            raise ValueError("invalid history batch")
        for request in requests:
            if set(request) != {"symbol", "timeframe"} or request["timeframe"] not in ("1d", "1h"):
                raise ValueError("invalid history request")
            Instrument(self.exchange, request["symbol"])
        result = self._request("history", requests, limit=limit)
        if not isinstance(result, list) or len(result) != len(requests) or any(
            item.get("symbol") != request["symbol"] or item.get("timeframe") != request["timeframe"]
            for item, request in zip(result, requests)):
            raise DataUnavailable("history identity mismatch")
        return result


def host_reader(exchange, *, https_proxy=None):
    root = Path(__file__).resolve().parents[3]
    default = root / ".venv-crypto" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    configured = os.environ.get("PANWATCH_CRYPTO_PYTHON")
    if configured or default.is_file():
        return ProcessSpotReader(exchange, configured or default, https_proxy=https_proxy)
    return SpotReader(exchange, https_proxy=https_proxy)
