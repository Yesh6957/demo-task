"""Demo REST API with built-in monitoring. Read it top to bottom."""
import asyncio
import logging
import os
import time
import traceback

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("api")

app = FastAPI(title="Monitoring Demo API")

API_KEY = os.getenv("API_KEY", "demo-secret-key")
state = {"healthy": True}      # flipped by /simulate-unhealthy
recent_calls = []              # timestamps used by the rate limiter (one global limit, kept simple)

USERS = [{"id": 1, "name": "Asha"}, {"id": 2, "name": "Ravi"}, {"id": 3, "name": "Meena"}]
PRODUCTS = [{"id": 1, "name": "Keyboard", "price": 49.99}, {"id": 2, "name": "Mouse", "price": 19.99}]

# ---------------------------------------------------------------- metrics
# Prometheus reads these from /metrics every few seconds.
REQUESTS = Counter("http_requests_total", "Requests by endpoint and HTTP status", ["endpoint", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Response time in seconds", ["endpoint"],
                    buckets=[0.1, 0.5, 1, 2, 3, 5, 10])
HEALTH = Gauge("service_health_status", "1 = healthy, 0 = unhealthy")
HEALTH.set_function(lambda: 1 if state["healthy"] else 0)   # evaluated on every scrape


@app.middleware("http")
async def monitor(request: Request, call_next):
    """Runs for EVERY request: counts it, times it, and catches crashes."""
    if request.url.path == "/metrics":          # don't count Prometheus' own scrapes
        return await call_next(request)

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        # One clear line (what + where), followed by the full stack trace = the root cause.
        crash = traceback.extract_tb(error.__traceback__)[-1]
        log.error("Unhandled %s on %s: %s (%s line %d in %s)", type(error).__name__, request.url.path, error,
                  os.path.basename(crash.filename), crash.lineno, crash.name, exc_info=True)
        response = JSONResponse({"detail": "Internal server error"}, status_code=500)

    seconds = time.perf_counter() - start
    route = request.scope.get("route")
    endpoint = route.path if route else "unmatched"
    REQUESTS.labels(endpoint, response.status_code).inc()
    LATENCY.labels(endpoint).observe(seconds)
    if seconds > 3:
        log.warning("Slow response: %s took %.1f seconds", request.url.path, seconds)
    return response


def check_api_key(x_api_key: str | None = Header(default=None)):
    if x_api_key != API_KEY:
        log.warning("Auth failed: %s API key", "missing" if x_api_key is None else "invalid")
        raise HTTPException(401, "Invalid or missing API key")


# -------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    # Add real checks here (database, cache...) and set "unhealthy" if one fails.
    if not state["healthy"]:
        return JSONResponse({"status": "unhealthy"}, status_code=503)
    return {"status": "healthy"}


@app.get("/users", dependencies=[Depends(check_api_key)])
def get_users():
    return USERS


@app.get("/products", dependencies=[Depends(check_api_key)])
def get_products():
    return PRODUCTS


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ------------------------------------------------- failure generators (demo only)
@app.get("/simulate-error")
def simulate_error():
    quantity = 0
    return {"unit_price": 100 / quantity}       # ZeroDivisionError -> HTTP 500


@app.get("/simulate-timeout")
async def simulate_timeout(delay: float = 5):
    await asyncio.sleep(min(delay, 30))         # slow response
    return {"message": f"responded after {delay} seconds"}


@app.get("/simulate-rate-limit")
def simulate_rate_limit():
    now = time.time()
    recent_calls[:] = [t for t in recent_calls if now - t < 30]     # keep the last 30 seconds
    if len(recent_calls) >= 5:
        log.warning("Rate limit exceeded: more than 5 requests in 30 seconds")
        raise HTTPException(429, "Rate limit exceeded: max 5 requests per 30 seconds", headers={"Retry-After": "30"})
    recent_calls.append(now)
    return {"message": "ok"}


@app.get("/simulate-unhealthy")
def simulate_unhealthy():
    """Call once: /health starts failing. Call again: it recovers."""
    state["healthy"] = not state["healthy"]
    log.warning("Health state changed: healthy=%s", state["healthy"])
    return {"healthy": state["healthy"]}


# Create every endpoint/status combination at 0. Without this, Prometheus cannot
# see the very FIRST failure (a counter that appears with value 1 has no "before").
for route in app.routes:
    LATENCY.labels(route.path)
    for status in (200, 401, 429, 500, 503):
        REQUESTS.labels(route.path, status)
