"""Explicit public-network smoke; never run as an offline unit test."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import platform
from pathlib import Path

from src.modules.crypto.adapter import SpotReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = {"at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
              "ccxt": importlib.metadata.version("ccxt"), "mode": "public-no-credentials", "results": []}
    for exchange, pair in [("okx", "BTC/USDT"), ("binance", "BTC/USDT"), ("kraken", "BTC/USD")]:
        row = {"exchange": exchange, "pair": pair}
        reader = SpotReader(exchange)
        for kind in ["quote", "bars"]:
            try:
                result = reader.quote(pair).as_dict() if kind == "quote" else reader.bars(pair, limit=3)
                row[kind] = {"status": "PASS", "result": result}
            except Exception as exc:
                row[kind] = {"status": "FAIL", "error_type": type(exc).__name__}
        report["results"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(r[k]["status"] == "PASS" for r in report["results"] for k in ["quote", "bars"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
