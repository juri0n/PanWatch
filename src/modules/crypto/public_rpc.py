"""One public request over stdin/stdout; no socket, shell, credentials or execution API."""
import json
import sys

from .adapter import SpotReader, TIMEFRAMES
from .contracts import Instrument


def handle_request(request, reader_factory=SpotReader):
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    operation = request.get("operation")
    if operation == "history":
        if set(request) != {"operation", "exchange", "requests", "limit"}:
            raise ValueError("invalid public history fields")
        items, limit = request["requests"], request["limit"]
        if not isinstance(items, list) or not 1 <= len(items) <= 16 or type(limit) is not int or not 1 <= limit <= 121:
            raise ValueError("invalid public history size")
        pairs = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {"symbol", "timeframe"} or item["timeframe"] not in ("1d", "1h"):
                raise ValueError("invalid public history request")
            Instrument(request["exchange"], item["symbol"])
            pairs.append((item["symbol"], item["timeframe"]))
        if len(set(pairs)) != len(pairs) or len({s for s, _ in pairs}) > 8:
            raise ValueError("duplicate or oversized history scope")
        reader = reader_factory(request["exchange"])
        result = []
        for symbol, timeframe in pairs:
            row = {"symbol": symbol, "timeframe": timeframe}
            try:
                row["bars"] = reader.bars(symbol, timeframe=timeframe, limit=limit)
            except Exception as exc:
                row["error_type"] = type(exc).__name__
            result.append(row)
        return result
    fields = {"operation", "exchange", "symbol"}
    if operation == "quotes":
        fields = {"operation", "exchange", "symbols"}
    if operation == "bars":
        fields |= {"timeframe", "limit"}
    if operation not in ("quote", "quotes", "bars") or set(request) != fields:
        raise ValueError("only public quote/bars requests are allowed")
    symbols = request["symbols"] if operation == "quotes" else [request["symbol"]]
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= 8 or any(not isinstance(s, str) for s in symbols) or len(set(symbols)) != len(symbols):
        raise ValueError("provide one to eight unique spot pairs")
    for symbol in symbols:
        Instrument(request["exchange"], symbol)
    if operation == "bars" and (request["timeframe"] not in TIMEFRAMES
            or type(request["limit"]) is not int or not 1 <= request["limit"] <= 500):
        raise ValueError("unsupported timeframe or limit")
    reader = reader_factory(request["exchange"])
    if operation == "quotes":
        return [reader.quote(symbol).as_dict() for symbol in symbols]
    if operation == "quote":
        return reader.quote(request["symbol"]).as_dict()
    return reader.bars(request["symbol"], timeframe=request["timeframe"], limit=request["limit"])


def main():
    try:
        raw = sys.stdin.read(2049)
        if len(raw) > 2048:
            raise ValueError("request too large")
        result = handle_request(json.loads(raw))
        print(json.dumps({"result": result}, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
