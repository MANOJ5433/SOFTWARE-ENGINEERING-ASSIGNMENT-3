"""Maintenance tickets, sensor-event intake and linked integration records."""
import json
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, request

from .audit import record
from .auth import auth_required, require_roles
from .blueprint import bp
from .constants import (
    FIELD_ACTIONS,
    MANAGER_ROLES,
    PRIORITIES,
    SENSOR_TYPES,
    STAFF_ROLES,
    TICKET_ACTION_ROLES,
    TICKET_CATEGORIES,
    TICKET_TRANSITIONS,
)
from .db import get_tx, now_iso, to_iso, write
from .errors import ApiError
from .idempotency import respond_idempotent
from .serializers import ticket_out
from .triage import SLA_HOURS, classify, evaluate_sensor
from .util import json_body, require_choice, require_int, require_number, require_str

TICKET_SELECT = (
    "SELECT t.*, f.code AS facility_code, ru.username AS reporter_username, au.username AS assignee_username "
    "FROM tickets t LEFT JOIN facilities f ON f.id = t.facility_id "
    "LEFT JOIN users ru ON ru.id = t.reporter_id LEFT JOIN users au ON au.id = t.assignee_id"
)
MAX_NOTES = 2000


def _fetch_ticket(tx, ticket_id):
    return ticket_out(tx.one(TICKET_SELECT + " WHERE t.id = %s", (ticket_id,)))


def _can_view(user, row):
    if user["role"] in MANAGER_ROLES + ("approver",):
        return True
    if user["role"] == "technician":
        return row["assignee_id"] == user["id"]
    return row["reporter_id"] == user["id"]


@bp.get("/tickets")
@auth_required
def list_tickets(user):
    sql = TICKET_SELECT + " WHERE 1 = 1"
    params = []
    if user["role"] == "technician":
        sql += " AND t.assignee_id = %s"
        params.append(user["id"])
    elif user["role"] not in MANAGER_ROLES + ("approver",):
        sql += " AND t.reporter_id = %s"
        params.append(user["id"])
    for arg, column in (("status", "t.status"), ("priority", "t.priority")):
        if request.args.get(arg):
            sql += f" AND {column} = %s"
            params.append(request.args[arg])
    sql += " ORDER BY CASE t.priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, t.id"
    return jsonify({"items": [ticket_out(r) for r in get_tx().all(sql, params)]})


@bp.get("/tickets/<int:ticket_id>")
@auth_required
def get_ticket(user, ticket_id):
    row = get_tx().one(TICKET_SELECT + " WHERE t.id = %s", (ticket_id,))
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Ticket not found")
    if not _can_view(user, row):
        raise ApiError(403, "FORBIDDEN", "You cannot view this ticket")
    return jsonify(ticket_out(row))


@bp.post("/tickets")
@auth_required
def create_ticket(user):
    body = json_body()
    return respond_idempotent("tickets.create", user, body, lambda tx: _create_ticket(tx, user, body))


def _create_ticket(tx, user, body):
    if user["role"] == "sensor":
        raise ApiError(403, "FORBIDDEN", "Sensor gateways report through /api/sensor-events")
    title = require_str(body, "title", 5, 120)
    description = require_str(body, "description", 0, MAX_NOTES, required=False)
    facility_id = None
    if body.get("facility_id") is not None:
        facility_id = require_int(body, "facility_id")
        if tx.one("SELECT id FROM facilities WHERE id = %s AND active = %s", (facility_id, True)) is None:
            raise ApiError(404, "FACILITY_NOT_FOUND", "Facility not found or inactive")

    suggestion = classify(title, description)
    category, priority, rules = suggestion["category"], suggestion["priority"], list(suggestion["rules"])
    if body.get("category") is not None:
        category = require_choice(body, "category", TICKET_CATEGORIES)
        rules.append(f"category set by reporter: {category}")
    if body.get("priority") is not None:
        if user["role"] not in MANAGER_ROLES:
            raise ApiError(403, "FORBIDDEN", "Only facility managers or administrators may set priority manually")
        priority = require_choice(body, "priority", PRIORITIES)
        rules.append(f"priority set by {user['role']}: {priority}")

    due = (datetime.now(timezone.utc) + timedelta(hours=SLA_HOURS[priority])).replace(microsecond=0).isoformat()
    now = now_iso()
    ticket_id = tx.insert(
        "INSERT INTO tickets (facility_id, reporter_id, source, title, description, category, priority, status, "
        "triage_rules, sla_due_at, version, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)",
        (facility_id, user["id"], "USER", title, description, category, priority, "INTAKE",
         json.dumps(rules), due, now, now),
    )
    record(tx, "ticket", ticket_id, "created", user["id"], {"category": category, "priority": priority, "rules": rules})
    return 201, _fetch_ticket(tx, ticket_id)


