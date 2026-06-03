"""Pydantic data models for the Trading Signal Website."""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class Signal(BaseModel):
    """A single trading signal."""
    id: int
    symbol: str = Field(..., examples=["BTC/USDT"])
    signal: SignalType
    status: SignalStatus = SignalStatus.ACTIVE
    entry: float
    target: float
    stop_loss: float
    confidence: int = Field(..., ge=0, le=100, description="Confidence score 0-100")
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SignalCreate(BaseModel):
    """Payload used to create a new signal."""
    symbol: str
    signal: SignalType
    entry: float
    target: float
    stop_loss: float
    confidence: int = Field(50, ge=0, le=100)
    note: Optional[str] = None
