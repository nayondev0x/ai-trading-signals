"""In-memory data store (swap for a real DB later).

This keeps the starter dependency-free. Replace the functions below with
SQLAlchemy / Tortoise / a real database when you outgrow it.
"""
from datetime import datetime, timedelta
from itertools import count
from typing import List, Optional

from .models import Signal, SignalCreate, SignalStatus, SignalType

_id_counter = count(1)
_signals: List[Signal] = []


def _seed() -> None:
    """Populate some demo signals on startup."""
    demo = [
        ("BTC/USDT", SignalType.BUY, 64200, 68500, 62000, 82,
         "Breakout above resistance with rising volume."),
        ("ETH/USDT", SignalType.BUY, 3380, 3650, 3220, 74,
         "Bouncing off the 200-day moving average."),
        ("SOL/USDT", SignalType.SELL, 152, 134, 161, 68,
         "Bearish divergence on the 4h RSI."),
        ("AAPL", SignalType.HOLD, 198, 210, 188, 55,
         "Consolidating ahead of earnings."),
    ]
    for i, (sym, sig, entry, tgt, sl, conf, note) in enumerate(demo):
        _signals.append(
            Signal(
                id=next(_id_counter),
                symbol=sym,
                signal=sig,
                status=SignalStatus.ACTIVE,
                entry=entry,
                target=tgt,
                stop_loss=sl,
                confidence=conf,
                note=note,
                created_at=datetime.utcnow() - timedelta(hours=i * 3),
            )
        )


def list_signals(signal_type: Optional[SignalType] = None) -> List[Signal]:
    items = sorted(_signals, key=lambda s: s.created_at, reverse=True)
    if signal_type:
        items = [s for s in items if s.signal == signal_type]
    return items


def get_signal(signal_id: int) -> Optional[Signal]:
    return next((s for s in _signals if s.id == signal_id), None)


def add_signal(payload: SignalCreate) -> Signal:
    signal = Signal(id=next(_id_counter), **payload.model_dump())
    _signals.append(signal)
    return signal


def delete_signal(signal_id: int) -> bool:
    signal = get_signal(signal_id)
    if signal:
        _signals.remove(signal)
        return True
    return False


def stats() -> dict:
    total = len(_signals)
    buy = sum(1 for s in _signals if s.signal == SignalType.BUY)
    sell = sum(1 for s in _signals if s.signal == SignalType.SELL)
    active = sum(1 for s in _signals if s.status == SignalStatus.ACTIVE)
    avg_conf = round(sum(s.confidence for s in _signals) / total) if total else 0
    return {"total": total, "buy": buy, "sell": sell,
            "active": active, "avg_confidence": avg_conf}


_seed()
