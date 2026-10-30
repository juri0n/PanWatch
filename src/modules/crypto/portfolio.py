"""Manual spot position valuation; does not claim tax P&L or USD/USDT parity."""
from decimal import Decimal, localcontext

from .adapter import Quote, number


def validate_positions(positions):
    if not isinstance(positions, list) or not positions or len(positions) > 100:
        raise ValueError("provide 1..100 manual spot positions")
    seen = set()
    for position in positions:
        if not isinstance(position, dict) or set(position) != {"symbol", "quantity"}:
            raise ValueError("position requires only symbol and quantity")
        symbol = position["symbol"]
        if not isinstance(symbol, str) or symbol in seen:
            raise ValueError("invalid or duplicate symbol")
        seen.add(symbol)
        # JSON numeric floats can already have lost precision; require decimal strings.
        if not isinstance(position["quantity"], str):
            raise ValueError("quantity must be a decimal string")
        number(position["quantity"])


def value_positions(positions: list[dict], quotes: dict[str, Quote]) -> dict:
    validate_positions(positions)
    rows, totals = [], {}
    for position in positions:
        symbol = position["symbol"]
        quote = quotes[symbol]  # Missing data is a failure, never a partial total.
        if quote.symbol != symbol:
            raise ValueError("position/quote identity mismatch")
        quantity = number(position["quantity"])
        with localcontext() as context:
            context.prec = 80  # two <=32-digit inputs plus up to 100 summed positions
            value = quantity * quote.price
            currency = quote.quote_currency
            totals[currency] = totals.get(currency, Decimal(0)) + value
        rows.append({**quote.as_dict(), "quantity": str(quantity), "value": str(value)})
    return {"positions": rows, "totals_by_quote_currency": {k: str(v) for k, v in totals.items()},
            "basis": "manual spot holdings; no tax or cost-basis accounting; no FX conversion"}
