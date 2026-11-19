"""Shared HTTP helpers for the test and load scripts (standard library only, no pip installs needed)."""
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080").rstrip("/")
API = BASE_URL + "/api"

# Demo tokens match the seeded token hashes in db/init/02_seed.sql. For local evaluation only.
TOKENS = {
    "admin": "tok-admin-demo",
    "facmgr": "tok-facmgr-demo",
    "approver": "tok-approver-demo",
    "tech1": "tok-tech1-demo",
    "tech2": "tok-tech2-demo",
    "faculty1": "tok-faculty-demo",
    "student1": "tok-student-demo",
    "sensor-gw": "tok-sensor-demo",
}


def call(method, path, token=None, body=None, key=None):
    """Return (status, parsed_json, response_headers). HTTP error statuses are returned, not raised."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key:
        headers["Idempotency-Key"] = key
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None), response.headers
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = {"raw": raw.decode("utf-8", "replace")}
        return err.code, payload, err.headers
