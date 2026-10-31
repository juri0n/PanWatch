"""Crypto technical-only profile over the same pure stock rules and calculator."""
from dataclasses import dataclass, field, asdict
from decimal import localcontext
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from src.modules.strategy import signal_rules
from .adapter import number, DataUnavailable
from .technical import build_snapshot, current

LABELS={'trend_follow':'均线多头','macd_golden':'MACD金叉状态','volume_breakout':'放量条件（原版标签）',
        'momentum':'周期动量','pullback':'接近支撑','rebound':'跌幅观察'}


@lru_cache(maxsize=1)
def rules_version():
    source=Path(signal_rules.__file__).read_text(encoding='utf-8').replace('\r\n','\n')
    return 'panwatch-rules/'+hashlib.sha256(source.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class CryptoProfile:
    primary_timeframe: str = '1d'
    rules: signal_rules.RuleParameters = field(default_factory=lambda:signal_rules.RuleParameters(turnover_bonus=False))

    def __post_init__(self):
        if self.primary_timeframe not in ('1d','1h') or not isinstance(self.rules,signal_rules.RuleParameters) or self.rules.turnover_bonus:
            raise ValueError('Crypto needs an explicit bar timeframe and no stock turnover bonus')

    @classmethod
    def from_dict(cls,value):
        if not isinstance(value,dict) or set(value)!={'primary_timeframe','rules'} or not isinstance(value['rules'],dict) or set(value['rules'])!=set(asdict(signal_rules.STOCK_RULES)):
            raise ValueError('invalid Crypto profile fields')
        return cls(value['primary_timeframe'],signal_rules.RuleParameters(**value['rules']))

    @property
    def version(self):
        payload=json.dumps({'schema':1,'profile':asdict(self),'rules_version':rules_version()},sort_keys=True)
        return 'crypto-technical-v1/'+hashlib.sha256(payload.encode()).hexdigest()[:16]


def score_snapshot(snapshot,profile,*,at_ms):
    if snapshot.get('schema_version')!=1 or not current(snapshot,now_ms=at_ms):
        raise DataUnavailable('technical snapshot is not current')
    # Recompute from captured raw bars, so metadata cannot make forged/missing
    # indicator values valid. The shared stock calculator remains authoritative.
    canonical=build_snapshot(snapshot['exchange'],snapshot['symbol'],snapshot['timeframe'],snapshot['bars'],now_ms=at_ms)
    if canonical['status']!='ok' or canonical['bars_sha256']!=snapshot['bars_sha256'] or canonical['indicators']!=snapshot['indicators'] or canonical['params']!=snapshot['params']:
        raise DataUnavailable('technical evidence does not match its captured inputs')
    previous,last=canonical['bars'][-2:]
    with localcontext() as context:
        context.prec=80
        change=float((number(last['close'])/number(previous['close'])-1)*100)
    quote={'change_pct':change,'current_price':float(number(last['close']))}
    summary=canonical['summary']
    decision=signal_rules.derive_market_scan_decision(quote,summary,params=profile.rules,labels=LABELS)
    score,evidence=signal_rules.score_market_scan_candidate(action=decision['action'],quote=quote,kline=summary,
        strategy_tags=decision['strategy_tags'],params=profile.rules,labels=LABELS)
    identity={key:canonical[key] for key in ('schema_version','instrument_key','timeframe','algorithm_version','params','source_close_ms','bars_sha256')}
    snapshot_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    return {'timeframe':canonical['timeframe'],'technical_score':score,'rule_points':decision['points'],
            'state':'matched' if decision['action'] in ('buy','add') else 'excluded' if decision['action']=='avoid' else 'watch',
            'strategy_tags':decision['strategy_tags'],'strategy_labels':[LABELS[tag] for tag in decision['strategy_tags']],
            'reasons':evidence,'return_1_bar_pct':change,'change_window':canonical['timeframe']+'/one_completed_bar',
            'price_reference':'last_completed_bar_close','risk_level':'unknown','calibrated':False,
            'profile_version':profile.version,'rules_version':rules_version(),'snapshot_id':snapshot_id,
            'source_close_ms':canonical['source_close_ms'],'bars_sha256':canonical['bars_sha256'],
            'indicator_algorithm_version':canonical['algorithm_version'],'valid_until_ms':canonical['valid_until_ms'],
            'excluded_score_domains':['stock_turnover_bonus','news','company_fundamentals','portfolio_constraints','learned_stock_weights'],
            'notes':['金叉为当前状态；放量不等于已突破；接近支撑不等于回踩确认。','技术参考分不是胜率、风险评级或交易指令。']}
