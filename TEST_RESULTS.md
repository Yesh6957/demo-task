# Failure Testing Results

## What was tested

Everything below was captured from a real run of the files in this repository: the API, Prometheus 2.53.0 and Alertmanager 0.27.0 running together (`python simulate.py all`, then a real process kill for downtime).

| Check | Result |
|---|---|
| `pytest` | 7 passed |
| `promtool check rules` | 7 rules, SUCCESS |
| `amtool check-config` | SUCCESS |
| Dashboard | all 13 panel queries evaluated against live data, 0 errors |
| Alert pipeline | every scenario below: failure → Prometheus alert → Alertmanager notification (FIRING and RESOLVED) |

**Not covered here, so please do these on your machine:**
- `docker compose up`. The test used the same config files with local processes (host names `api` and `alertmanager` replaced by `localhost`).
- Grafana's screen rendering. The queries are verified, so take the screenshots yourself.
- Real Slack and email delivery, because they need your credentials. In this test Alertmanager's notifications went to a temporary local webhook (same message content, delivered by the same Alertmanager).

All times are UTC.

## Results

| # | Scenario | What the API returned | Alert fired (Prometheus) | Notification sent | Resolved |
|---|---|---|---|---|---|
| 1 | Invalid authentication | `401` × 6 | `AuthFailuresSpike` 09:08:50, `HighFailureRate` 09:09:06 | 09:09:00 and 09:09:15 | 09:10:00 |
| 2 | API timeout | `200` after 4.0 s × 3 | `HighResponseTime` 09:10:20 | 09:10:30 | 09:11:30 |
| 3 | Server error | `500` × 3 | `Http500Errors` 09:11:27 (critical), `HighFailureRate` 09:11:41 | 09:11:35 and 09:11:50 | 09:12:35 |
| 4 | Rate limit | `200` × 5, then `429` × 7 | `RateLimitExceeded` 09:12:37 | 09:12:45 | 09:13:45 |
| 5 | Health failure | `/health` → `503` for 30 s | `ServiceUnhealthy` 09:14:01 (critical) | 09:14:10 | 09:15:10 |
| 6 | Downtime (process killed 09:16:33) | connection refused | `APIDown` 09:16:51 (critical) | 09:17:00 (**27 s after the kill**) | 09:18:00 (after restart) |

## Root cause information per scenario

**1. Authentication.** The alert says *"6 HTTP 401 responses in the last minute: wrong or missing API key"*. The log separates the two causes:
```
WARNING Auth failed: missing API key
WARNING Auth failed: invalid API key
```

**2. Timeout.** The alert names the endpoint: *"p95 response time of /simulate-timeout is 4.9s (limit 3s)"*. The log:
```
WARNING Slow response: /simulate-timeout took 4.0 seconds
```
Only this alert fired: the responses were `200`, and slow is not the same as failing.

**3. Server error.** The alert says *"3 server error(s) on /simulate-error in the last minute"*. `docker compose logs api | grep ERROR` gives one line that names the exception, the endpoint, the file and the line:
```
ERROR Unhandled ZeroDivisionError on /simulate-error: division by zero (main.py line 93 in simulate_error)
```
The full stack trace follows that line in the logs. **Root cause:** `simulate_error` divides by `quantity`, which is `0`. **Fix:** validate the input, return a 4xx for bad data, and add a test. The caller only receives a generic `500 Internal server error`.

**4. Rate limit.** The alert says *"7 HTTP 429 responses in the last minute: a client sends too many requests"*, and the log has `WARNING Rate limit exceeded: more than 5 requests in 30 seconds`. The `429` response includes a `Retry-After` header.

**5. Health failure.** `/health` returns `503 {"status":"unhealthy"}` and the *Health check* panel turns red.

**6. Downtime.** While the API was down: `up = 0` (the *API status* panel shows DOWN) and *Uptime %* fell to 91.6 %. The alert text points to `docker compose ps` and `docker compose logs api`.

## Issues found during testing (and fixed)

1. **Notifications were late or missing.** After simplifying the Alertmanager config, RESOLVED messages and repeat alerts were held back, because Alertmanager's default `group_interval` is 5 minutes. **Fix:** `group_interval: 1m`. Re-run: every alert above produced both FIRING and RESOLVED messages within about a minute.
2. **Root cause was buried.** The first version's stack trace put the application's own line about 25 lines below the framework frames, out of reach of a simple `grep -A25 ERROR`. **Fix:** one `ERROR` line with exception, endpoint, file and line (shown in scenario 3), with the full trace after it.

## Behaviour worth knowing

- `HighFailureRate` joins several scenarios because the demo has almost no background traffic: a few failures are "100 %". With real traffic it only fires when failures are a real share of requests.
- Alertmanager groups messages by alert name. If an alert fires, clears and fires again inside one `group_interval`, the repeat can be merged into the previous message. This happened to `HighFailureRate` in scenario 4 (the specific `RateLimitExceeded` alert was still delivered).
