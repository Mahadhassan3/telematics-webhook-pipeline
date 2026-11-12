import httpx
import pytest

from app import delivery
from app.config import Settings
from dataclasses import replace


@pytest.fixture()
def alert_id(conn):
    cur = conn.execute(
        "INSERT INTO alerts (vehicle_id, rule, message, event_id, created_at)"
        " VALUES ('V001', 'speeding', 'too fast', 'e1', '2026-11-01T08:00:00')"
    )
    conn.commit()
    return cur.lastrowid


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://alerts.test")


def status_of(conn, alert_id):
    row = conn.execute("SELECT delivery_status, delivery_attempts FROM alerts WHERE alert_id = ?",
                       (alert_id,)).fetchone()
    return row["delivery_status"], row["delivery_attempts"]


def test_no_alert_url_means_skipped(conn, settings, alert_id):
    assert delivery.deliver_alert(conn, alert_id, settings) == "skipped"
    assert status_of(conn, alert_id) == ("skipped", 0)


def test_successful_delivery_sends_payload_and_idempotency_key(conn, settings, alert_id):
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("Idempotency-Key")
        seen["body"] = request.read()
        return httpx.Response(200)

    s = replace(settings, alert_url="https://alerts.test/hook")
    assert delivery.deliver_alert(conn, alert_id, s, client=client_for(handler)) == "delivered"
    assert status_of(conn, alert_id) == ("delivered", 1)
    assert seen["key"] == f"alert-{alert_id}"
    assert b"too fast" in seen["body"]


def test_retries_server_error_then_succeeds(conn, settings, alert_id):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200 if calls["n"] == 3 else 503)

    s = replace(settings, alert_url="https://alerts.test/hook")
    assert delivery.deliver_alert(conn, alert_id, s, client=client_for(handler), sleep=lambda _: None) == "delivered"
    assert status_of(conn, alert_id) == ("delivered", 3)


def test_gives_up_after_max_attempts(conn, settings, alert_id):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500)

    s = replace(settings, alert_url="https://alerts.test/hook", delivery_max_attempts=3)
    assert delivery.deliver_alert(conn, alert_id, s, client=client_for(handler), sleep=lambda _: None) == "failed"
    assert calls["n"] == 3
    assert status_of(conn, alert_id) == ("failed", 3)


def test_client_error_is_not_retried(conn, settings, alert_id):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400)

    s = replace(settings, alert_url="https://alerts.test/hook")
    assert delivery.deliver_alert(conn, alert_id, s, client=client_for(handler), sleep=lambda _: None) == "failed"
    assert calls["n"] == 1


def test_rate_limit_is_retried(conn, settings, alert_id):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200 if calls["n"] == 2 else 429)

    s = replace(settings, alert_url="https://alerts.test/hook")
    assert delivery.deliver_alert(conn, alert_id, s, client=client_for(handler), sleep=lambda _: None) == "delivered"
    assert calls["n"] == 2


def test_network_error_is_retried(conn, settings, alert_id):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("boom")
        return httpx.Response(200)

    s = replace(settings, alert_url="https://alerts.test/hook")
    assert delivery.deliver_alert(conn, alert_id, s, client=client_for(handler), sleep=lambda _: None) == "delivered"


def test_backoff_is_exponential(conn, settings, alert_id):
    waits = []
    s = replace(settings, alert_url="https://alerts.test/hook", delivery_backoff_seconds=1.0,
                delivery_max_attempts=4)
    delivery.deliver_alert(conn, alert_id, s, client=client_for(lambda r: httpx.Response(500)),
                           sleep=waits.append)
    assert waits == [1.0, 2.0, 4.0]
