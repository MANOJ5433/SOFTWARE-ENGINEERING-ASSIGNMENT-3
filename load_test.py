"""Bounded load experiment. Reports only what it measures.

It does NOT prove support for any particular number of users. It sends a fixed number of concurrent
clients for a fixed duration and records throughput, latency, status codes and which backend instance
served each response (from the X-Served-By header added by the backend).

Run:  BASE_URL=http://localhost:8080 python scripts/load_test.py --threads 20 --seconds 20
"""
import argparse
import random
import statistics
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from common import TOKENS, call


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()

    _, facilities, _ = call("GET", "/facilities", TOKENS["student1"])
    seminar = next(f["id"] for f in facilities["items"] if f["code"] == "SEM-201")
    run = random.randint(100000, 999999)
    stop_at = time.time() + args.seconds
    latencies, statuses, served_by, errors = [], Counter(), Counter(), []
    lock = threading.Lock()

    def client(worker):
        seq = 0
        while time.time() < stop_at:
            seq += 1
            choice = random.random()
            began = time.perf_counter()
            try:
                if choice < 0.5:
                    status, _, headers = call("GET", "/facilities", TOKENS["student1"])
                elif choice < 0.75:
                    status, _, headers = call("GET", "/dashboard", TOKENS["facmgr"])
                else:
                    base = datetime(2028, 1, 1, tzinfo=timezone.utc) + timedelta(hours=random.randint(0, 40000))
                    status, _, headers = call("POST", "/bookings", TOKENS["faculty1"],
                                              {"facility_id": seminar, "start_time": base.isoformat(),
                                               "end_time": (base + timedelta(hours=1)).isoformat(),
                                               "purpose": f"Load test {run}", "attendees": 3},
                                              key=f"load-{run}-{worker}-{seq}")
            except Exception as exc:  # network-level failure
                with lock:
                    errors.append(type(exc).__name__)
                continue
            elapsed = (time.perf_counter() - began) * 1000
            with lock:
                latencies.append(elapsed)
                statuses[status] += 1
                served_by[headers.get("X-Served-By", "unknown")] += 1

    threads = [threading.Thread(target=client, args=(i,)) for i in range(args.threads)]
    started = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    duration = time.time() - started

    total = len(latencies)
    latencies.sort()
    p50 = statistics.median(latencies) if latencies else 0
    p95 = latencies[int(0.95 * (len(latencies) - 1))] if latencies else 0
    print(f"Bounded load experiment: {args.threads} concurrent clients for {duration:.1f} s")
    print(f"  requests completed: {total}  throughput: {total / duration:.1f} req/s")
    print(f"  latency ms: median {p50:.0f}, p95 {p95:.0f}, max {max(latencies) if latencies else 0:.0f}")
    print(f"  status codes: {dict(sorted(statuses.items()))}")
    print(f"  responses per backend instance: {dict(served_by)}")
    print(f"  network-level errors: {len(errors)} {dict(Counter(errors))}")
    server_errors = sum(v for k, v in statuses.items() if k >= 500)
    print("  note: 409 responses on bookings are expected overlap rejections, not failures.")
    return 0 if server_errors == 0 and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
