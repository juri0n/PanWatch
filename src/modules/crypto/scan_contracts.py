"""Opt-in public universe configuration; no account, URLs or arbitrary SDK options."""
from dataclasses import dataclass, asdict
import hashlib
import json
import re

from .adapter import EXCHANGES, number


@dataclass(frozen=True)
class UniverseConfig:
    exchange: str
    quote_currency: str
    limit: int
    min_quote_volume: str
    max_spread_pct: str
    reviewed_plain_assets: tuple[str, ...]
    deadline_seconds: int = 180

    def __post_init__(self):
        if self.exchange not in EXCHANGES or self.quote_currency not in ('USD', 'USDT'):
            raise ValueError('unsupported public universe')
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError('limit must be 1..100')
        if type(self.deadline_seconds) is not int or not 30 <= self.deadline_seconds <= 180:
            raise ValueError('deadline must be 30..180 seconds')
        if not isinstance(self.min_quote_volume, str) or not isinstance(self.max_spread_pct, str):
            raise ValueError('thresholds must be decimal strings')
        number(self.min_quote_volume, positive=True)
        if number(self.max_spread_pct, positive=True) > 5:
            raise ValueError('spread threshold must be at most 5 percent')
        if (not isinstance(self.reviewed_plain_assets, tuple) or not 1 <= len(self.reviewed_plain_assets) <= 100
                or len(set(self.reviewed_plain_assets)) != len(self.reviewed_plain_assets)
                or any(not isinstance(s, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,30}', s) for s in self.reviewed_plain_assets)):
            raise ValueError('provide an explicit reviewed asset classification scope')
        if set(self.reviewed_plain_assets) & {'USD','USDT','USDC','DAI','FDUSD','USDE','TUSD','BUSD','USDP'}:
            raise ValueError('known stable assets cannot be classified as plain base assets')

    @classmethod
    def from_dict(cls, value):
        fields = {'exchange', 'quote_currency', 'limit', 'min_quote_volume', 'max_spread_pct', 'reviewed_plain_assets', 'deadline_seconds'}
        if not isinstance(value, dict) or set(value) != fields or not isinstance(value['reviewed_plain_assets'], list):
            raise ValueError('invalid universe configuration fields')
        return cls(**{**value, 'reviewed_plain_assets': tuple(value['reviewed_plain_assets'])})

    def as_dict(self):
        return asdict(self)

    @property
    def version(self):
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(',', ':'))
        return 'universe-v1/' + hashlib.sha256(payload.encode()).hexdigest()[:16]
