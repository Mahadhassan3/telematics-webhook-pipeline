"""Settings read from environment variables, with safe defaults for local runs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("DB_PATH", "events.db"))
    # Shared secret used to verify inbound webhook signatures.
    webhook_secret: str = field(default_factory=lambda: os.environ.get("WEBHOOK_SECRET", "dev-secret"))
    # Where alerts are delivered. Empty means "store alerts but do not deliver".
    alert_url: str = field(default_factory=lambda: os.environ.get("ALERT_URL", ""))
    speed_limit_kmh: float = field(default_factory=lambda: float(os.environ.get("SPEED_LIMIT_KMH", "110")))
    harsh_event_threshold: int = field(default_factory=lambda: int(os.environ.get("HARSH_EVENT_THRESHOLD", "3")))
    harsh_event_window_minutes: int = field(default_factory=lambda: int(os.environ.get("HARSH_EVENT_WINDOW_MINUTES", "10")))
    # Circular geofence around the depot.
    geofence_lat: float = field(default_factory=lambda: float(os.environ.get("GEOFENCE_LAT", "45.4215")))
    geofence_lon: float = field(default_factory=lambda: float(os.environ.get("GEOFENCE_LON", "-75.6972")))
    geofence_radius_km: float = field(default_factory=lambda: float(os.environ.get("GEOFENCE_RADIUS_KM", "50")))
    delivery_max_attempts: int = field(default_factory=lambda: int(os.environ.get("DELIVERY_MAX_ATTEMPTS", "4")))
    delivery_backoff_seconds: float = field(default_factory=lambda: float(os.environ.get("DELIVERY_BACKOFF_SECONDS", "0.5")))
