# API Monitoring Demo: FastAPI + Prometheus + Grafana

A small FastAPI service with complete monitoring: **health, response time, error tracking, dashboard, alerts (Slack / Email) and root cause analysis.**

```
simulate.py ──▶ FastAPI :8000 ──/metrics──▶ Prometheus :9090 ──▶ Grafana :3000   (dashboard)
 (traffic +        │   (every 5s)               │ alert rules
  failures)        │ logs                       ▼
                   ▼                       Alertmanager :9093 ──▶ Slack · Email · (phone)
        docker compose logs api   (root cause)
```

## Run it

```bash
docker compose up --build -d
python simulate.py traffic        # healthy traffic, so the dashboard has data
python simulate.py error          # break something and watch the dashboard and alerts
```

| What | URL |
|---|---|
| API (Swagger docs) | http://localhost:8000/docs |
| **Dashboard** (login `admin` / `admin` → *API Monitoring*) | http://localhost:3000 |
| Alert states | http://localhost:9090/alerts |
| Alertmanager | http://localhost:9093 |

---

## 1. FastAPI setup

Without Docker:
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --port 8000
pip install pytest httpx && pytest                     # 7 tests (optional)
```
The whole API is one file: **`main.py`** (about 125 lines).

| Endpoint | Behaviour |
|---|---|
| `GET /health` | `200 healthy`, or `503 unhealthy` |
| `GET /users`, `GET /products` | sample data. Needs header `X-API-Key: demo-secret-key`, otherwise **401** |
| `GET /simulate-error` | crashes on purpose → **500** |
| `GET /simulate-timeout?delay=5` | answers after `delay` seconds |
| `GET /simulate-rate-limit` | 5 calls per 30 s, then **429** |
| `GET /simulate-unhealthy` | call once: `/health` fails. Call again: recovers |
| `GET /metrics` | numbers for Prometheus |

## 2. Monitoring architecture

There is no custom monitoring code. The API only publishes numbers at `/metrics`; the tools do the rest.

- **FastAPI** counts and times every request in one middleware.
- **Prometheus** reads `/metrics` every 5 s, keeps the history and checks the alert rules.
- **Alertmanager** sends firing alerts to Slack and Email.
- **Grafana** draws the dashboard (loaded automatically from `monitoring/`).

| Brief asks to monitor | Measured by |
|---|---|
| API availability | `up` (can Prometheus reach the API?) |
| Response time | `http_request_duration_seconds` |
| HTTP status codes, failed requests, error % | `http_requests_total{endpoint, status}` |
| Server health | `service_health_status` (from `/health`) + CPU and memory (`process_*`) |

## 3. Dashboard (Grafana → *API Monitoring*)

| Panel | Shows |
|---|---|
| API status, Health check | UP/DOWN and HEALTHY/UNHEALTHY right now |
| Uptime % | availability in the selected time range |
| Avg response time | mean response time |
| Total requests, Failed requests, Error % | counts since the API started |
| Requests per second by status code | traffic mix |
| Failure rate % | **error trend** (red line = alert limit 20 %) |
| p95 response time by endpoint | **which** endpoint is slow (red line = 3 s) |
| Failures by endpoint & status | **where** it fails and **what** code (401, 429, 500) |
| Server CPU, Server memory | server health |

## 4. Alert rules and notifications

Rules are in `monitoring/alert_rules.yml`. The `for:` times are short so the demo reacts fast (production: 1–5 minutes).

| Alert | Fires when | Brief requirement |
|---|---|---|
| `APIDown` | API unreachable for 15 s | API downtime |
| `HighResponseTime` | p95 response time of an endpoint > 3 s | response time > 3 s |
| `Http500Errors` | any HTTP 500 in the last minute | HTTP 500 errors |
| `HighFailureRate` | more than 20 % of requests are 4xx/5xx | increased failure rate |
| `ServiceUnhealthy` | `/health` failing | service health failure |
| `AuthFailuresSpike` | more than 3 × HTTP 401 in a minute | scenario 1 |
| `RateLimitExceeded` | more than 3 × HTTP 429 in a minute | scenario 4 |

Each alert message tells you what is wrong and which command to run next.

**Slack** (3 minutes): Slack → Apps → *Incoming Webhooks* → add to a channel → copy the URL → paste it as `api_url` in `monitoring/alertmanager.yml`.
**Email** (Gmail): Google account → Security → *App passwords* → create one → fill the `smtp_*` lines and `to:` in the same file.
**Phone call** (optional): uncomment the `pagerduty_configs` block and add a PagerDuty key (PagerDuty phones the on-call person).

Apply and test:
```bash
docker compose restart alertmanager
curl -XPOST localhost:9093/api/v2/alerts -H 'Content-Type: application/json' \
  -d '[{"labels":{"alertname":"TestAlert","severity":"critical"},"annotations":{"summary":"Test","description":"Testing Slack and Email"}}]'
