"""Alert rules. Each rule is a pure-ish function of the new event plus stored state,
so a rule can be tested by inserting rows and calling `evaluate`."""

from __future__ import annotations

import math
import sqlite3
from datetime import timedelta

from .config import Settings
from .models import HARSH_TYPES, TelematicsEvent


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def evaluate(conn: sqlite3.Connection, event: TelematicsEvent, settings: Settings) -> list[tuple[str, str]]:
    """Return (rule, message) for every rule the event triggers. The event must
    already be stored, because the harsh-driving rule counts recent events."""
    triggered: list[tuple[str, str]] = []

    if event.speed_kmh > settings.speed_limit_kmh:
        triggered.append((
            "speeding",
            f"{event.vehicle_id} at {event.speed_kmh:.0f} km/h (limit {settings.speed_limit_kmh:.0f})",
        ))

    state = conn.execute("SELECT * FROM vehicle_state WHERE vehicle_id = ?", (event.vehicle_id,)).fetchone()

    # Geofence: alert only on the inside -> outside transition, never on every ping outside.
    distance = haversine_km(event.lat, event.lon, settings.geofence_lat, settings.geofence_lon)
    inside = distance <= settings.geofence_radius_km
    was_inside = True if state is None else bool(state["inside_geofence"])
    if was_inside and not inside:
        triggered.append((
            "geofence_exit",
            f"{event.vehicle_id} left the geofence ({distance:.0f} km from depot, radius "
            f"{settings.geofence_radius_km:.0f} km)",
        ))

    # Harsh driving: N harsh events inside a rolling window, with a cooldown of one
    # window so a single bad stretch produces one alert instead of one per event.
    last_harsh_alert = state["last_harsh_alert_at"] if state else None
    if event.type in HARSH_TYPES:
        window = timedelta(minutes=settings.harsh_event_window_minutes)
        window_start = (event.timestamp - window).isoformat()
        placeholders = ",".join("?" * len(HARSH_TYPES))
        count = conn.execute(
            f"SELECT COUNT(*) FROM events WHERE vehicle_id = ? AND type IN ({placeholders})"
            " AND timestamp > ? AND timestamp <= ?",
            (event.vehicle_id, *sorted(HARSH_TYPES), window_start, event.timestamp.isoformat()),
        ).fetchone()[0]
        cooling_down = last_harsh_alert is not None and last_harsh_alert > window_start
        if count >= settings.harsh_event_threshold and not cooling_down:
            triggered.append((
                "harsh_driving",
                f"{event.vehicle_id}: {count} harsh events in {settings.harsh_event_window_minutes} minutes",
            ))
            last_harsh_alert = event.timestamp.isoformat()

    conn.execute(
        "INSERT INTO vehicle_state (vehicle_id, inside_geofence, last_harsh_alert_at) VALUES (?, ?, ?)"
        " ON CONFLICT(vehicle_id) DO UPDATE SET inside_geofence = excluded.inside_geofence,"
        " last_harsh_alert_at = excluded.last_harsh_alert_at",
        (event.vehicle_id, int(inside), last_harsh_alert),
    )
    return triggered
