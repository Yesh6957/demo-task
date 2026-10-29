"""Run with:  pip install pytest httpx  &&  pytest"""
import time

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

import main

client = TestClient(main.app)
KEY = {"X-API-Key": "demo-secret-key"}


def setup_function():                  # runs before every test
    main.recent_calls.clear()
    main.state["healthy"] = True


def count(endpoint, status):
    return REGISTRY.get_sample_value("http_requests_total", {"endpoint": endpoint, "status": str(status)})


def test_health_ok():
    assert client.get("/health").json() == {"status": "healthy"}


def test_users_and_products_with_key():
    assert len(client.get("/users", headers=KEY).json()) == 3
    assert len(client.get("/products", headers=KEY).json()) == 2


def test_auth_failure_returns_401():                     # scenario 1
    assert client.get("/users").status_code == 401                                  # missing key
    assert client.get("/users", headers={"X-API-Key": "wrong"}).status_code == 401  # wrong key


def test_timeout_endpoint_is_slow():                     # scenario 2
    start = time.time()
    assert client.get("/simulate-timeout", params={"delay": 0.3}).status_code == 200
    assert time.time() - start >= 0.3


def test_error_returns_500_and_is_counted():             # scenario 3
    before = count("/simulate-error", 500)
    assert client.get("/simulate-error").status_code == 500
    assert count("/simulate-error", 500) == before + 1


def test_rate_limit_returns_429():                       # scenario 4
    assert [client.get("/simulate-rate-limit").status_code for _ in range(5)] == [200] * 5
    assert client.get("/simulate-rate-limit").status_code == 429


def test_unhealthy_toggle_and_metric():
    client.get("/simulate-unhealthy")
    assert client.get("/health").status_code == 503
    assert "service_health_status 0.0" in client.get("/metrics").text
    client.get("/simulate-unhealthy")
    assert client.get("/health").status_code == 200
