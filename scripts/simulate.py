"""Send signed demo events at a running service, so the pipeline can be seen end to end.

    uvicorn app.main:app &
    python scripts/simulate.py --url http://127.0.0.1:8000 --secret dev-secret
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import random
from datetime import datetime, timedelta

import httpx

SCENARIO = [
    ("position", 45.42, -75.70, 60, "normal run inside the geofence"),
    ("position", 45.42, -75.70, 115, "over the limit -> speeding alert"),
    ("harsh_braking", 45.43, -75.71, 70, "harsh 1 of 3"),
    ("harsh_acceleration", 45.44, -75.72, 75, "harsh 2 of 3"),
    ("harsh_cornering", 45.45, -75.73, 72, "harsh 3 of 3 -> harsh_driving alert"),
    ("position", 43.65, -79.38, 95, "now near Toronto -> geofence_exit alert"),
    ("position", 43.60, -79.30, 90, "still outside -> no duplicate alert"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--secret", default="dev-secret")
    parser.add_argument("--vehicle", default="V001")
    args = parser.parse_args()

    clock = datetime(2026, 11, 1, 8, 0, 0)
    run_id = random.randint(1000, 9999)
    with httpx.Client(base_url=args.url, timeout=10.0) as client:
        for i, (event_type, lat, lon, speed, note) in enumerate(SCENARIO, start=1):
            payload = {
                "event_id": f"sim-{run_id}-{i}",
                "vehicle_id": args.vehicle,
                "type": event_type,
                "timestamp": (clock + timedelta(minutes=i)).isoformat(),
                "lat": lat,
                "lon": lon,
                "speed_kmh": float(speed),
            }
            body = json.dumps(payload).encode()
            signature = "sha256=" + hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
            response = client.post(
                "/webhooks/telematics", content=body,
                headers={"X-Signature": signature, "Content-Type": "application/json"},
            )
            result = response.json()
            print(f"{i}. {event_type:<20} {note}")
            print(f"   -> {response.status_code} {result.get('status')}, alerts={result.get('alerts')}")

        # Replay one event to show idempotency.
        print("\nReplaying event 2 to show de-duplication:")
        payload = {
            "event_id": f"sim-{run_id}-2", "vehicle_id": args.vehicle, "type": "position",
            "timestamp": (clock + timedelta(minutes=2)).isoformat(),
            "lat": 45.42, "lon": -75.70, "speed_kmh": 115.0,
        }
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
        print("   ->", client.post("/webhooks/telematics", content=body,
              headers={"X-Signature": signature, "Content-Type": "application/json"}).json())

        print("\nStats:", json.dumps(client.get("/stats").json(), indent=2))
        print("\nAlerts raised:")
        for alert in client.get("/alerts", params={"vehicle_id": args.vehicle}).json():
            print(f"   [{alert['rule']}] {alert['message']} ({alert['delivery_status']})")


if __name__ == "__main__":
    main()
