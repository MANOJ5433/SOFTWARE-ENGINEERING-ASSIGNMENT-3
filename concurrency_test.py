"""Concurrency and retry-safety experiments against the running service.

Each experiment fires simultaneous requests and asserts an invariant:
  A. Two or more users reserve the same facility slot at the same moment -> exactly one reservation survives.
  B. The same booking request is retried concurrently with the same Idempotency-Key -> exactly one record.
  C. Two technicians submit an update to the same ticket version at once -> exactly one update applies.
  D. A sensor gateway re-sends the same event concurrently -> exactly one ticket is created.

Run:  BASE_URL=http://localhost:8080 python scripts/concurrency_test.py [--threads 20]
"""
import argparse
import random
import sys
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

from common import TOKENS, call


def run_parallel(n, fn):
    """Start n threads that wait on one barrier, so requests hit the server together."""
    barrier = threading.Barrier(n)
    results = [None] * n

    def worker(i):
        barrier.wait()
        results[i] = fn(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def facility(code):
    _, body, _ = call("GET", "/facilities", TOKENS["student1"])
    return next(f["id"] for f in body["items"] if f["code"] == code)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=20)
    args = parser.parse_args()
    n = args.threads
    failures = []
    run = random.randint(100000, 999999)

    # Experiment A: simultaneous conflicting reservations of one slot.
    seminar = facility("SEM-201")
    base = datetime(2027, 6, 1, tzinfo=timezone.utc) + timedelta(hours=random.randint(0, 20000))
    start, end = base.isoformat(), (base + timedelta(hours=2)).isoformat()
    users = [TOKENS["faculty1"], TOKENS["student1"], TOKENS["facmgr"], TOKENS["admin"]]

    def book_a(i):
        token = users[i % len(users)]
        return call("POST", "/bookings", token,
                    {"facility_id": seminar, "start_time": start, "end_time": end,
                     "purpose": f"Contention test {run} from user {i}", "attendees": 5},
                    key=f"conc-{run}-A-{i:03d}")

    results = run_parallel(n, book_a)
    codes = Counter(r[0] for r in results)
    created = codes.get(201, 0)
    overlap = sum(1 for r in results if r[0] == 409 and r[1] and r[1]["error"]["code"] == "BOOKING_OVERLAP")
    print(f"\nExperiment A - {n} simultaneous reservations of SEM-201 {start} to {end}")
    print(f"  status codes: {dict(codes)}  (201 created: {created}, 409 BOOKING_OVERLAP: {overlap})")
    if created != 1 or overlap != n - 1 or codes.get(500, 0):
        failures.append("A: expected exactly one reservation and the rest rejected as overlaps")

    # Experiment B: identical retried request sent concurrently with one Idempotency-Key.
    base_b = base + timedelta(days=3)
    body_b = {"facility_id": seminar, "start_time": base_b.isoformat(),
              "end_time": (base_b + timedelta(hours=1)).isoformat(), "purpose": f"Retry storm {run}", "attendees": 4}

    results_b = run_parallel(n, lambda i: call("POST", "/bookings", TOKENS["faculty1"], body_b, key=f"conc-{run}-B-same"))
    ids = {r[1]["id"] for r in results_b if r[0] == 201}
    replays = sum(1 for r in results_b if r[2] and r[2].get("Idempotent-Replayed") == "true")
    codes_b = Counter(r[0] for r in results_b)
    print(f"\nExperiment B - {n} concurrent retries with the same Idempotency-Key")
    print(f"  status codes: {dict(codes_b)}  distinct booking ids: {sorted(ids)}  replayed responses: {replays}")
    if len(ids) != 1 or codes_b.get(500, 0) or any(r[0] not in (201, 409) for r in results_b):
        failures.append("B: retries must produce exactly one booking")
    if codes_b.get(409, 0):
        print("  note: 409 responses here mean a retry arrived while the original was still in progress;"
              " the client should wait and retry with the same key.")

    # Experiment C: two technicians update the same ticket version concurrently.
    _, ticket_body, _ = call("POST", "/tickets", TOKENS["student1"],
                             {"title": f"Door lock jammed run {run}", "description": "Cannot lock from inside"},
                             key=f"conc-{run}-C-create")
    _, users_body, _ = call("GET", "/users?role=technician", TOKENS["facmgr"])
    tech1 = next(u["id"] for u in users_body["items"] if u["username"] == "tech1")
    _, assigned, _ = call("POST", f"/tickets/{ticket_body['id']}/transition", TOKENS["facmgr"],
                          {"action": "assign", "version": ticket_body["version"], "assignee_id": tech1},
                          key=f"conc-{run}-C-assign")
    results_c = run_parallel(n, lambda i: call(
        "POST", f"/tickets/{ticket_body['id']}/transition", TOKENS["tech1"],
        {"action": "start_inspection", "version": assigned["version"], "notes": f"Inspection attempt {i}"},
        key=f"conc-{run}-C-{i:03d}"))
    codes_c = Counter(r[0] for r in results_c)
    conflicts = sum(1 for r in results_c if r[0] == 409 and r[1] and r[1]["error"]["code"] == "VERSION_CONFLICT")
    print(f"\nExperiment C - {n} concurrent technician updates to ticket {ticket_body['id']} at version {assigned['version']}")
    print(f"  status codes: {dict(codes_c)}  (200 applied: {codes_c.get(200, 0)}, 409 VERSION_CONFLICT: {conflicts})")
    if codes_c.get(200, 0) != 1 or conflicts != n - 1:
        failures.append("C: exactly one technician update must apply")

    # Experiment D: duplicate sensor messages sent concurrently.
    event = f"GW-CONC-{run}-smoke"
    chem = facility("CHEM-LAB")
    results_d = run_parallel(n, lambda i: call(
        "POST", "/sensor-events", TOKENS["sensor-gw"],
        {"event_key": event, "facility_id": chem, "sensor_type": "SMOKE_LEVEL", "reading": 0.7},
        key=f"conc-{run}-D-{i:03d}"))
    codes_d = Counter(r[0] for r in results_d)
    ticket_ids = {r[1]["ticket_id"] for r in results_d if r[0] in (200, 201) and r[1]}
    created_d = sum(1 for r in results_d if r[0] == 201)
    print(f"\nExperiment D - {n} concurrent copies of sensor event {event}")
    print(f"  status codes: {dict(codes_d)}  (new records: {created_d})  distinct tickets: {len(ticket_ids)}")
    if created_d != 1 or len(ticket_ids) != 1 or codes_d.get(500, 0):
        failures.append("D: duplicate sensor events must create exactly one record and one ticket")

    print("\nRESULT:", "PASS - all invariants held" if not failures else "FAIL")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
