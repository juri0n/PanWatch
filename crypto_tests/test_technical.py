"""Completed-bar contracts and parity with the existing stock calculator."""
from copy import deepcopy
from dataclasses import asdict

import pytest

from src.modules.crypto.adapter import DataUnavailable, TIMEFRAMES
from src.modules.crypto.technical import TechnicalCache, build_snapshot, current, public_snapshot, stamp
from src.modules.crypto.public_rpc import handle_request

NOW = 1793404800000  # UTC day boundary


def bars(timeframe="1d", count=120, forming=False):
    duration = TIMEFRAMES[timeframe]
    result = []
    for i in range(count + int(forming)):
        price = 100 + i + (i % 3)
        result.append(dict(timestamp_ms=NOW - (count-i)*duration, open=str(price),
                           high=str(price+4), low=str(price-2), close=str(price+1), volume=str(100+i)))
    return result


@pytest.mark.parametrize("timeframe", ["1d", "1h"])
def test_stock_formula_parity_and_period_contract(timeframe):
    pytest.importorskip('httpx', reason='Stock calculator runs in the host compatibility job')
    from src.platform.marketdata.collectors.kline_collector import KlineCollector, KlineData
    rows = bars(timeframe, forming=True)
    item = build_snapshot("okx", "BTC/USDT", timeframe, rows, now_ms=NOW+1234)
    legacy = asdict(KlineCollector.calculate_indicators([
        KlineData(date=stamp(row['timestamp_ms']), **{k: float(row[k]) for k in ('open','high','low','close','volume')})
        for row in rows[:-1]]))
    for old, new in (("change_5d","change_5_bars"),("change_20d","change_20_bars"),("macd_cross_days","macd_cross_bars")):
        if old in legacy:
            legacy[new] = legacy.pop(old)
    assert item['indicators'] == legacy
    assert item['status'] == 'ok' and item['bar_count'] == 120
    assert item['source_close_ms'] == NOW and item['summary']['timeframe'] == timeframe
    assert not any(k.endswith('_5d') or k.endswith('_20d') for k in item['summary'])
    assert item['params']['atr']['smoothing'] == 'simple_mean'
    assert item['params']['macd']['histogram_multiplier'] == 2
    assert current(item, now_ms=NOW+1234)
    public = public_snapshot(item, now_ms=NOW+TIMEFRAMES[timeframe])
    assert public['status'] == 'stale' and public['indicators'] is None and 'bars' not in public


@pytest.mark.parametrize("mutation", ['gap','duplicate','future','stale','nan','range','grid'])
def test_invalid_history_is_rejected(mutation):
    rows = bars('1h')
    if mutation == 'gap': del rows[10]
    elif mutation == 'duplicate': rows[10] = deepcopy(rows[9])
    elif mutation == 'future': rows[-1]['timestamp_ms'] = NOW+TIMEFRAMES['1h']
    elif mutation == 'stale': rows = rows[:-1]
    elif mutation == 'nan': rows[10]['close'] = 'NaN'
    elif mutation == 'range': rows[10]['high'] = '1'
    elif mutation == 'grid': rows[0]['timestamp_ms'] += 1
    with pytest.raises(DataUnavailable):
        build_snapshot('okx','BTC/USDT','1h',rows,now_ms=NOW+1)


def test_short_history_and_zero_volume_never_generate_zero_indicators():
    for rows in (bars(count=119), [{**row,'volume':'0'} for row in bars()]):
        item = build_snapshot('okx','BTC/USDT','1d',rows,now_ms=NOW+1)
        assert item['status'] == 'insufficient' and item['indicators'] is None


def test_history_batch_cache_boundary_and_negative_retry():
    pytest.importorskip('httpx', reason='Stock calculator runs in the host compatibility job')
    clock = [NOW+1]
    calls = []
    class Reader:
        def history(self, requests, limit):
            calls.append(requests)
            return [{'bars':bars(r['timeframe'])} for r in requests]
    cache = TechnicalCache(lambda:clock[0])
    assert len(cache.collect('okx',['BTC/USDT'],Reader())) == 2
    cache.collect('okx',['BTC/USDT'],Reader())
    assert len(calls) == 1
    clock[0] += TIMEFRAMES['1h']
    result = cache.collect('okx',['BTC/USDT'],Reader())
    assert calls[-1] == [{'symbol':'BTC/USDT','timeframe':'1h'}]
    assert result[1]['status'] == 'unavailable'  # previous hour data cannot be reused
    cache.collect('okx',['BTC/USDT'],Reader())
    assert len(calls) == 2


def test_history_rpc_uses_one_public_client_and_isolates_errors():
    clients=[]
    class Reader:
        def __init__(self, exchange): clients.append(exchange)
        def bars(self, symbol, timeframe, limit):
            if timeframe == '1h': raise RuntimeError('secret')
            return bars(timeframe)
    request=dict(operation='history',exchange='okx',requests=[dict(symbol='BTC/USDT',timeframe=t) for t in ('1d','1h')],limit=121)
    result=handle_request(request,Reader)
    assert clients == ['okx'] and len(result[0]['bars']) == 120
    assert result[1]['error_type'] == 'RuntimeError' and 'secret' not in str(result)
    for bad in ({**request,'apiKey':'x'}, {**request,'operation':'create_order'}, {**request,'requests':[request['requests'][0]]*2}):
        with pytest.raises(ValueError): handle_request(bad,Reader)


def test_research_receives_only_current_timeframes_without_raw_bars():
    pytest.importorskip('pan_investment_research')
    from datetime import datetime, timezone
    from decimal import Decimal
    from src.modules.crypto.adapter import Quote
    from src.modules.crypto.contracts import Snapshot, Holding, Instrument
    from src.modules.crypto.research import to_research_input
    snapshot = Snapshot((Holding('manual',Instrument('okx','BTC/USDT'),'0.001'),),
                        (Quote('okx','BTC/USDT','USDT',Decimal('123'),NOW+1,NOW+1),),
                        datetime.fromtimestamp((NOW+1)/1000,timezone.utc))
    daily = build_snapshot('okx','BTC/USDT','1d',bars(),now_ms=NOW+1)
    hourly = build_snapshot('okx','BTC/USDT','1h',bars('1h'),now_ms=NOW+1)
    hourly['algorithm_version'] = 'obsolete'
    prepared = to_research_input(snapshot,run_id='technical-parity',technical=[daily,hourly])
    content = prepared.evidence[0].content
    assert content['missing_timeframes'] == ['1h']
    assert len(content['technical_snapshots']) == 1
    assert 'bars' not in content['technical_snapshots'][0]
    assert content['indicators']['timeframe'] == '1d'


def test_field_errors_identify_pair_and_quantity():
    from src.modules.crypto.validation import ConfigFieldError, validate_position_fields
    for row,field in ((dict(symbol='BTC',quantity='0.001'),'symbol'),(dict(symbol='BTC/USDT',quantity='USDT'),'quantity')):
        with pytest.raises(ConfigFieldError) as error:
            validate_position_fields('okx',[row])
        assert error.value.field == f'positions.0.{field}'
        assert '第 1 项' in str(error.value)