@bp.post("/tickets/<int:ticket_id>/transition")
@auth_required
def transition_ticket(user, ticket_id):
    body = json_body()
    endpoint = f"tickets.transition.{ticket_id}"
    return respond_idempotent(endpoint, user, body, lambda tx: _transition_ticket(tx, user, ticket_id, body))


def _append_notes(existing, new):
    if not new:
        return existing
    combined = (existing + "\n" + new).strip() if existing else new
    if len(combined) > MAX_NOTES:
        raise ApiError(422, "VALIDATION_ERROR", "Notes would exceed 2000 characters", {"field": "notes"})
    return combined


def _transition_ticket(tx, user, ticket_id, body):
    action = require_str(body, "action", 3, 30)
    version = require_int(body, "version", 1)
    notes = require_str(body, "notes", 0, MAX_NOTES, required=False)
    known_actions = {action_name for (_, action_name) in TICKET_TRANSITIONS}
    if action not in known_actions:
        raise ApiError(422, "VALIDATION_ERROR", "Unknown action", {"field": "action", "allowed": sorted(known_actions)})

    row = tx.one("SELECT * FROM tickets WHERE id = %s", (ticket_id,), lock=True)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Ticket not found")
    # Optimistic concurrency: two technicians who both read version N cannot both succeed.
    if row["version"] != version:
        raise ApiError(409, "VERSION_CONFLICT", "The ticket was updated by someone else; reload and retry",
                       {"current_version": row["version"], "current_status": row["status"]})

    next_status = TICKET_TRANSITIONS.get((row["status"], action))
    if next_status is None:
        raise ApiError(409, "INVALID_TRANSITION", f"Cannot '{action}' a ticket that is {row['status']}",
                       {"current_status": row["status"]})

    if action in TICKET_ACTION_ROLES:
        require_roles(user, TICKET_ACTION_ROLES[action])
    elif action in FIELD_ACTIONS:
        is_assigned = user["role"] == "technician" and row["assignee_id"] == user["id"]
        if user["role"] not in MANAGER_ROLES and not is_assigned:
            raise ApiError(403, "FORBIDDEN", "Only the assigned technician or a manager may update this ticket")

    now = now_iso()
    assignee_id = row["assignee_id"]
    inspection = row["inspection_notes"] or ""
    resolution = row["resolution_notes"] or ""
    closed_at = row["closed_at"]

    if action == "assign":
        assignee_id = require_int(body, "assignee_id")
        tech = tx.one("SELECT id, role, active FROM users WHERE id = %s", (assignee_id,))
        if tech is None or tech["role"] != "technician" or not tech["active"]:
            raise ApiError(422, "VALIDATION_ERROR", "assignee_id must be an active technician", {"field": "assignee_id"})
    elif action == "start_inspection":
        inspection = _append_notes(inspection, notes)
    elif action == "pending_work":
        if not notes:
            raise ApiError(422, "VALIDATION_ERROR", "notes describing the pending work are required", {"field": "notes"})
        inspection = _append_notes(inspection, notes)
    elif action == "resolve":
        if not notes:
            raise ApiError(422, "VALIDATION_ERROR", "notes describing the resolution are required", {"field": "notes"})
        resolution = notes
    elif action == "close":
        if not inspection.strip():
            raise ApiError(409, "INSPECTION_REQUIRED", "A ticket cannot be closed before inspection notes are recorded")
        closed_at = now
    elif action == "reopen":
        closed_at = None

    changed = tx.execute(
        "UPDATE tickets SET status = %s, assignee_id = %s, inspection_notes = %s, resolution_notes = %s, "
        "closed_at = %s, version = version + 1, updated_at = %s WHERE id = %s AND version = %s",
        (next_status, assignee_id, inspection, resolution, closed_at, now, ticket_id, version),
    )
    if changed != 1:
        raise ApiError(409, "VERSION_CONFLICT", "The ticket was updated by someone else; reload and retry")
    record(tx, "ticket", ticket_id, action, user["id"],
           {"from": row["status"], "to": next_status, "notes": notes or None, "assignee_id": assignee_id})
    return 200, _fetch_ticket(tx, ticket_id)


