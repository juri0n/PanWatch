"""Frozen pre-extraction results, not a second copy of the rule algorithm."""
import json
from pathlib import Path
import pytest
from src.modules.strategy.signal_rules import derive_market_scan_decision, score_market_scan_candidate, RuleParameters

CASES=[json.loads(line) for line in (Path(__file__).parent/'fixtures/stock_signal_baseline.jsonl').read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('case',CASES)
def test_original_stock_results_are_identical(case):
    result=derive_market_scan_decision(case['quote'],case['kline'])
    score,evidence=score_market_scan_candidate(action=result['action'],quote=case['quote'],kline=case['kline'],strategy_tags=result['strategy_tags'])
    assert result==case['decision']
    assert (score,evidence)==(case['score'],case['evidence'])


def test_stock_wrapper_uses_the_same_entry_points():
    pytest.importorskip('sqlalchemy')
    from src.modules.strategy.entry_candidates import _derive_market_scan_decision, _score_market_scan_candidate
    for case in CASES:
        assert _derive_market_scan_decision(case['quote'],case['kline'])==case['decision']
        assert _score_market_scan_candidate(action=case['decision']['action'],quote=case['quote'],kline=case['kline'],strategy_tags=case['decision']['strategy_tags'])==(case['score'],case['evidence'])


def test_crypto_can_disable_stock_turnover_bonus_without_changing_stock_defaults():
    kwargs=dict(action='buy',quote={'turnover':3e9},kline={},strategy_tags=[])
    assert score_market_scan_candidate(**kwargs)[0]==81
    assert score_market_scan_candidate(**kwargs,params=RuleParameters(turnover_bonus=False))[0]==78
    assert score_market_scan_candidate(**kwargs)[0]==81
