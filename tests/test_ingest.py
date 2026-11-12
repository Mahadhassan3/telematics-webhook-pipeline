import json

from app.main import sign


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_valid_event_is_accepted_and_stored(post_event, conn):
    response = post_event()
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_unsigned_request_rejected(client):
    response = client.post("/webhooks/telematics", json={"event_id": "x"})
    assert response.status_code == 401


def test_tampered_body_rejected(client, settings):
    body = json.dumps({"event_id": "e1", "vehicle_id": "V001", "type": "position",
                       "timestamp": "2026-11-01T08:00:00", "lat": 45.0, "lon": -75.0,
                       "speed_kmh": 10.0}).encode()
    signature = sign(body, settings.webhook_secret)
    response = client.post("/webhooks/telematics", content=body.replace(b'"speed_kmh": 10.0', b'"speed_kmh": 99.0'),
                           headers={"X-Signature": signature, "Content-Type": "application/json"})
    assert response.status_code == 401


def test_wrong_secret_rejected(client):
    body = json.dumps({"event_id": "e1", "vehicle_id": "V001", "type": "position",
                       "timestamp": "2026-11-01T08:00:00", "lat": 45.0, "lon": -75.0,
                       "speed_kmh": 10.0}).encode()
    response = client.post("/webhooks/telematics", content=body,
                           headers={"X-Signature": sign(body, "wrong"), "Content-Type": "application/json"})
    assert response.status_code == 401


def test_replayed_event_is_idempotent(post_event, conn):
    first = post_event(event_id="dup", speed_kmh=150)
    second = post_event(event_id="dup", speed_kmh=150)
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    # The replay must not raise a second alert for the same event.
    assert conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1


def test_bad_payloads_rejected_with_detail(post_event):
    assert post_event(speed_kmh=-5).status_code == 422
    assert post_event(lat=200).status_code == 422
    assert post_event(type="teleport").status_code == 422
    response = post_event(extra_field="surprise")
    assert response.status_code == 422
    assert response.json()["detail"]


def test_stats_and_alert_filters(post_event, client):
    post_event(speed_kmh=150)
    post_event(vehicle_id="V002", speed_kmh=160)
    stats = client.get("/stats").json()
    assert stats["events"] == 2
    assert stats["alerts_by_rule"]["speeding"] == 2
    assert len(client.get("/alerts", params={"vehicle_id": "V002"}).json()) == 1
    assert client.get("/alerts", params={"rule": "geofence_exit"}).json() == []