@bp.patch("/tickets/<int:ticket_id>")
@auth_required
def change_priority(user, ticket_id):
    require_roles(user, MANAGER_ROLES)
    body = json_body()
    priority = require_choice(body, "priority", PRIORITIES)
    version = require_int(body, "version", 1)

    def work(tx):
        row = tx.one("SELECT * FROM tickets WHERE id = %s", (ticket_id,), lock=True)
        if row is None:
            raise ApiError(404, "NOT_FOUND", "Ticket not found")
        if row["version"] != version:
            raise ApiError(409, "VERSION_CONFLICT", "The ticket was updated by someone else; reload and retry",
                           {"current_version": row["version"]})
        created = datetime.fromisoformat(to_iso(row["created_at"]))
        due = (created + timedelta(hours=SLA_HOURS[priority])).isoformat()
        tx.execute(
            "UPDATE tickets SET priority = %s, sla_due_at = %s, version = version + 1, updated_at = %s "
            "WHERE id = %s AND version = %s",
            (priority, due, now_iso(), ticket_id, version),
        )
        record(tx, "ticket", ticket_id, "priority_changed", user["id"], {"from": row["priority"], "to": priority})
        return _fetch_ticket(tx, ticket_id)

    return jsonify(write(work))


# ---------- Sensor-event intake ----------

@bp.post("/sensor-events")
@auth_required
def ingest_sensor_event(user):
    body = json_body()
    return respond_idempotent("sensor_events.create", user, body, lambda tx: _ingest_sensor(tx, user, body))


def _ingest_sensor(tx, user, body):
    require_roles(user, ("sensor", "facility_manager", "admin"))
    event_key = require_str(body, "event_key", 8, 120)
    facility_id = require_int(body, "facility_id")
    sensor_type = require_choice(body, "sensor_type", SENSOR_TYPES)
    reading = require_number(body, "reading")

    # Duplicate sensor messages (retries, re-sent batches) are recognised by event_key and never create a second ticket.
    existing = tx.one("SELECT event_key, breached, ticket_id FROM sensor_events WHERE event_key = %s", (event_key,))
    if existing is not None:
        return 200, {
            "duplicate": True,
            "event_key": event_key,
            "breached": bool(existing["breached"]),
            "ticket_id": existing["ticket_id"],
            "message": "Event already processed; no new record created",
        }

    facility = tx.one("SELECT id, code FROM facilities WHERE id = %s AND active = %s", (facility_id, True))
    if facility is None:
        raise ApiError(404, "FACILITY_NOT_FOUND", "Facility not found or inactive")

    config = current_app.config
    breached, category, priority, rules = evaluate_sensor(
        sensor_type, reading, config["TEMPERATURE_THRESHOLD_C"], config["SMOKE_THRESHOLD"])

    ticket_id = None
    if breached:
        now = now_iso()
        due = (datetime.now(timezone.utc) + timedelta(hours=SLA_HOURS[priority])).replace(microsecond=0).isoformat()
        title = f"Sensor alert: {sensor_type} {reading:g} at {facility['code']}"
        ticket_id = tx.insert(
            "INSERT INTO tickets (facility_id, reporter_id, source, title, description, category, priority, status, "
            "triage_rules, sla_due_at, version, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)",
            (facility_id, user["id"], "SENSOR", title, f"Generated from sensor event {event_key}",
             category, priority, "INTAKE", json.dumps(rules), due, now, now),
        )
        record(tx, "ticket", ticket_id, "created", user["id"], {"source": "SENSOR", "event_key": event_key, "rules": rules})

    tx.execute(
        "INSERT INTO sensor_events (event_key, facility_id, sensor_type, reading, breached, ticket_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (event_key, facility_id, sensor_type, reading, breached, ticket_id, now_iso()),
    )
    record(tx, "sensor_event", facility_id, "received", user["id"], {"event_key": event_key, "breached": breached})
    return 201, {
        "duplicate": False,
        "event_key": event_key,
        "breached": breached,
        "ticket_id": ticket_id,
        "rules": rules,
    }


