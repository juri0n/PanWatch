"""Shared pure stock signal rules; no database, calendar, SDK or host imports."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RuleParameters:
    volume_high: float = 1.8
    volume_low: float = 0.7
    momentum_low: float = 1.5
    momentum_high: float = 8.5
    overheat: float = 10.5
    rebound: float = -5.5
    support_multiple: float = 1.03
    turnover_bonus: bool = True

    def __post_init__(self):
        values=(self.volume_high,self.volume_low,self.momentum_low,self.momentum_high,self.overheat,self.rebound,self.support_multiple)
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in values) or type(self.turnover_bonus) is not bool:
            raise ValueError('invalid finite rule parameters')
        if not (0 <= self.volume_low < self.volume_high and self.rebound < 0 < self.momentum_low <= self.momentum_high < self.overheat and 1 < self.support_multiple <= 2):
            raise ValueError('invalid rule parameter ordering')


STOCK_RULES = RuleParameters()


ACTION_BASE_SCORE: dict[str, float] = {
    "buy": 78.0,
    "add": 72.0,
    "hold": 58.0,
    "watch": 52.0,
    "alert": 45.0,
    "reduce": 30.0,
    "sell": 20.0,
    "avoid": 15.0,
}

STRATEGY_LABELS: dict[str, str] = {
    "trend_follow": "趋势延续",
    "macd_golden": "MACD金叉",
    "volume_breakout": "放量突破",
    "momentum": "动量强化",
    "pullback": "回踩确认",
    "rebound": "超跌反弹",
    "watchlist_agent": "Agent建议",
}

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))

def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None

def _strategy_labels(tags: list[str] | None, labels=None) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        if not t:
            continue
        out.append((STRATEGY_LABELS if labels is None else labels).get(t, t))
    return out

def derive_market_scan_decision(quote: dict | None, kline: dict | None, *, params=STOCK_RULES, labels=None) -> dict:
    q = quote or {}
    k = kline or {}
    points = 0
    tags: list[str] = []
    reasons: list[str] = []

    trend = (k.get("trend") or "").strip()
    if trend == "多头排列":
        points += 2
        tags.append("trend_follow")
        reasons.append("均线多头排列")
    elif trend == "空头排列":
        points -= 2

    macd = (k.get("macd_cross") or "").strip()
    if macd == "金叉":
        points += 2
        tags.append("macd_golden")
        reasons.append("MACD金叉")
    elif macd == "死叉":
        points -= 2

    vol_ratio = _safe_float(k.get("volume_ratio"))
    if vol_ratio is not None:
        if vol_ratio >= params.volume_high:
            points += 1
            tags.append("volume_breakout")
            reasons.append(f"放量({vol_ratio:.1f}x)")
        elif vol_ratio <= params.volume_low:
            points -= 1

    pct = _safe_float(q.get("change_pct"))
    if pct is not None:
        if params.momentum_low <= pct <= params.momentum_high:
            points += 1
            tags.append("momentum")
            reasons.append(f"涨幅{pct:+.2f}%")
        elif pct >= params.overheat:
            points -= 2
        elif pct <= params.rebound:
            points += 1
            tags.append("rebound")
            reasons.append("短线超跌")

    support = _safe_float(k.get("support_m")) or _safe_float(k.get("support"))
    last_close = _safe_float(k.get("last_close")) or _safe_float(q.get("current_price"))
    if support and last_close and 0 < support < last_close <= support * params.support_multiple:
        points += 1
        tags.append("pullback")
        reasons.append("回踩支撑附近")

    action = "watch"
    action_label = "观望"
    if points >= 4:
        action = "buy"
        action_label = "建仓"
    elif points >= 3:
        action = "add"
        action_label = "准备加仓"
    elif points <= -3:
        action = "avoid"
        action_label = "回避"

    signal = "，".join(_strategy_labels(tags[:3], labels)) if tags else "暂无明确信号"
    reason = "，".join(reasons[:3]) if reasons else "等待更高确定性信号后介入"
    return {
        "action": action,
        "action_label": action_label,
        "signal": signal,
        "reason": reason,
        "strategy_tags": tags,
        "points": points,
    }

def score_market_scan_candidate(
    *, action: str, quote: dict | None, kline: dict | None, strategy_tags: list[str] | None, params=STOCK_RULES, labels=None
) -> tuple[float, list[str]]:
    score = ACTION_BASE_SCORE.get((action or "").strip().lower(), 45.0)
    evidence: list[str] = []

    q = quote or {}
    k = kline or {}
    tags = strategy_tags or []

    if tags:
        score += min(8, len(tags) * 2)
        evidence.append("策略信号: " + " / ".join(_strategy_labels(tags[:3], labels)))

    pct = _safe_float(q.get("change_pct"))
    if pct is not None:
        if 1 <= pct <= 7:
            score += 2
            evidence.append(f"价格动量({pct:+.2f}%)")
        elif pct >= 10:
            score -= 3
            evidence.append(f"涨幅过热({pct:+.2f}%)")

    turnover = _safe_float(q.get("turnover"))
    if params.turnover_bonus and turnover is not None:
        if turnover >= 3e9:
            score += 3
            evidence.append("成交额高")
        elif turnover >= 1e9:
            score += 1

    trend = (k.get("trend") or "").strip()
    if trend == "多头排列":
        score += 5
        evidence.append("均线多头排列")
    elif trend == "空头排列":
        score -= 6
        evidence.append("均线空头排列")

    score = _clamp(score, 0.0, 100.0)
    return score, evidence[:8]
