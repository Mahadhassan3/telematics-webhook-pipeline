"""Webhook ingestion service: verify, validate, de-duplicate, store, evaluate rules, alert."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from pydantic import ValidationError

from . import db, delivery, rules
from .config import Settings
from .models import Alert, TelematicsEvent


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def create_app(settings: Settings | None = None, conn: sqlite3.Connection | None = None) -> FastAPI:
    settings = settings or Settings()
    conn = conn or db.connect(settings.db_path)
    app = FastAPI(title="Telematics webhook pipeline", version="0.1.0")
    app.state.settings, app.state.conn = settings, conn

    @app.get("/health")
    def health() -> dict:
        conn.execute("SELECT 1")
        return {"status": "ok"}

    @app.post("/webhooks/telematics", status_code=202)
    async def ingest(
        request: Request,
        background: BackgroundTasks,
        x_signature: str | None = Header(default=None),
    ) -> dict:
        body = await request.body()
        # Verify against the raw bytes before parsing anything the sender controls.
        if not x_signature or not hmac.compare_digest(x_signature, sign(body, settings.webhook_secret)):
            raise HTTPException(status_code=401, detail="Invalid or missing signature")
        try:
            event = TelematicsEvent.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_input=False))

        # INSERT OR IGNORE on the primary key makes ingestion idempotent: senders
        # retry, and a duplicate must not double-count or re-alert.
        inserted = conn.execute(
            "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event.event_id, event.vehicle_id, event.type, event.timestamp.isoformat(),
             event.lat, event.lon, event.speed_kmh),
        ).rowcount
        if not inserted:
            conn.commit()
            return {"status": "duplicate", "event_id": event.event_id, "alerts": []}

        alert_ids = []
        now = datetime.now(timezone.utc).isoformat()
        for rule, message in rules.evaluate(conn, event, settings):
            cur = conn.execute(
                "INSERT INTO alerts (vehicle_id, rule, message, event_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (event.vehicle_id, rule, message, event.event_id, now),
            )
            alert_ids.append(cur.lastrowid)
        conn.commit()

        # Respond to the sender first; deliver alerts afterwards so a slow
        # downstream system never makes the gateway time out and retry.
        for alert_id in alert_ids:
            background.add_task(delivery.deliver_alert, conn, alert_id, settings)
        return {"status": "accepted", "event_id": event.event_id, "alerts": alert_ids}

    @app.get("/alerts", response_model=list[Alert])
    def list_alerts(vehicle_id: str | None = None, rule: str | None = None, limit: int = 50) -> list[dict]:
        sql, params = "SELECT * FROM alerts WHERE 1=1", []
        if vehicle_id:
            sql += " AND vehicle_id = ?"
            params.append(vehicle_id)
        if rule:
            sql += " AND rule = ?"
            params.append(rule)
        params.append(max(1, min(limit, 500)))
        return [dict(r) for r in conn.execute(sql + " ORDER BY alert_id DESC LIMIT ?", params)]

    @app.get("/stats")
    def stats() -> dict:
        return {
            "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "alerts_by_rule": {r[0]: r[1] for r in conn.execute("SELECT rule, COUNT(*) FROM alerts GROUP BY rule")},
            "alerts_by_delivery_status": {
                r[0]: r[1] for r in conn.execute("SELECT delivery_status, COUNT(*) FROM alerts GROUP BY delivery_status")
            },
        }

    return app


app = create_app()
