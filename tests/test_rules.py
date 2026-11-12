import pytest

from app.rules import haversine_km


def alerts(conn, rule=None):
    sql = "SELECT * FROM alerts" + (" WHERE rule = ?" if rule else "")
    return conn.execute(sql, (rule,) if rule else ()).fetchall()


def test_haversine_matches_known_distance():
    # Ottawa to Toronto is about 350 km great-circle.
    assert haversine_km(45.4215, -75.6972, 43.6532, -79.3832) == pytest.approx(350, abs=10)


def test_speeding_rule_boundary(post_event, conn):
    post_event(speed_kmh=110)      # at the limit: no alert
    post_event(speed_kmh=110.5)    # over it: alert
    rows = alerts(conn, "speeding")
    assert len(rows) == 1
    assert "110" in rows[0]["message"]


def test_geofence_alerts_once_on_exit_and_rearms_on_return(post_event, conn):
    post_event(lat=45.42, lon=-75.70)   # inside
    post_event(lat=43.65, lon=-79.38)   # exit -> one alert
    post_event(lat=43.60, lon=-79.30)   # still outside -> no new alert
    assert len(alerts(conn, "geofence_exit")) == 1
    post_event(lat=45.42, lon=-75.70)   # back inside
    post_event(lat=43.65, lon=-79.38)   # exit again -> second alert
    assert len(alerts(conn, "geofence_exit")) == 2


def test_harsh_driving_needs_threshold_within_window(post_event, conn):
    for i in range(2):
        post_event(type="harsh_braking", timestamp=f"2026-11-01T08:0{i}:00")
    assert alerts(conn, "harsh_driving") == []
    post_event(type="harsh_cornering", timestamp="2026-11-01T08:02:00")
    assert len(alerts(conn, "harsh_driving")) == 1


def test_harsh_events_spread_out_do_not_alert(post_event, conn):
    for hour in (8, 9, 10):
        post_event(type="harsh_braking", timestamp=f"2026-11-01T{hour}:00:00")
    assert alerts(conn, "harsh_driving") == []


def test_harsh_alert_has_cooldown(post_event, conn):
    for i in range(6):
        post_event(type="harsh_braking", timestamp=f"2026-11-01T08:0{i}:00")
    # Six harsh events in six minutes is one bad stretch, so one alert, not four.
    assert len(alerts(conn, "harsh_driving")) == 1
    for i in range(3):
        post_event(type="harsh_braking", timestamp=f"2026-11-01T09:0{i}:00")
    assert len(alerts(conn, "harsh_driving")) == 2


def test_harsh_rule_is_per_vehicle(post_event, conn):
    for i in range(2):
        post_event(type="harsh_braking", vehicle_id="V001", timestamp=f"2026-11-01T08:0{i}:00")
    post_event(type="harsh_braking", vehicle_id="V002", timestamp="2026-11-01T08:02:00")
    assert alerts(conn, "harsh_driving") == []


def test_one_event_can_trigger_two_rules(post_event, conn):
    post_event(lat=43.65, lon=-79.38, speed_kmh=150)
    assert {r["rule"] for r in alerts(conn)} == {"speeding", "geofence_exit"}
