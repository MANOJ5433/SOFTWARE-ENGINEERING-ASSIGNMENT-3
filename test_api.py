"""Functional and robustness checks for the running API.

Run:  BASE_URL=http://localhost:8080 python scripts/test_api.py
Every check is executed against the live service. Nothing here is pre-recorded.
Exit code 0 only when every check passes.
"""
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from common import API, TOKENS, call

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def fresh_slot(hours=1):
    """Unique future slot per run so repeated runs never collide with earlier test data."""
    base = datetime(2027, 1, 4, tzinfo=timezone.utc) + timedelta(hours=random.randint(0, 20000))
    return base.isoformat(), (base + timedelta(hours=hours)).isoformat()


def facility_id(code):
    _, body, _ = call("GET", "/facilities", TOKENS["student1"])
    return next(f["id"] for f in body["items"] if f["code"] == code)


def main():
    run = random.randint(100000, 999999)
    print(f"Smart Campus API checks, run id {run}, target {API}")

    # --- Health, authentication and identity ---
    status, body, _ = call("GET", "/health")
    check("health endpoint reports database ok", status == 200 and body.get("database") == "ok", str(body))
    check("instance name is reported", bool(body and body.get("instance")), str(body and body.get("instance")))
    status, body, _ = call("GET", "/facilities")
    check("request without token is rejected with 401", status == 401 and body["error"]["code"] == "UNAUTHENTICATED")
    status, body, _ = call("GET", "/facilities", "tok-not-a-real-token")
    check("unknown token is rejected with 401", status == 401)
    status, body, _ = call("GET", "/me", TOKENS["faculty1"])
    check("/me returns the authenticated identity", status == 200 and body["role"] == "faculty", str(body))

    # --- Facilities ---
    status, body, _ = call("GET", "/facilities", TOKENS["student1"])
    codes = [f["code"] for f in body["items"]]
    check("facility catalogue lists seeded facilities", status == 200 and "LAB-101" in codes, str(codes))
    lab = facility_id("LAB-101")
    sem = facility_id("SEM-201")
    chem = facility_id("CHEM-LAB")

    # --- Booking validation ---
    start, end = fresh_slot()
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"],
                           {"facility_id": sem, "start_time": end, "end_time": start, "purpose": "Reversed", "attendees": 5},
                           key=f"val-{run}-a")
    check("booking with end before start is rejected (422)", status == 422 and body["error"]["code"] == "VALIDATION_ERROR")
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"],
                           {"facility_id": sem, "start_time": "2020-01-01T10:00:00Z", "end_time": "2020-01-01T11:00:00Z",
                            "purpose": "Past slot", "attendees": 5}, key=f"val-{run}-b")
    check("booking in the past is rejected (422)", status == 422, str(body and body.get("error", {}).get("message")))
    s9, e9 = fresh_slot(hours=9)
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"],
                           {"facility_id": sem, "start_time": s9, "end_time": e9, "purpose": "Too long", "attendees": 5},
                           key=f"val-{run}-c")
    check("booking longer than the maximum duration is rejected (422)", status == 422)
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"],
                           {"facility_id": sem, "start_time": start, "end_time": end, "purpose": "Oversized group",
                            "attendees": 500}, key=f"val-{run}-d")
    check("booking above facility capacity is rejected (422)", status == 422 and body["error"]["code"] == "CAPACITY_EXCEEDED")
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"], {"facility_id": sem}, key=f"val-{run}-e")
    check("booking with missing fields is rejected (422)", status == 422)
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"], None, key=f"val-{run}-f")
    check("request with no JSON body is rejected (400)", status == 400 and body["error"]["code"] == "BAD_JSON")

    # --- Role restrictions and approval workflow ---
    rs, re_ = fresh_slot(hours=2)
    status, body, _ = call("POST", "/bookings", TOKENS["student1"],
                           {"facility_id": lab, "start_time": rs, "end_time": re_, "purpose": "Lab practice", "attendees": 3},
                           key=f"role-{run}-stu")
    check("student cannot book a restricted facility (403)", status == 403 and body["error"]["code"] == "ROLE_RESTRICTED")

    status, body, _ = call("POST", "/bookings", TOKENS["sensor-gw"],
                           {"facility_id": sem, "start_time": rs, "end_time": re_, "purpose": "Machine booking", "attendees": 2},
                           key=f"role-{run}-sensor")
    check("sensor gateway cannot create bookings (403)", status == 403)

    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"],
                           {"facility_id": lab, "start_time": rs, "end_time": re_, "purpose": "Lab practice", "attendees": 20},
                           key=f"book-{run}-lab")
    check("faculty can request a restricted facility (201, status REQUESTED)",
          status == 201 and body["status"] == "REQUESTED", str(body and body.get("status")))
    lab_booking = body

    status, body, _ = call("POST", "/bookings/%d/transition" % lab_booking["id"], TOKENS["faculty1"],
                           {"action": "approve", "version": lab_booking["version"]}, key=f"appr-{run}-x")
    check("faculty cannot approve a booking (403)", status == 403, str(body and body.get("error", {}).get("code")))

    status, body, _ = call("POST", "/bookings/%d/transition" % lab_booking["id"], TOKENS["approver"],
                           {"action": "approve", "version": lab_booking["version"], "note": "Approved for practical"},
                           key=f"appr-{run}-y")
    check("approver approves a restricted booking (APPROVED)", status == 200 and body["status"] == "APPROVED", str(body and body.get("status")))
    approved = body

    status, body, _ = call("POST", "/bookings/%d/transition" % approved["id"], TOKENS["faculty1"],
                           {"action": "confirm", "version": approved["version"]}, key=f"conf-{run}-y")
    check("requester confirms an approved booking (CONFIRMED)", status == 200 and body["status"] == "CONFIRMED")
    confirmed = body

    status, body, _ = call("POST", "/bookings/%d/transition" % confirmed["id"], TOKENS["faculty1"],
                           {"action": "approve", "version": confirmed["version"]}, key=f"bad-{run}-z")
    check("invalid transition is rejected (409 INVALID_TRANSITION)", status == 409 and body["error"]["code"] == "INVALID_TRANSITION")

    status, body, _ = call("POST", "/bookings/%d/transition" % confirmed["id"], TOKENS["faculty1"],
                           {"action": "start", "version": 1}, key=f"stale-{run}-q")
    check("stale version on a booking is rejected (409 VERSION_CONFLICT)", status == 409 and body["error"]["code"] == "VERSION_CONFLICT")

    # --- Overlapping reservations ---
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"],
                           {"facility_id": lab, "start_time": rs, "end_time": re_, "purpose": "Duplicate slot", "attendees": 10},
                           key=f"ovl-{run}-1")
    check("overlapping booking of the same slot is blocked (409 BOOKING_OVERLAP)",
          status == 409 and body["error"]["code"] == "BOOKING_OVERLAP", str(body and body.get("error", {}).get("code")))
    partial_start = (datetime.fromisoformat(rs) + timedelta(minutes=30)).isoformat()
    partial_end = (datetime.fromisoformat(re_) + timedelta(minutes=30)).isoformat()
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"],
                           {"facility_id": lab, "start_time": partial_start, "end_time": partial_end, "purpose": "Partial overlap", "attendees": 10},
                           key=f"ovl-{run}-2")
    check("partially overlapping booking is blocked (409)", status == 409)
    adjacent_start = re_
    adjacent_end = (datetime.fromisoformat(re_) + timedelta(hours=1)).isoformat()
    status, body, _ = call("POST", "/bookings", TOKENS["faculty1"],
                           {"facility_id": lab, "start_time": adjacent_start, "end_time": adjacent_end, "purpose": "Back-to-back", "attendees": 10},
                           key=f"ovl-{run}-3")
    check("back-to-back booking that touches but does not overlap is accepted", status == 201, str(body and body.get("status")))

    # --- Idempotency and retry safety ---
    ss, se = fresh_slot(hours=1)
    payload = {"facility_id": sem, "start_time": ss, "end_time": se, "purpose": "Retry-safe booking", "attendees": 6}
    key = f"idem-{run}-booking"
    status1, body1, h1 = call("POST", "/bookings", TOKENS["faculty1"], payload, key=key)
    status2, body2, h2 = call("POST", "/bookings", TOKENS["faculty1"], payload, key=key)
    check("first booking with an Idempotency-Key is created (201)", status1 == 201, str(status1))
    check("retry with same key and body returns the same booking id",
          status2 == 201 and body2["id"] == body1["id"], f"ids {body1 and body1['id']} / {body2 and body2['id']}")
    check("retry is flagged as a replay (Idempotent-Replayed: true)", h2.get("Idempotent-Replayed") == "true",
          str(h2.get("Idempotent-Replayed")))
    status3, body3, _ = call("POST", "/bookings", TOKENS["faculty1"], dict(payload, purpose="Different body"), key=key)
    check("same key with a different body is rejected (422 IDEMPOTENCY_KEY_REUSED)",
          status3 == 422 and body3["error"]["code"] == "IDEMPOTENCY_KEY_REUSED")
    status4, body4, _ = call("POST", "/bookings", TOKENS["faculty1"], payload, key=None)
    check("create without Idempotency-Key is rejected (400)", status4 == 400 and body4["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED")
    status5, body5, _ = call("GET", f"/bookings/{body1['id']}", TOKENS["faculty1"])
    check("exactly one booking exists after retries (GET reflects a single record)", status5 == 200 and body5["id"] == body1["id"])

    # --- Maintenance tickets: triage, RBAC, versioning ---
    status, body, _ = call("POST", "/tickets", TOKENS["student1"],
                           {"title": f"Water leak near basin Lab {run % 1000}", "description": "Pooling water on floor",
                            "facility_id": chem}, key=f"tk-{run}-1")
    check("ticket creation returns 201 with triage category and priority",
          status == 201 and body["category"] == "PLUMBING" and body["priority"] == "HIGH" and body["status"] == "INTAKE",
          f"{body and body.get('category')}/{body and body.get('priority')}")
    check("triage response explains which keyword rules fired", bool(body and body["triage_rules"]), str(body and body["triage_rules"]))
    ticket = body
    status, body, _ = call("POST", "/tickets", TOKENS["student1"],
                           {"title": f"Water leak near basin Lab {run % 1000}", "description": "Pooling water on floor",
                            "facility_id": chem}, key=f"tk-{run}-1")
    check("retried ticket request returns the same ticket (no duplicate ticket)", status == 201 and body["id"] == ticket["id"])
    status, body, _ = call("POST", "/tickets", TOKENS["student1"],
                           {"title": "Chair wobble in study area", "priority": "CRITICAL"}, key=f"tk-{run}-2")
    check("non-manager cannot set ticket priority (403)", status == 403)

    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["tech1"],
                           {"action": "assign", "version": 1, "assignee_id": 1}, key=f"tr-{run}-t0")
    check("technician cannot assign tickets (403)", status == 403)

    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["facmgr"],
                           {"action": "assign", "version": ticket["version"], "assignee_id": _tech_id("tech1")}, key=f"tr-{run}-a1")
    check("facility manager assigns the ticket to a technician (ASSIGNED, version +1)",
          status == 200 and body["status"] == "ASSIGNED" and body["version"] == ticket["version"] + 1, str(body and body.get("status")))
    assigned = body

    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["facmgr"],
                           {"action": "assign", "version": ticket["version"], "assignee_id": _tech_id("tech2")}, key=f"tr-{run}-a2")
    check("conflicting update using a stale version is rejected (409 VERSION_CONFLICT)",
          status == 409 and body["error"]["code"] == "VERSION_CONFLICT")

    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["tech2"],
                           {"action": "start_inspection", "version": assigned["version"], "notes": "Not my ticket"}, key=f"tr-{run}-n")
    check("a technician who is not the assignee cannot update the ticket (403)", status == 403)

    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["tech1"],
                           {"action": "start_inspection", "version": assigned["version"], "notes": "Trap under basin cracked"},
                           key=f"tr-{run}-i")
    check("assigned technician starts inspection with notes (INSPECTION)", status == 200 and body["status"] == "INSPECTION")
    inspecting = body

    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["tech1"],
                           {"action": "resolve", "version": inspecting["version"]}, key=f"tr-{run}-r0")
    check("resolution without notes is rejected (422)", status == 422)
    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["tech1"],
                           {"action": "resolve", "version": inspecting["version"], "notes": "Replaced trap and sealed joint"},
                           key=f"tr-{run}-r1")
    check("technician records resolution (RESOLVED)", status == 200 and body["status"] == "RESOLVED")
    resolved = body
    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["tech1"],
                           {"action": "close", "version": resolved["version"]}, key=f"tr-{run}-c0")
    check("technician cannot close a ticket (403)", status == 403)
    status, body, _ = call("POST", f"/tickets/{ticket['id']}/transition", TOKENS["facmgr"],
                           {"action": "close", "version": resolved["version"]}, key=f"tr-{run}-c1")
    check("facility manager authorises closure (CLOSED, closed_at set)",
          status == 200 and body["status"] == "CLOSED" and bool(body["closed_at"]))

    status, body, _ = call("GET", f"/tickets/{ticket['id']}", TOKENS["student1"])
    check("reporter sees the closed ticket with inspection and resolution notes",
          status == 200 and body["status"] == "CLOSED" and "Trap under basin" in body["inspection_notes"])

    # --- Sensor events and duplicate suppression ---
    event = f"GW-TEST-{run}-smoke"
    status, body, _ = call("POST", "/sensor-events", TOKENS["sensor-gw"],
                           {"event_key": event, "facility_id": chem, "sensor_type": "SMOKE_LEVEL", "reading": 0.9},
                           key=f"sen-{run}-1")
    check("sensor breach creates a tracked ticket (201, breached)", status == 201 and body["breached"] and body["ticket_id"])
    sensor_ticket = body["ticket_id"]
    status, body, _ = call("POST", "/sensor-events", TOKENS["sensor-gw"],
                           {"event_key": event, "facility_id": chem, "sensor_type": "SMOKE_LEVEL", "reading": 0.9},
                           key=f"sen-{run}-2")
    check("re-sent sensor message is recognised as duplicate (no second ticket)",
          status == 200 and body["duplicate"] and body["ticket_id"] == sensor_ticket)
    status, body, _ = call("GET", f"/tickets/{sensor_ticket}", TOKENS["facmgr"])
    check("sensor ticket is CRITICAL SAFETY with a threshold rule recorded",
          body["category"] == "SAFETY" and body["priority"] == "CRITICAL" and body["source"] == "SENSOR"
          and any("threshold" in r for r in body["triage_rules"]))
    status, body, _ = call("POST", "/sensor-events", TOKENS["sensor-gw"],
                           {"event_key": f"GW-TEST-{run}-temp", "facility_id": sem, "sensor_type": "TEMPERATURE", "reading": 22},
                           key=f"sen-{run}-3")
    check("normal temperature reading creates no ticket", status == 201 and body["breached"] is False and body["ticket_id"] is None)
    status, body, _ = call("POST", "/sensor-events", TOKENS["student1"],
                           {"event_key": f"GW-TEST-{run}-forged", "facility_id": sem, "sensor_type": "TEMPERATURE", "reading": 40},
                           key=f"sen-{run}-4")
    check("a student cannot submit sensor events (403)", status == 403)

    # --- Linked integration record with retry ---
    status, body, _ = call("POST", f"/tickets/{ticket['id']}/links", TOKENS["faculty1"],
                           {"provider": "devops-issue", "title": "Investigate recurring basin leak"}, key=f"lnk-{run}-f")
    check("faculty cannot create integration links (403)", status == 403)
    status, body, _ = call("POST", f"/tickets/{ticket['id']}/links", TOKENS["facmgr"],
                           {"provider": "devops-issue", "title": "Investigate recurring basin leak"}, key=f"lnk-{run}-m")
    check("manager creates a linked DevOps issue record", status == 201 and body["status"] in ("SYNCED", "PENDING"),
          f"status={body and body.get('status')} mode={body and body.get('mode')} error={body and body.get('last_error')}")
    link = body
    status, body, _ = call("POST", f"/integrations/{link['id']}/retry", TOKENS["facmgr"], None, key=f"ret-{run}-1")
    check("retry of a linked record returns a definite status (SYNCED or PENDING)",
          status == 200 and body["status"] in ("SYNCED", "PENDING"), f"status={body and body.get('status')} attempts={body and body.get('attempts')}")

    # --- Dashboard, audit, errors ---
    status, body, _ = call("GET", "/dashboard", TOKENS["facmgr"])
    check("dashboard returns status counts and SLA indicator",
          status == 200 and "tickets_by_status" in body and "open_tickets_past_sla" in body)
    status, body, _ = call("GET", f"/audit?entity_type=ticket&entity_id={ticket['id']}", TOKENS["facmgr"])
    actions = [e["action"] for e in body["items"]] if status == 200 else []
    check("audit trail records every ticket change", status == 200 and {"created", "assign", "start_inspection", "resolve", "close"} <= set(actions),
          str(sorted(set(actions))))
    status, body, _ = call("GET", "/audit", TOKENS["student1"])
    check("students cannot read the audit trail (403)", status == 403)
    status, body, _ = call("GET", "/no-such-route", TOKENS["facmgr"])
    check("unknown route returns a JSON 404", status == 404 and body["error"]["code"] == "NOT_FOUND")

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\nSUMMARY: {passed}/{len(RESULTS)} checks passed")
    failed = [name for name, ok in RESULTS if not ok]
    if failed:
        print("FAILED:")
        for name in failed:
            print("  -", name)
    return 0 if not failed else 1


_TECH_CACHE = {}


def _tech_id(username):
    if username not in _TECH_CACHE:
        _, body, _ = call("GET", "/users?role=technician", TOKENS["facmgr"])
        for user in body["items"]:
            _TECH_CACHE[user["username"]] = user["id"]
    return _TECH_CACHE[username]


if __name__ == "__main__":
    sys.exit(main())
