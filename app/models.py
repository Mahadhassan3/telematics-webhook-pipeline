from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal["position", "harsh_braking", "harsh_acceleration", "harsh_cornering"]
HARSH_TYPES = {"harsh_braking", "harsh_acceleration", "harsh_cornering"}


class TelematicsEvent(BaseModel):
    """One event from a vehicle gateway. Unknown fields are rejected on purpose:
    a silent schema drift from the sender should fail loudly, not be dropped."""

    model_config = {"extra": "forbid"}

    event_id: str = Field(min_length=1, max_length=64)
    vehicle_id: str = Field(min_length=1, max_length=32)
    type: EventType
    timestamp: datetime
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed_kmh: float = Field(ge=0, le=300)


class Alert(BaseModel):
    alert_id: int
    vehicle_id: str
    rule: str
    message: str
    event_id: str
    created_at: str
    delivery_status: str
    delivery_attempts: int
