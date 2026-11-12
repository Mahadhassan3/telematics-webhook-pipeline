import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import Settings
from app.main import create_app, sign


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "events.db"),
        webhook_secret="test-secret",
        alert_url="",
        speed_limit_kmh=110,
        harsh_event_threshold=3,
        harsh_event_window_minutes=10,
        geofence_lat=45.4215,
        geofence_lon=-75.6972,
        geofence_radius_km=50,
        delivery_max_attempts=4,
        delivery_backoff_seconds=0.0,
    )


@pytest.fixture()
def conn(settings):
    c = db.connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture()
def client(settings, conn):
    with TestClient(create_app(settings, conn)) as c:
        yield c


@pytest.fixture()
def post_event(client, settings):
    """Post a signed event, filling in sensible defaults."""
    counter = {"n": 0}

    def _post(**overrides):
        counter["n"] += 1
        payload = {
            "event_id": f"e{counter['n']}",
            "vehicle_id": "V001",
            "type": "position",
            "timestamp": "2026-11-01T08:00:00",
            "lat": 45.42,
            "lon": -75.70,
            "speed_kmh": 60.0,
        }
        payload.update(overrides)
        body = __import__("json").dumps(payload).encode()
        return client.post(
            "/webhooks/telematics", content=body,
            headers={"X-Signature": sign(body, settings.webhook_secret), "Content-Type": "application/json"},
        )

    return _post
