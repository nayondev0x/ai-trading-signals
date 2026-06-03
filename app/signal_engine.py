"""Shared technical-signal engine.

Generates a BUY / SELL / NEUTRAL signal **strictly from live price data** by
combining several classic indicators into a single score — conceptually the
same approach TradingView uses (a vote across multiple indicators), so the
locally-computed providers (e.g. CoinGecko) produce signals of comparable
quality to the TradingView host.

Indicators used (all derived from the closing-price series):
  * RSI(14)              — momentum / overbought-oversold
  * SMA(20) vs SMA(50)   — trend direction (golden/death cross)
  * EMA(12) vs EMA(26)   — short-term trend (MACD line sign)
  * Price vs SMA(20)     — position relative to mean

Each indicator votes BUY (+1), SELL (-1) or NEUTRAL (0); the average vote
maps to the final recommendation. Everything is pure + deterministic so it's
easy to test and reason about.
"""
from __future__ import annotations

from typing import Dict, List, Optional

RSI_PERIOD = 14


# --------------------------------------------------------------------------- #
# Core indicator math
# --------------------------------------------------------------------------- #
def compute_rsi(closes: List[float], period: int = RSI_PERIOD) -> Optional[float]:
    """Classic Wilder's RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def ema(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    e = sum(closes[:period]) / period  # seed with SMA
    for price in closes[period:]:
        e = price * k + e * (1 - k)
    return e


# --------------------------------------------------------------------------- #
# Signal generation
# --------------------------------------------------------------------------- #
def _rsi_vote(rsi: Optional[float]) -> int:
    if rsi is None:
        return 0
    if rsi >= 60:
        return 1
    if rsi <= 40:
        return -1
    return 0


def analyze(closes: List[float]) -> Dict[str, object]:
    """Run the full indicator panel on a closing-price series.

    Returns a dict with the final signal, a -1..1 score, the contributing
    indicator values, and the individual votes (great for transparency / UI).
    """
    rsi = compute_rsi(closes)
    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    price = closes[-1] if closes else None

    votes: Dict[str, int] = {}

    # 1) RSI momentum
    votes["RSI"] = _rsi_vote(rsi)

    # 2) Trend: SMA20 vs SMA50 (golden cross = bull, death cross = bear)
    if sma20 is not None and sma50 is not None:
        votes["SMA20/50"] = 1 if sma20 > sma50 else -1 if sma20 < sma50 else 0
    else:
        votes["SMA20/50"] = 0

    # 3) MACD line sign: EMA12 vs EMA26
    if ema12 is not None and ema26 is not None:
        votes["EMA12/26"] = 1 if ema12 > ema26 else -1 if ema12 < ema26 else 0
    else:
        votes["EMA12/26"] = 0

    # 4) Price vs its 20-period mean
    if price is not None and sma20 is not None:
        votes["Price/SMA20"] = 1 if price > sma20 else -1 if price < sma20 else 0
    else:
        votes["Price/SMA20"] = 0

    active = [v for v in votes.values() if v != 0]
    score = round(sum(votes.values()) / len(votes), 3) if votes else 0.0

    # Map averaged vote -> recommendation (mirrors TradingView's banding).
    buy_votes = sum(1 for v in votes.values() if v == 1)
    sell_votes = sum(1 for v in votes.values() if v == -1)
    neutral_votes = sum(1 for v in votes.values() if v == 0)

    if score >= 0.5:
        signal, recommendation = "BUY", "STRONG_BUY"
    elif score >= 0.2:
        signal, recommendation = "BUY", "BUY"
    elif score <= -0.5:
        signal, recommendation = "SELL", "STRONG_SELL"
    elif score <= -0.2:
        signal, recommendation = "SELL", "SELL"
    else:
        signal, recommendation = "NEUTRAL", "NEUTRAL"

    # strength 0-100 = how lopsided the vote is toward the chosen side
    total = len(votes) or 1
    if signal == "BUY":
        strength = round(buy_votes / total * 100)
    elif signal == "SELL":
        strength = round(sell_votes / total * 100)
    else:
        strength = 50

    return {
        "signal": signal,
        "recommendation": recommendation,
        "score": score,
        "strength": strength,
        "rsi": rsi,
        "indicators": {
            "rsi": rsi, "sma20": sma20, "sma50": sma50,
            "ema12": ema12, "ema26": ema26, "price": price,
        },
        "votes": {"buy": buy_votes, "neutral": neutral_votes, "sell": sell_votes},
        "vote_detail": votes,
    }