# ---------- Linked integration records (simulated external issue tracker) ----------

def _link_out(row):
    return {
        "id": row["id"],
        "ticket_id": row["ticket_id"],
        "provider": row["provider"],
        "title": row["title"],
        "external_ref": row["external_ref"],
        "mode": row["mode"],
        "status": row["status"],
        "attempts": row["attempts"],
        "last_error": row["last_error"],
        "created_at": to_iso(row["created_at"]),
    }


@bp.post("/tickets/<int:ticket_id>/links")
@auth_required
def create_link(user, ticket_id):
    body = json_body()
    return respond_idempotent(f"links.create.{ticket_id}", user, body,
                              lambda tx: _create_link(tx, user, ticket_id, body))


def _create_link(tx, user, ticket_id, body):
    require_roles(user, STAFF_ROLES)
    provider = require_choice(body, "provider", ("devops-issue",))
    title = require_str(body, "title", 5, 160)
    if tx.one("SELECT id FROM tickets WHERE id = %s", (ticket_id,)) is None:
        raise ApiError(404, "NOT_FOUND", "Ticket not found")

    now = now_iso()
    if current_app.config["SIMULATE_TRACKER_OUTAGE"]:
        status, mode, ref = "PENDING", "LOCAL_QUEUE", None
        error = "Issue tracker unavailable (simulated outage); link kept locally and can be retried"
    else:
        status, mode = "SYNCED", "LOCAL_SIMULATED"
        ref = f"DEV-{secrets.token_hex(3).upper()}"
        error = None
    link_id = tx.insert(
        "INSERT INTO integration_links (ticket_id, provider, title, external_ref, mode, status, attempts, last_error, "
        "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s)",
        (ticket_id, provider, title, ref, mode, status, error, now, now),
    )
    record(tx, "ticket", ticket_id, "link_created", user["id"], {"link_id": link_id, "status": status, "mode": mode})
    return 201, _link_out(tx.one("SELECT * FROM integration_links WHERE id = %s", (link_id,)))


@bp.post("/integrations/<int:link_id>/retry")
@auth_required
def retry_link(user, link_id):
    body = request.get_json(silent=True) or {}
    return respond_idempotent(f"integrations.retry.{link_id}", user, body,
                              lambda tx: _retry_link(tx, user, link_id))


def _retry_link(tx, user, link_id):
    require_roles(user, STAFF_ROLES)
    row = tx.one("SELECT * FROM integration_links WHERE id = %s", (link_id,), lock=True)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Integration link not found")
    if row["status"] == "SYNCED":
        return 200, _link_out(row)  # already delivered: a retry changes nothing
    now = now_iso()
    if current_app.config["SIMULATE_TRACKER_OUTAGE"]:
        tx.execute("UPDATE integration_links SET attempts = attempts + 1, updated_at = %s WHERE id = %s", (now, link_id))
    else:
        ref = f"DEV-{secrets.token_hex(3).upper()}"
        tx.execute(
            "UPDATE integration_links SET status = %s, mode = %s, external_ref = %s, last_error = NULL, "
            "attempts = attempts + 1, updated_at = %s WHERE id = %s",
            ("SYNCED", "LOCAL_SIMULATED", ref, now, link_id),
        )
    record(tx, "integration", link_id, "retry", user["id"], {"attempt_at": now})
    return 200, _link_out(tx.one("SELECT * FROM integration_links WHERE id = %s", (link_id,)))


@bp.get("/tickets/<int:ticket_id>/links")
@auth_required
def list_links(user, ticket_id):
    ticket = get_tx().one("SELECT * FROM tickets WHERE id = %s", (ticket_id,))
    if ticket is None:
        raise ApiError(404, "NOT_FOUND", "Ticket not found")
    if not _can_view(user, ticket):
        raise ApiError(403, "FORBIDDEN", "You cannot view this ticket")
    rows = get_tx().all("SELECT * FROM integration_links WHERE ticket_id = %s ORDER BY id", (ticket_id,))
    return jsonify({"items": [_link_out(r) for r in rows]})
