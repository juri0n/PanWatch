"""python -m src.modules.crypto --config ... --output ... [--watch]."""
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile

from .adapter import SpotReader, EXCHANGES, DataUnavailable
from .portfolio import validate_positions, value_positions
from .contracts import Holding, Instrument, Snapshot

log = logging.getLogger(__name__)


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"exchange", "interval_seconds", "positions"}:
        raise ValueError("config accepts only exchange, interval_seconds, positions; no credentials")
    if config["exchange"] not in EXCHANGES:
        raise ValueError("unsupported exchange")
    interval = config["interval_seconds"]
    if type(interval) is not int or not 60 <= interval <= 86400:
        raise ValueError("interval_seconds must be 60..86400")
    validate_positions(config["positions"])
    return config


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".crypto-", delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def collect(config, reader):
    quotes = {p["symbol"]: reader.quote(p["symbol"]) for p in config["positions"]}
    cutoff = max(q.observed_ms for q in quotes.values())
    if any(cutoff - q.source_ms > reader.max_age_ms for q in quotes.values()):
        raise DataUnavailable("portfolio quote expired during collection")
    as_of = datetime.fromtimestamp(cutoff / 1000, timezone.utc)
    snapshot = Snapshot(tuple(Holding("manual", Instrument(config["exchange"], p["symbol"]), p["quantity"])
                              for p in config["positions"]), tuple(quotes.values()), as_of,
                        max_age_seconds=reader.max_age_ms // 1000)
    return {"status": "ok", "mode": "public-readonly", "exchange": config["exchange"],
            "observed_at": as_of.isoformat(), "host_snapshot": snapshot.as_dict(),
            **value_positions(config["positions"], quotes)}


def capture(config, reader, output):
    try:
        atomic_json(output, collect(config, reader))
        return True
    except Exception as exc:
        # Do not retain a previous success under an apparently fresh state.
        # Exception messages can contain upstream payloads/URLs: record type only.
        atomic_json(output, {"status": "error", "mode": "public-readonly",
                            "observed_at": datetime.now(timezone.utc).isoformat(),
                            "error_type": type(exc).__name__})
        log.error("Crypto capture failed: %s", type(exc).__name__)
        return False


def scheduler_for(config, reader, output):
    from apscheduler.schedulers.blocking import BlockingScheduler
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(capture, "interval", seconds=config["interval_seconds"],
                      args=[config, reader, output], id="crypto-public-snapshot",
                      coalesce=True, max_instances=1, misfire_grace_time=30)
    return scheduler


def main():
    parser = argparse.ArgumentParser(description="PanWatch public crypto snapshot worker")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    if Path(args.config).resolve() == Path(args.output).resolve():
        parser.error("output must differ from config")
    config = load_config(args.config)
    reader = SpotReader(config["exchange"])
    success = capture(config, reader, args.output)
    if args.watch:
        scheduler_for(config, reader, args.output).start()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
