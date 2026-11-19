"""Persistence evidence for restart tests.

  python scripts/persistence_check.py snapshot  snapshot.json   # before restarting a container
  python scripts/persistence_check.py verify    snapshot.json   # after restarting it

verify exits non-zero if any booking/ticket recorded in the snapshot is missing or changed,
or if the newest audit event has disappeared.
"""
import json
import sys

from common import TOKENS, call


def collect():
    _, bookings, _ = call("GET", "/bookings", TOKENS["facmgr"])
    _, tickets, _ = call("GET", "/tickets", TOKENS["facmgr"])
    _, audit, _ = call("GET", "/audit", TOKENS["facmgr"])
    return {
        "bookings": {str(b["id"]): [b["status"], b["version"]] for b in bookings["items"]},
        "tickets": {str(t["id"]): [t["status"], t["version"]] for t in tickets["items"]},
        "latest_audit_id": audit["items"][0]["id"] if audit["items"] else None,
    }


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("snapshot", "verify"):
        print(__doc__)
        return 2
    mode, path = sys.argv[1], sys.argv[2]
    current = collect()
    if mode == "snapshot":
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2)
        print(f"snapshot saved: {len(current['bookings'])} bookings, {len(current['tickets'])} tickets, "
              f"latest audit id {current['latest_audit_id']}")
        return 0
    with open(path, encoding="utf-8") as handle:
        before = json.load(handle)
    missing_b = [k for k in before["bookings"] if k not in current["bookings"]]
    changed_b = [k for k in before["bookings"] if k in current["bookings"] and current["bookings"][k] != before["bookings"][k]]
    missing_t = [k for k in before["tickets"] if k not in current["tickets"]]
    changed_t = [k for k in before["tickets"] if k in current["tickets"] and current["tickets"][k] != before["tickets"][k]]
    audit_ok = current["latest_audit_id"] is not None and (before["latest_audit_id"] or 0) <= current["latest_audit_id"]
    print(f"bookings: {len(before['bookings'])} before, {len(current['bookings'])} after; missing {missing_b}; changed {changed_b}")
    print(f"tickets:  {len(before['tickets'])} before, {len(current['tickets'])} after; missing {missing_t}; changed {changed_t}")
    print(f"audit trail intact: {audit_ok} (latest id before {before['latest_audit_id']}, after {current['latest_audit_id']})")
    ok = not (missing_b or changed_b or missing_t or changed_t) and audit_ok
    print("PERSISTENCE: PASS" if ok else "PERSISTENCE: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
