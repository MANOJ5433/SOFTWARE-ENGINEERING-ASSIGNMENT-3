"""Convert database rows into API response objects."""
import json

from .db import now_iso, to_iso


def facility_out(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "name": r["name"],
        "location": r["location"],
        "capacity": r["capacity"],
        "restricted": bool(r["restricted"]),
        "active": bool(r["active"]),
    }


def booking_out(r):
    return {
        "id": r["id"],
        "facility_id": r["facility_id"],
        "facility_code": r.get("facility_code"),
        "facility_name": r.get("facility_name"),
        "requester_id": r["requester_id"],
        "requester_username": r.get("requester_username"),
        "start_time": to_iso(r["start_time"]),
        "end_time": to_iso(r["end_time"]),
        "purpose": r["purpose"],
        "attendees": r["attendees"],
        "status": r["status"],
        "decision_note": r.get("decision_note"),
        "version": r["version"],
        "created_at": to_iso(r["created_at"]),
        "updated_at": to_iso(r["updated_at"]),
    }


def ticket_out(r):
    rules = r.get("triage_rules") or "[]"
    return {
        "id": r["id"],
        "facility_id": r["facility_id"],
        "facility_code": r.get("facility_code"),
        "reporter_id": r["reporter_id"],
        "reporter_username": r.get("reporter_username"),
        "source": r["source"],
        "title": r["title"],
        "description": r["description"],
        "category": r["category"],
        "priority": r["priority"],
        "status": r["status"],
        "assignee_id": r["assignee_id"],
        "assignee_username": r.get("assignee_username"),
        "inspection_notes": r["inspection_notes"],
        "resolution_notes": r["resolution_notes"],
        "triage_rules": json.loads(rules) if isinstance(rules, str) else rules,
        "sla_due_at": to_iso(r["sla_due_at"]),
        "sla_breached": r["status"] != "CLOSED" and to_iso(r["sla_due_at"]) < now_iso(),
        "version": r["version"],
        "created_at": to_iso(r["created_at"]),
        "updated_at": to_iso(r["updated_at"]),
        "closed_at": to_iso(r["closed_at"]),
    }