```
Slack and email messages arrive after about 15 seconds. Until you add real credentials, alerts are still visible at http://localhost:9090/alerts.

## 5. Failure simulation and root cause analysis

Run one at a time and wait about a minute between them (or `python simulate.py all`, about 7 minutes). Open the dashboard while it runs.

| Scenario | Command | Alert | Root cause |
|---|---|---|---|
| 1. Invalid authentication | `python simulate.py auth` | `AuthFailuresSpike` | `docker compose logs api \| grep "Auth failed"` shows *missing* vs *invalid* key |
| 2. API timeout | `python simulate.py timeout` | `HighResponseTime` (names the endpoint) | `docker compose logs api \| grep Slow` |
| 3. Server error | `python simulate.py error` | `Http500Errors` | `docker compose logs api \| grep ERROR` |
| 4. Rate limit | `python simulate.py ratelimit` | `RateLimitExceeded` | `docker compose logs api \| grep "Rate limit"` |
| Health failure | `python simulate.py health` | `ServiceUnhealthy` | `curl localhost:8000/health` |
| Downtime | `docker compose stop api` (then `start api`) | `APIDown` | `docker compose ps`, `docker compose logs api` |

Example, scenario 3. The `ERROR` line says what crashed and where, and the full stack trace follows it:
```
ERROR Unhandled ZeroDivisionError on /simulate-error: division by zero (main.py line 93 in simulate_error)
```
Real results of every scenario are in [`TEST_RESULTS.md`](TEST_RESULTS.md).

## 6. Troubleshooting guide

| Alert | First check | Usual cause → fix |
|---|---|---|
| `APIDown` | `docker compose ps`, `docker compose logs api`, http://localhost:9090/targets | container crashed or stopped → `docker compose up -d api` |
| `HighResponseTime` | dashboard *p95 by endpoint* (which endpoint?), `grep Slow` in logs | slow query or external call in that endpoint; high CPU/memory |
| `Http500Errors` | `grep ERROR` in logs → file, line and stack trace | a bug → fix the code, add a test |
| `HighFailureRate` | dashboard *Failures by endpoint & status* | 401 = auth, 429 = rate limit, 500 = bug, 503 = health. Follow that one. |
| `ServiceUnhealthy` | `curl localhost:8000/health` | a dependency is down. In the demo: call `/simulate-unhealthy` again |
| `AuthFailuresSpike` | `grep "Auth failed"`: missing or invalid? | client has no key or an old key → fix the client |
| `RateLimitExceeded` | `grep "Rate limit"` | a client retries too fast → it should wait (`Retry-After` header) |

The monitoring stack itself:

| Problem | Check |
|---|---|
| Dashboard says "No data" | Prometheus up? http://localhost:9090/targets must show the API as **UP**. Is the time range too short? |
| Alert on `/alerts` page but no Slack/Email | Open http://localhost:9093 (is it listed?), then `docker compose logs alertmanager \| grep -i fail` (wrong webhook URL, or Gmail needs an *App password*) |
| Changed a config file, nothing happened | `docker compose restart prometheus` (or `alertmanager`) |
| Check a config for typos | `docker compose exec prometheus promtool check rules /etc/prometheus/alert_rules.yml` |

## 7. Maintenance process

- **Weekly:** look at which alerts fired. Tune or remove noisy ones. An alert nobody trusts is worse than none.
- **Monthly:** send the test alert (section 4) to prove Slack/Email still work. Rotate the API key, Slack webhook and email password.
- **Quarterly:** update the image versions in `docker-compose.yml` and the packages in `requirements.txt`, then run `pytest` and the scenarios again.
- **Changing an alert or panel:** edit the file → restart that service → run the matching scenario to prove it still fires.
- **Planned maintenance:** silence alerts in the Alertmanager UI (*Silences → New*) instead of deleting rules.
- **Before using for a real API:** remove the `/simulate-*` endpoints, set a real `API_KEY` environment variable (and use proper authentication), keep `/metrics` and Prometheus off the internet, change the Grafana password, use the longer `for:` times, and run one uvicorn worker (several workers need Prometheus multiprocess mode).

## Deliverables

| Deliverable | Where |
|---|---|
| FastAPI source code | `main.py`, `test_main.py`, `simulate.py` |
| Monitoring setup | `monitoring/`, `docker-compose.yml` |
| Dashboard screenshots / video | take them on your machine: run `python simulate.py all` with the dashboard open and record the screen |
| Alert notification proof | screenshots of Slack and email (after adding your credentials), plus http://localhost:9090/alerts |
| Failure testing results | [`TEST_RESULTS.md`](TEST_RESULTS.md) |
| Documentation | this file |
