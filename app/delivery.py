"""Outbound alert delivery with retries and exponential backoff."""

from __future__ import annotations

import sqlite3
import time
from typing import Callable

import httpx

from .config import Settings

RETRYABLE = {408, 429}


def deliver_alert(
    conn: sqlite3.Connection,
    alert_id: int,
    settings: Settings,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """POST one alert to the configured URL. Retries network errors, 5xx, 408 and 429;
    gives up immediately on other 4xx because retrying a bad request cannot succeed.
    Returns the final status: delivered, failed or skipped."""
    row = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    if row is None:
        return "failed"
    if not settings.alert_url:
        _finish(conn, alert_id, "skipped", 0)
        return "skipped"

    payload = {k: row[k] for k in ("alert_id", "vehicle_id", "rule", "message", "event_id", "created_at")}
    own_client = client is None
    client = client or httpx.Client(timeout=5.0)
    status, attempts = "failed", 0
    try:
        for attempt in range(1, settings.delivery_max_attempts + 1):
            attempts = attempt
            try:
                response = client.post(
                    settings.alert_url,
                    json=payload,
                    # Lets the receiver de-duplicate if a retry lands after a slow success.
                    headers={"Idempotency-Key": f"alert-{alert_id}"},
                )
                if response.status_code < 300:
                    status = "delivered"
                    break
                if response.status_code < 500 and response.status_code not in RETRYABLE:
                    break
            except httpx.HTTPError:
                pass
            if attempt < settings.delivery_max_attempts:
                sleep(settings.delivery_backoff_seconds * 2 ** (attempt - 1))
    finally:
        if own_client:
            client.close()
    _finish(conn, alert_id, status, attempts)
    return status


def _finish(conn: sqlite3.Connection, alert_id: int, status: str, attempts: int) -> None:
    conn.execute(
        "UPDATE alerts SET delivery_status = ?, delivery_attempts = ? WHERE alert_id = ?",
        (status, attempts, alert_id),
    )
    conn.commit()
