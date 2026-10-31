"""One bounded public probe per process; one CCXT instance, no host/stock imports."""
import hashlib
import json
import sys
import time
import uuid
from decimal import Decimal

from .adapter import SpotReader, TIMEFRAMES, DataUnavailable, number
from .scan_contracts import UniverseConfig
from .technical import normalize_bars
from .universe import choose, market_reason, statistics, spread, fresh


def now_ms():
    return int(time.time()*1000)


def history(reader, symbol, timeframe, include_bars=False):
    bars=normalize_bars(reader.bars(symbol,timeframe=timeframe,limit=121),timeframe,now_ms())
    status='ok' if len(bars)>=120 and any(number(row['volume'])>0 for row in bars) else 'insufficient'
    return {'timeframe':timeframe,'status':status,'bar_count':len(bars),
            'source_close_ms':bars[-1]['timestamp_ms']+TIMEFRAMES[timeframe] if bars else None,
            'bars_sha256':hashlib.sha256(json.dumps(bars,sort_keys=True).encode()).hexdigest(),
            **({'bars':bars} if include_bars else {})}


def valid_entry(item, *, at_ms):
    """The same gate is used at publication and after loading historical probe data."""
    try:
        fresh(item['source_ms'],at_ms,120000)
        fresh(item['book_source_ms'],at_ms,15000)
        daily=next(row for row in item['history'] if row['timeframe']=='1d')
        return (daily['status']=='ok' and daily['bar_count']>=120
                and daily['source_close_ms']==at_ms//TIMEFRAMES['1d']*TIMEFRAMES['1d'])
    except (ValueError,KeyError,StopIteration,TypeError):
        return False


def run_probe(config, *, reader_factory=SpotReader, clock=time.monotonic, include_bars=False):
    started=now_ms()
    deadline=clock()+config.deadline_seconds
    def budget():
        if clock()>=deadline:
            raise TimeoutError('probe deadline')
    budget()
    reader=reader_factory(config.exchange)
    budget()
    markets=reader.public_markets()
    budget()
    eligible=[row['symbol'] for row in markets if market_reason(row,config) is None]
    if len(set(eligible))!=len(eligible):
        raise DataUnavailable('duplicate directory identities')
    rows=reader.public_statistics(eligible) if eligible else []
    selection=choose(markets,rows,config,now_ms=now_ms())
    entries=[]
    # Histories first, fresh statistics and books last: an early book is not
    # silently kept alive throughout a potentially long OHLCV sweep.
    for selected in selection['selected']:
        item={**selected,'history':[],'status':'pending','reasons':[],'history_calls':0,'book_calls':0}
        for timeframe in ('1d','1h'):
            try:
                budget()
                item['history_calls']+=1
                item['history'].append(history(reader,item['symbol'],timeframe,include_bars))
            except Exception as exc:
                item['history'].append({'timeframe':timeframe,'status':'unavailable','error_type':type(exc).__name__})
        entries.append(item)
    try:
        budget()
        latest=reader.public_statistics([item['symbol'] for item in entries]) if entries else []
        if len({row.get('symbol') for row in latest})!=len(latest):
            raise DataUnavailable('duplicate fresh statistics')
        updated={row.get('symbol'):row for row in latest}
        if set(updated)-{item['symbol'] for item in entries}:
            raise DataUnavailable('fresh statistics outside selected scope')
    except Exception:
        updated={}
    for item in entries:
        try:
            budget()
            stat=statistics(updated.get(item['symbol'],{}),item['symbol'],config,now_ms=now_ms())
            if not stat.pop('liquid'):
                raise DataUnavailable('turnover below threshold at publication')
            item.update(stat)
            budget()
            item['book_calls']+=1
            book=reader.public_book(item['symbol'])
            item['book_source_timestamp_present']=type(book.get('source_ms')) is int
            item.update(spread(book,item['symbol'],now_ms=now_ms()))
            if Decimal(item['spread_pct'])>number(config.max_spread_pct):
                item['reasons'].append('wide_spread')
        except Exception as exc:
            item['reasons'].append('invalid_or_missing_liquidity')
            item['error_type']=type(exc).__name__
    finished=now_ms()
    for item in entries:
        # Hourly confirmation is independently marked, never inferred from daily.
        for row in item['history']:
            if row['status']=='ok' and row['source_close_ms']!=finished//TIMEFRAMES[row['timeframe']]*TIMEFRAMES[row['timeframe']]:
                row['status']='stale'
        if not valid_entry(item,at_ms=finished):
            item['reasons'].append('incomplete_or_expired_evidence')
        item['status']='eligible' if not item['reasons'] else 'excluded'
    accepted=[item for item in entries if item['status']=='eligible']
    accepted.sort(key=lambda item:item['symbol'])
    accepted.sort(key=lambda item:number(item['quote_volume']),reverse=True)
    return {'schema_version':1,'run_id':uuid.uuid4().hex,'settings_version':config.version,'config':config.as_dict(),
            'mode':'public-universe-probe','includes_bars':include_bars,'classification_scope':'explicit_operator_review_not_full_market_classification',
            'started_ms':started,'finished_ms':finished,'elapsed_ms':finished-started,
            'status':'partial' if any(item['status']!='eligible' for item in entries) else 'complete' if entries else 'empty',
            'selection':selection,'entries':entries,'accepted':accepted,'accepted_count':len(accepted),
            'coverage':{'history_attempted_count':sum(item['history_calls']>0 for item in entries),
                        'book_attempted_count':sum(item['book_calls']>0 for item in entries),
                        'deadline_skipped_count':sum(item.get('error_type')=='TimeoutError' or any(row.get('error_type')=='TimeoutError' for row in item['history']) for item in entries),
                        'excluded_count':len(entries)-len(accepted)},
            'not_claimed':['strategy_scores','orderbook_depth','full_market_coverage','live_trading'],
            'capabilities_sample':{'native_turnover':bool(selection['valid_statistics_count']) if eligible else None,
                'book_source_timestamp':any(item.get('book_source_timestamp_present') for item in entries) if any(item['book_calls'] for item in entries) else None,
                'daily_history':any(any(row['timeframe']=='1d' and row['status']=='ok' for row in item['history']) for item in entries) if any(item['history_calls'] for item in entries) else None}}


def main():
    try:
        if sys.argv[1:] not in ([],['--with-bars']):
            raise ValueError('unsupported probe option')
        raw=sys.stdin.read(16385)
        if len(raw)>16384:
            raise ValueError('request too large')
        config=UniverseConfig.from_dict(json.loads(raw))
        print(json.dumps({'result':run_probe(config,include_bars=bool(sys.argv[1:]))},allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
