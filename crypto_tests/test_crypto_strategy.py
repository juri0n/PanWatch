from copy import deepcopy
from dataclasses import asdict, replace
import pytest

from src.modules.crypto.strategy_profile import CryptoProfile, score_snapshot
from src.modules.crypto.technical_scan import score_probe, current_view
from src.modules.crypto.scan_worker import run_probe
from src.modules.strategy.signal_rules import RuleParameters, STOCK_RULES
from crypto_tests.test_universe import Reader, config


@pytest.fixture
def probe():
    pytest.importorskip('httpx',reason='Host calculator is covered by the full compatibility job')
    return run_probe(config(),reader_factory=Reader,include_bars=True)


def test_profile_is_explicit_versioned_and_independent():
    profile=CryptoProfile()
    assert CryptoProfile.from_dict(asdict(profile))==profile
    changed=replace(profile,rules=replace(profile.rules,volume_high=2.0))
    assert profile.version!=changed.version
    assert STOCK_RULES.volume_high==1.8 and STOCK_RULES.turnover_bonus
    assert not profile.rules.turnover_bonus


@pytest.mark.parametrize('mutate',[lambda p:p.update(apiKey='x'),lambda p:p.update(primary_timeframe='5m'),
    lambda p:p['rules'].update(turnover_bonus=True),lambda p:p['rules'].update(volume_high=float('nan')),
    lambda p:p['rules'].update(momentum_low=10),lambda p:p['rules'].update(volume_high=True)])
def test_invalid_or_stock_biased_profile_is_rejected(mutate):
    data=asdict(CryptoProfile()); mutate(data)
    with pytest.raises(ValueError):CryptoProfile.from_dict(data)


def test_pool_scores_reference_the_same_captured_bars(probe):
    result=score_probe(probe,CryptoProfile(),at_ms=probe['finished_ms'])
    assert result['data_eligible_count']==2 and len(result['items'])==2
    assert len(result['technical_snapshots'])==4
    for item in result['items']:
        assert set(item['periods'])=={'1d','1h'}
        for timeframe,period in item['periods'].items():
            assert period['change_window']==timeframe+'/one_completed_bar'
            assert period['risk_level']=='unknown' and not period['calibrated']
            assert 'confidence' not in period and 'action' not in period
            snap=result['technical_snapshots'][period['snapshot_id']]
            assert snap['bars_sha256']==period['bars_sha256'] and 'bars' not in snap


def test_hash_mismatch_never_becomes_a_score(probe):
    probe['accepted'][0]['history'][0]['bars_sha256']='forged'
    result=score_probe(probe,CryptoProfile(),at_ms=probe['finished_ms'])
    assert len(result['items'])==1 and len(result['errors'])==1


def test_hourly_missing_does_not_become_confirmed(probe):
    probe['accepted'][0]['history'][1].pop('bars')
    result=score_probe(probe,CryptoProfile(),at_ms=probe['finished_ms'])
    item=next(row for row in result['items'] if row['symbol']==probe['accepted'][0]['symbol'])
    assert item['periods']['1h']['status']=='unavailable' and item['periods']['1d']['status']=='ok'


def test_stale_profile_data_and_book_cannot_reenter_current_ranking(probe):
    profile=CryptoProfile()
    result=score_probe(probe,profile,at_ms=probe['finished_ms'])
    assert len(current_view(result,profile,at_ms=probe['finished_ms'])['items'])==2
    assert not current_view(result,profile,at_ms=probe['finished_ms']+16000)['items']
    changed=replace(profile,rules=replace(profile.rules,volume_high=2.0))
    assert not current_view(result,changed,at_ms=probe['finished_ms'])['items']
    late=score_probe(probe,profile,at_ms=probe['finished_ms']+16000)
    assert not late['items'] and len(late['errors'])==2


def test_return_window_is_completed_bars_not_current_quote(probe):
    from src.modules.crypto.technical import build_snapshot
    captured=deepcopy(probe['accepted'][0]['history'][0])
    captured['bars'][-1].update(close='102')
    snap=build_snapshot('okx','BTC/USDT','1d',captured['bars'],now_ms=probe['finished_ms'])
    result=score_snapshot(snap,CryptoProfile(),at_ms=probe['finished_ms'])
    assert result['return_1_bar_pct']==2 and result['change_window']=='1d/one_completed_bar'
    modified=deepcopy(snap); modified['indicators']['ma20']=0
    with pytest.raises(ValueError):score_snapshot(modified,CryptoProfile(),at_ms=probe['finished_ms'])


def test_timeframe_fingerprint_and_score_filter_are_visible(probe):
    profile=CryptoProfile(primary_timeframe='1h')
    result=score_probe(probe,profile,at_ms=probe['finished_ms'],min_score=100)
    assert result['below_min_score_count']==2 and not result['items']
    assert result['data_eligible_count']==2 and result['profile_version']==profile.version
