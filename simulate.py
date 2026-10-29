"""Generate traffic and failures against the API (no extra packages needed).

    python simulate.py traffic     # healthy traffic (baseline)
    python simulate.py auth        # scenario 1: invalid authentication  -> 401
    python simulate.py timeout     # scenario 2: slow responses          -> 4 s each
    python simulate.py error       # scenario 3: server error            -> 500
    python simulate.py ratelimit   # scenario 4: rate limit              -> 429
    python simulate.py health      # health check failure                -> 503 for 30 s
    python simulate.py all         # all of the above, 70 s apart
"""
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
KEY = "demo-secret-key"


def get(path, key=None):
    """Call the API, return (status_code, seconds taken)."""
    request = urllib.request.Request(BASE + path, headers={"X-API-Key": key} if key else {})
    start = time.time()
    try:
        status = urllib.request.urlopen(request, timeout=30).status
    except urllib.error.HTTPError as error:        # 401, 429, 500... are normal results here
        status = error.code
    return status, time.time() - start


def traffic():
    print("Healthy traffic: 30 requests")
    codes = []
    for i in range(30):
        codes.append(get(["/health", "/users", "/products"][i % 3], KEY)[0])
        time.sleep(0.2)
    print("  statuses:", codes)


def auth():
    print("Scenario 1 - invalid authentication: 6 calls to /users (no key / wrong key)")
    print("  statuses:", [get("/users", key)[0] for key in [None, "wrong"] * 3])


def timeout():
    print("Scenario 2 - timeout: 3 calls that each take 4 seconds")
    for _ in range(3):
        status, seconds = get("/simulate-timeout?delay=4")
        print(f"  status {status} after {seconds:.1f}s")


def error():
    print("Scenario 3 - server error: 3 calls to /simulate-error")
    print("  statuses:", [get("/simulate-error")[0] for _ in range(3)])


def ratelimit():
    print("Scenario 4 - rate limit: 12 quick calls (limit is 5 per 30 seconds)")
    print("  statuses:", [get("/simulate-rate-limit")[0] for _ in range(12)])


def health():
    print("Health failure: /health returns 503 for 30 seconds, then recovers")
    get("/simulate-unhealthy")
    print("  /health ->", get("/health")[0])
    time.sleep(30)
    get("/simulate-unhealthy")
    print("  recovered: /health ->", get("/health")[0])


SCENARIOS = {"traffic": traffic, "auth": auth, "timeout": timeout, "error": error, "ratelimit": ratelimit, "health": health}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name == "all":
        for i, scenario in enumerate(SCENARIOS.values()):
            if i:
                print("\n(waiting 70s so the previous alert clears)\n")
                time.sleep(70)
            scenario()
    elif name in SCENARIOS:
        SCENARIOS[name]()
    else:
        print(__doc__)
