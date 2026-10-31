"""Pure eligibility and turnover ordering. A classification scope is not a seed pool."""
from decimal import localcontext

from .adapter import DataUnavailable, number, utc_ms
from .contracts import Instrument


def market_reason(row, config):
    try:
        Instrument(config.exchange, row['symbol'])
        base, quote = row['symbol'].split('/')
        if row.get('base') != base or row.get('quote') != quote:
            return 'market_identity_mismatch'
    except (ValueError, TypeError, KeyError):
        return 'invalid_spot_identity'
    if row.get('spot') is not True or row.get('contract') is not False:
        return 'not_confirmed_spot'
    if row.get('active') is not True:
        return 'inactive_or_unknown'
    if quote != config.quote_currency:
        return 'different_quote_currency'
    if base not in config.reviewed_plain_assets:
        return 'asset_classification_unknown'
    return None


def fresh(source_ms, now_ms, max_age_ms):
    source = utc_ms(source_ms)
    if not source <= now_ms or now_ms-source > max_age_ms:
        raise DataUnavailable('stale or future source')
    return source


def statistics(row, symbol, config, *, now_ms):
    if row.get('symbol') != symbol:
        raise DataUnavailable('statistics identity mismatch')
    source = fresh(row.get('source_ms'), now_ms, 120000)
    allowed={'binance':('quoteVolume','amount'),'okx':('volCcy24h',),'kraken':()}
    if row.get('quote_volume_source') not in allowed[config.exchange]:
        raise DataUnavailable('native quote turnover missing')
    volume = number(row.get('quote_volume'), positive=True)
    price = number(row.get('last'), positive=True)
    return {'symbol': symbol, 'instrument_key': Instrument(config.exchange,symbol).key,
            'exchange': config.exchange, 'quote_currency': config.quote_currency, 'price': str(price),
            'quote_volume': str(volume), 'quote_volume_source': row['quote_volume_source'],
            'quote_volume_window': 'rolling_24h', 'source_ms': source, 'observed_ms': now_ms,
            'liquid': volume >= number(config.min_quote_volume, positive=True)}


def spread(book, symbol, *, now_ms):
    if book.get('symbol') != symbol:
        raise DataUnavailable('book identity mismatch')
    source = fresh(book.get('source_ms'), now_ms, 15000)
    bid, ask = number(book.get('bid'),positive=True), number(book.get('ask'),positive=True)
    if ask < bid:
        raise DataUnavailable('inverted order book')
    with localcontext() as context:
        context.prec=80
        value=(ask-bid)/((ask+bid)/2)*100
    return {'bid':str(bid),'ask':str(ask),'spread_pct': str(value), 'book_source_ms': source, 'book_observed_ms': now_ms}


def choose(markets, rows, config, *, now_ms):
    """Return all exclusions and bounded selections; never fabricate ticker coverage."""
    if not isinstance(markets,list) or len(markets)>20000 or not isinstance(rows,list) or len(rows)>1000:
        raise ValueError('universe payload exceeds budget')
    entries, eligible, seen = [], [], set()
    for market in markets:
        symbol=market.get('symbol')
        reason=market_reason(market, config)
        if symbol in seen:
            reason='duplicate_market'
        seen.add(symbol)
        if reason:
            entries.append({'symbol':symbol,'stage':'market','reason':reason})
        else:
            eligible.append(symbol)
    symbols=[r.get('symbol') for r in rows]
    if len(symbols)!=len(set(symbols)):
        raise DataUnavailable('duplicate statistics identity')
    tickers={r.get('symbol'):r for r in rows}
    if set(tickers)-set(eligible):
        raise DataUnavailable('statistics outside eligible scope')
    ranked=[]
    valid_statistics_count=0
    for symbol in eligible:
        try:
            item=statistics(tickers.get(symbol,{}),symbol,config,now_ms=now_ms)
            valid_statistics_count+=1
            if not item.pop('liquid'):
                entries.append({'symbol':symbol,'stage':'statistics','reason':'below_turnover_threshold'})
            else:
                ranked.append(item)
        except (ValueError,TypeError) as exc:
            raw=tickers.get(symbol,{})
            entries.append({'symbol':symbol,'stage':'statistics','reason':'invalid_or_missing_statistics','error_type':type(exc).__name__,
                            'source_timestamp_present':type(raw.get('source_ms')) is int,
                            'native_turnover_reported':bool(raw.get('quote_volume_source'))})
    ranked.sort(key=lambda item:item['symbol'])
    ranked.sort(key=lambda item:number(item['quote_volume']),reverse=True)
    selected=ranked[:config.limit]
    return {'directory_count':len(markets),'market_eligible_count':len(eligible),'valid_statistics_count':valid_statistics_count,'liquidity_eligible_count':len(ranked),
            'selected_count':len(selected),'not_scanned_budget_count':max(0,len(ranked)-len(selected)),
            'selected':selected,'exclusions':entries}
