"""Public universe selection, partial evidence and persistence without production data."""
from copy import deepcopy
import json
import time
import sqlite3
from types import SimpleNamespace

import pytest

from src.modules.crypto.adapter import DataUnavailable, SpotReader, TIMEFRAMES
from src.modules.crypto.scan_contracts import UniverseConfig
from src.modules.crypto.universe import choose, market_reason, spread
from src.modules.crypto.scan_worker import run_probe, valid_entry
from src.modules.crypto.universe_probe import save_run, load_run, collect_probe

NOW=1793433601000


def config(**values):
    defaults=dict(exchange='okx',quote_currency='USDT',limit=10,
        min_quote_volume='10000000',max_spread_pct='0.3',reviewed_plain_assets=('BTC','ETH'),
        deadline_seconds=180)
    return UniverseConfig(**{**defaults,**values})


def market(base='BTC',**values):
    return dict(symbol=base+'/USDT',base=base,quote='USDT',spot=True,contract=False,active=True,**values)


def stat(symbol='BTC/USDT',volume='20000000'):
    return dict(symbol=symbol,source_ms=NOW,last='100',quote_volume=volume,quote_volume_source='volCcy24h')


@pytest.mark.parametrize('change',[{'apiKey':'x'},{'limit':True},{'limit':101},{'deadline_seconds':0},
    {'max_spread_pct':'NaN'},{'min_quote_volume':'0'},{'exchange':'https://evil'},
    {'quote_currency':'USDC'},{'reviewed_plain_assets':['USDT']},{'reviewed_plain_assets':['BTC','BTC']}])
def test_configuration_refuses_unbounded_or_private_options(change):
    value=json.loads(json.dumps(config().as_dict()))
    value.update(change)
    with pytest.raises((ValueError,TypeError)):
        UniverseConfig.from_dict(value)


@pytest.mark.parametrize('field,value,reason',[
    ('active',None,'inactive_or_unknown'),('active',False,'inactive_or_unknown'),
    ('contract',True,'not_confirmed_spot'),('spot',False,'not_confirmed_spot'),
    ('base','ETH','market_identity_mismatch')])
def test_market_flags_must_be_explicit(field,value,reason):
    row=market(); row[field]=value
    assert market_reason(row,config())==reason
    assert market_reason(market('NOTREVIEWED'),config())=='asset_classification_unknown'


def test_turnover_units_top_limit_and_coverage():
    value=config(limit=1)
    result=choose([market(),market('ETH'),market('OTHER')],
                  [stat(),stat('ETH/USDT','30000000')],value,now_ms=NOW)
    assert result['selected'][0]['symbol']=='ETH/USDT'
    assert result['market_eligible_count']==2 and result['not_scanned_budget_count']==1
    assert result['exclusions'][0]['reason']=='asset_classification_unknown'
    assert result['selected'][0]['quote_volume_window']=='rolling_24h'


@pytest.mark.parametrize('field,value',[('quote_volume',None),('quote_volume','NaN'),('quote_volume','-1'),
    ('quote_volume_source',None),('quote_volume_source','computed'),('source_ms',NOW-120001),
    ('source_ms',NOW+1),('source_ms',None),('last','0')])
def test_invalid_statistics_never_become_ranked_zero(field,value):
    row=stat(); row[field]=value
    result=choose([market()],[row],config(),now_ms=NOW)
    assert not result['selected']
    assert result['exclusions'][0]['reason']=='invalid_or_missing_statistics'


def test_duplicate_and_extra_tickers_fail_closed():
    for rows in ([stat(),stat()],[stat('ETH/USDT')]):
        with pytest.raises(DataUnavailable):choose([market()],rows,config(),now_ms=NOW)


@pytest.mark.parametrize('change',[{'source_ms':None},{'source_ms':NOW-15001},{'source_ms':NOW+1},
    {'bid':'102'},{'ask':'NaN'},{'bid':'0'},{'symbol':'ETH/USDT'}])
def test_spread_requires_real_current_source_and_valid_prices(change):
    row=dict(symbol='BTC/USDT',source_ms=NOW,bid='100',ask='100.1'); row.update(change)
    with pytest.raises(DataUnavailable):spread(row,'BTC/USDT',now_ms=NOW)


class Reader:
    def __init__(self,exchange): self.exchange=exchange
    def public_markets(self):return [market(),market('ETH'),market('OTHER')]
    def public_statistics(self,symbols):
        return [{**stat(s),'source_ms':int(time.time()*1000)} for s in symbols]
    def public_book(self,symbol):
        return dict(symbol=symbol,source_ms=int(time.time()*1000),bid='100',ask='100.1')
    def bars(self,symbol,timeframe,limit):
        now=int(time.time()*1000); duration=TIMEFRAMES[timeframe]; end=now//duration*duration
        return [dict(timestamp_ms=end-(120-i)*duration,open='99',high='102',low='98',close='100',volume='10') for i in range(120)]


def test_unheld_candidate_positive_path_and_restart_expiry(tmp_path):
    result=run_probe(config(),reader_factory=Reader)
    assert result['accepted_count']==2 and result['status']=='complete'
    assert all(valid_entry(item,at_ms=result['finished_ms']) for item in result['accepted'])
    assert not any('holding' in key for key in result)
    assert result['selection']['directory_count']==3
    store=tmp_path/'probe.sqlite3'
    save_run(store,result)
    assert load_run(store,result['run_id'],at_ms=result['finished_ms'])['accepted_count']==2
    old=load_run(store,result['run_id'],at_ms=result['finished_ms']+16000)
    assert old['accepted_count']==0 and old['historical']
    assert all(item['status']=='stale' for item in old['entries'])
    with pytest.raises(Exception):save_run(store,result)  # no overwrite of a captured run


