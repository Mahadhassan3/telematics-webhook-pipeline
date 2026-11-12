from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id   TEXT PRIMARY KEY,
    vehicle_id TEXT NOT NULL,
    type       TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    speed_kmh  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_vehicle_time ON events(vehicle_id, timestamp);
CREATE TABLE IF NOT EXISTS vehicle_state (
    vehicle_id      TEXT PRIMARY KEY,
    inside_geofence INTEGER NOT NULL,
    last_harsh_alert_at TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT NOT NULL,
    rule       TEXT NOT NULL,
    message    TEXT NOT NULL,
    event_id   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivery_status   TEXT NOT NULL DEFAULT 'pending',
    delivery_attempts INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI runs sync handlers and background tasks on a
    # thread pool. A single process with SQLite is fine for a POC; see README for scaling.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
