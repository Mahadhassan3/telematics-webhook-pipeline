# telematics-webhook-pipeline

A production-shaped webhook ingestion service: it receives vehicle telematics events,
verifies they really came from the sender, validates and de-duplicates them, evaluates
alert rules, and delivers alerts downstream with retries.

> Events are **simulated**. This is a personal project showing how I build the integration
> layer between a customer's system and ours. It contains no employer or customer data.

## Why I built it

Most integration work in the field is not the happy path. It is the duplicate the gateway
sent twice, the downstream endpoint that was down for ten minutes, the alert that fired
forty times for one bad stretch of driving, and the sender whose payload changed without
telling anyone. This service is built around those four problems.

## What it does

```
vehicle gateway
   │  POST /webhooks/telematics   (HMAC-SHA256 signature)
   ▼
verify signature ──► 401
validate payload ──► 422 with field-level detail
de-duplicate on event_id ──► 202 {"status": "duplicate"}
   ▼
store event ──► evaluate rules ──► persist alerts ──► 202 accepted
                                        │
                                        ▼ background
                           deliver with retry + exponential backoff
```

| Endpoint | Purpose |
| --- | --- |
| `POST /webhooks/telematics` | Ingest one event |
| `GET /alerts` | Alerts, filterable by vehicle and rule |
| `GET /stats` | Event count, alerts by rule, alerts by delivery status |
| `GET /health` | Liveness, including a database check |

### Alert rules

- **Speeding** — speed above the configured limit.
- **Geofence exit** — fires on the inside-to-outside transition only, and re-arms when the
  vehicle returns, so a vehicle parked outside the fence does not alert on every ping.
- **Harsh driving** — N harsh events within a rolling window, per vehicle, with a cooldown
  of one window so one bad stretch of driving produces one alert instead of ten.

## Engineering decisions

- **Signature checked against raw bytes** before any parsing, with `hmac.compare_digest`.
- **Ingestion is idempotent.** `event_id` is the primary key and inserts use
  `INSERT OR IGNORE`, so a sender retrying cannot double-count an event or raise a second
  alert. The duplicate returns 202, not an error, because it is not the sender's fault.
- **Unknown payload fields are rejected** (`extra="forbid"`). Silent schema drift from a
  sender is the kind of bug that is found three weeks later in a reconciliation meeting.
- **Validation errors return field-level detail**, which is what the integrating team needs
  to fix their payload without a support ticket.
- **Delivery happens after the response.** A slow downstream system must not make the
  gateway time out and retry, which would amplify load exactly when things are breaking.
- **Retries distinguish retryable from permanent.** Network errors, 5xx, 408 and 429 are
  retried with exponential backoff; other 4xx fail immediately, because a malformed request
  will not succeed on the fourth attempt. Every outbound call carries an idempotency key.
- **Delivery state is persisted** (`pending`, `delivered`, `failed`, `skipped`) with an
  attempt count, so failures are visible in `/stats` rather than lost in logs.
- **Rules and delivery are pure functions over a connection**, which is why the tests can
  cover cooldowns and backoff timing without a network or a clock.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                    # 24 tests

export WEBHOOK_SECRET=dev-secret
uvicorn app.main:app --reload &
python scripts/simulate.py                   # drives the whole pipeline and prints alerts
```

With Docker:

```bash
docker build -t telematics-pipeline .
docker run -p 8000:8000 -e WEBHOOK_SECRET=dev-secret telematics-pipeline
```

Interactive API docs are at `http://127.0.0.1:8000/docs`.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `WEBHOOK_SECRET` | `dev-secret` | Shared secret for inbound signatures |
| `ALERT_URL` | *(empty)* | Where alerts are POSTed; empty marks them `skipped` |
| `DB_PATH` | `events.db` | SQLite file |
| `SPEED_LIMIT_KMH` | `110` | Speeding threshold |
| `HARSH_EVENT_THRESHOLD` | `3` | Harsh events needed to alert |
| `HARSH_EVENT_WINDOW_MINUTES` | `10` | Rolling window and cooldown |
| `GEOFENCE_LAT` / `GEOFENCE_LON` / `GEOFENCE_RADIUS_KM` | Ottawa, 50 km | Depot geofence |
| `DELIVERY_MAX_ATTEMPTS` | `4` | Attempts before giving up |
| `DELIVERY_BACKOFF_SECONDS` | `0.5` | Base delay, doubled each attempt |

## Tests

24 tests covering signature rejection and body tampering, replay de-duplication, each
validation failure, every rule including its boundaries and cooldown, two rules firing on
one event, and delivery behaviour: success, retry-then-succeed, give-up, non-retryable 4xx,
rate limiting, network failure, and the exact backoff sequence.

## Limits and next steps

Single process with SQLite and in-process background tasks, which suits a POC. For
production: Postgres, a real queue for delivery, a dead-letter queue for exhausted alerts,
rotating signing keys, and per-sender rate limits.

## License

MIT