def test_missing_book_time_is_partial_without_observation_time_substitution():
    class Missing(Reader):
        def public_book(self,symbol):return dict(symbol=symbol,source_ms=None,bid='100',ask='100.1')
    result=run_probe(config(),reader_factory=Missing)
    assert result['status']=='partial' and not result['accepted']
    assert result['capabilities_sample']['book_source_timestamp'] is False


def test_one_history_failure_does_not_hide_other_candidate():
    class Failure(Reader):
        def bars(self,symbol,timeframe,limit):
            if symbol=='ETH/USDT':raise RuntimeError('secret')
            return super().bars(symbol,timeframe,limit)
    result=run_probe(config(),reader_factory=Failure)
    assert result['status']=='partial' and result['accepted_count']==1
    assert 'secret' not in str(result)


def test_pinned_sdk_public_projection_and_native_provenance(monkeypatch):
    import ccxt
    monkeypatch.setattr(ccxt.okx,'load_markets',lambda _: {'BTC/USDT':market()})
    monkeypatch.setattr(ccxt.okx,'fetch_tickers',lambda _,symbols: {'BTC/USDT':{
        'symbol':'BTC/USDT','timestamp':NOW,'last':100,'quoteVolume':20000000,'info':{'volCcy24h':'20000000'}}})
    monkeypatch.setattr(ccxt.okx,'fetch_order_book',lambda _,symbol,limit:dict(symbol=symbol,timestamp=NOW,bids=[[100,1]],asks=[[100.1,1]]))
    reader=SpotReader('okx')
    assert reader.public_markets()==[market()]
    assert reader.public_statistics(['BTC/USDT'])[0]['quote_volume_source']=='volCcy24h'
    assert reader.public_book('BTC/USDT')['source_ms']==NOW
    assert not reader._SpotReader__client.apiKey and not reader._SpotReader__client.secret
    assert not hasattr(reader,'create_order') and not hasattr(reader,'fetch_balance')


def test_kraken_computed_turnover_is_not_promoted_to_native(monkeypatch):
    import ccxt
    monkeypatch.setattr(ccxt.kraken,'load_markets',lambda _: {'BTC/USDT':market()})
    monkeypatch.setattr(ccxt.kraken,'fetch_tickers',lambda _,symbols: {'BTC/USDT':{
        'symbol':'BTC/USDT','timestamp':NOW,'last':100,'quoteVolume':20000000,'info':{'v':['1','2'],'p':['100','100']}}})
    row=SpotReader('kraken').public_statistics(['BTC/USDT'])[0]
    assert row['reported_quote_volume']==20000000 and row['quote_volume'] is None


def test_usd_and_usdt_are_separate_universes():
    usd=UniverseConfig('okx','USD',10,'10000000','0.3',('BTC',),180)
    assert market_reason(market(),usd)=='different_quote_currency'
    assert usd.version!=config().version


def test_deadline_stops_requests_and_records_unscanned_work():
    ticks=[0]
    def clock():
        ticks[0]+=1
        return 0 if ticks[0]<5 else 181
    result=run_probe(config(),reader_factory=Reader,clock=clock)
    assert result['status']=='partial' and not result['accepted']
    assert result['coverage']['deadline_skipped_count']==2
    assert result['coverage']['history_attempted_count']==0
    assert result['coverage']['book_attempted_count']==0
    assert result['capabilities_sample']['book_source_timestamp'] is None


def test_large_and_small_decimal_order_is_exact():
    a=stat('BTC/USDT','100000000000000000000.00000000001')
    b=stat('ETH/USDT','100000000000000000000.00000000002')
    result=choose([market(),market('ETH')],[a,b],config(limit=1),now_ms=NOW)
    assert result['selected'][0]['symbol']=='ETH/USDT'


def test_foreign_database_is_never_extended(tmp_path):
    path=tmp_path/'renamed.db'
    with sqlite3.connect(path) as db:db.execute('CREATE TABLE stocks (id INTEGER)')
    with pytest.raises(ValueError):save_run(path,{'run_id':'x'})
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('stocks',)]


def test_host_protocol_strips_secrets_and_rechecks_result(monkeypatch,tmp_path):
    from src.modules.crypto import universe_probe
    payload=run_probe(config(),reader_factory=Reader)
    calls=[]
    def fake(args,**options):
        calls.append((args,options))
        return SimpleNamespace(returncode=0,stdout=json.dumps({'result':payload}))
    monkeypatch.setenv('OPENAI_API_KEY','never-forward')
    monkeypatch.setenv('PYTHONPATH','never-forward')
    monkeypatch.setattr(universe_probe.subprocess,'run',fake)
    interpreter=tmp_path/'python'; interpreter.write_text('test executable placeholder')
    assert collect_probe(config(),interpreter)['accepted_count']==2
    assert 'OPENAI_API_KEY' not in calls[0][1]['env'] and 'PYTHONPATH' not in calls[0][1]['env']
    assert calls[0][1]['timeout']==200 and 'shell' not in calls[0][1]
    payload['accepted'][0]['spread_pct']='0'
    with pytest.raises(ValueError):collect_probe(config(),interpreter)


def test_host_rejects_wrong_exchange_even_if_claimed_config_is_correct(monkeypatch,tmp_path):
    from src.modules.crypto import universe_probe
    payload=run_probe(config(),reader_factory=Reader)
    payload['entries'][0]['exchange']='binance'
    monkeypatch.setattr(universe_probe.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps({'result':payload})))
    interpreter=tmp_path/'python'; interpreter.write_text('fixture')
    with pytest.raises(ValueError):collect_probe(config(),interpreter)
