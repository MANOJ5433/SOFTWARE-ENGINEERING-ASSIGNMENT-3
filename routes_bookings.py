"""Facility booking endpoints: create (idempotent, overlap-checked) and the approval state machine."""
from datetime import datetime, timezone

from flask import current_app, jsonify, request

from .audit import record
from .auth import auth_required
from .blueprint import bp
from .constants import (
    BOOKING_ACTION_ROLES,
    BOOKING_TRANSITIONS,
    REQUESTER_ACTIONS,
)
from .db import get_tx, now_iso
from .errors import ApiError
from .idempotency import respond_idempotent
from .serializers import booking_out
from .util import json_body, parse_datetime, require_int, require_str

BOOKING_SELECT = (
    "SELECT b.id, b.facility_id, b.requester_id, b.start_time, b.end_time, b.purpose, b.attendees, "
    "b.status, b.decision_note, b.version, b.created_at, b.updated_at, "
    "f.code AS facility_code, f.name AS facility_name, u.username AS requester_username "
    "FROM bookings b JOIN facilities f ON f.id = b.facility_id JOIN users u ON u.id = b.requester_id"
)
ACTIVE_SQL = "('REQUESTED', 'APPROVED', 'CONFIRMED', 'IN_USE')"


def _fetch(tx, booking_id):
    return booking_out(tx.one(BOOKING_SELECT + " WHERE b.id = %s", (booking_id,)))


@bp.get("/bookings")
@auth_required
def list_bookings(user):
    sql = BOOKING_SELECT + " WHERE 1 = 1"
    params = []
    if user["role"] in ("student", "faculty"):
        sql += " AND b.requester_id = %s"  # students and faculty only see their own bookings
        params.append(user["id"])
    status = request.args.get("status")
    if status:
        sql += " AND b.status = %s"
        params.append(status)
    sql += " ORDER BY b.start_time, b.id"
    return jsonify({"items": [booking_out(r) for r in get_tx().all(sql, params)]})


@bp.get("/bookings/<int:booking_id>")
@auth_required
def get_booking(user, booking_id):
    row = get_tx().one(BOOKING_SELECT + " WHERE b.id = %s", (booking_id,))
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Booking not found")
    if user["role"] in ("student", "faculty") and row["requester_id"] != user["id"]:
        raise ApiError(403, "FORBIDDEN", "You can only view your own bookings")
    return jsonify(booking_out(row))


@bp.post("/bookings")
@auth_required
def create_booking(user):
    body = json_body()
    return respond_idempotent("bookings.create", user, body, lambda tx: _create_booking(tx, user, body))


def _create_booking(tx, user, body):
    if user["role"] == "sensor":
        raise ApiError(403, "FORBIDDEN", "Sensor gateways cannot create bookings")
    facility_id = require_int(body, "facility_id")
    start = parse_datetime(body.get("start_time"), "start_time")
    end = parse_datetime(body.get("end_time"), "end_time")
    purpose = require_str(body, "purpose", 3, 200)
    attendees = require_int(body, "attendees", 1, 5000)

    if end <= start:
        raise ApiError(422, "VALIDATION_ERROR", "end_time must be after start_time", {"field": "end_time"})
    if (end - start).total_seconds() / 3600 > current_app.config["BOOKING_MAX_HOURS"]:
        raise ApiError(422, "VALIDATION_ERROR", "A booking may not exceed the maximum duration", {"field": "end_time"})
    if start <= datetime.now(timezone.utc):
        raise ApiError(422, "VALIDATION_ERROR", "start_time must be in the future", {"field": "start_time"})

    # Lock the facility row: concurrent bookings of the SAME facility queue here, so the overlap check
    # below always sees every committed reservation. The database exclusion constraint is a second guard.
    facility = tx.one("SELECT * FROM facilities WHERE id = %s AND active = %s", (facility_id, True), lock=True)
    if facility is None:
        raise ApiError(404, "FACILITY_NOT_FOUND", "Facility not found or inactive")
    if facility["restricted"] and user["role"] == "student":
        raise ApiError(403, "ROLE_RESTRICTED", "Students cannot book restricted facilities")
    if attendees > facility["capacity"]:
        raise ApiError(422, "CAPACITY_EXCEEDED", f"{facility['code']} holds {facility['capacity']} people",
                       {"field": "attendees"})

    clash = tx.one(
        "SELECT id, start_time, end_time FROM bookings WHERE facility_id = %s "
        f"AND status IN {ACTIVE_SQL} AND start_time < %s AND end_time > %s",
        (facility_id, end.isoformat(), start.isoformat()),
    )
    if clash is not None:
        raise ApiError(409, "BOOKING_OVERLAP", "The facility is already reserved for an overlapping time",
                       {"conflicting_booking_id": clash["id"]})

    status = "REQUESTED" if facility["restricted"] else "CONFIRMED"
    now = now_iso()
    booking_id = tx.insert(
        "INSERT INTO bookings (facility_id, requester_id, start_time, end_time, purpose, attendees, status, "
        "last_actor_id, version, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)",
        (facility_id, user["id"], start.isoformat(), end.isoformat(), purpose, attendees, status,
         user["id"], now, now),
    )
    record(tx, "booking", booking_id, "created", user["id"], {"status": status, "facility": facility["code"]})
    return 201, _fetch(tx, booking_id)


@bp.post("/bookings/<int:booking_id>/transition")
@auth_required
def transition_booking(user, booking_id):
    body = json_body()
    endpoint = f"bookings.transition.{booking_id}"
    return respond_idempotent(endpoint, user, body, lambda tx: _transition_booking(tx, user, booking_id, body))


def _transition_booking(tx, user, booking_id, body):
    action = require_str(body, "action", 3, 20)
    version = require_int(body, "version", 1)
    note = require_str(body, "note", 0, 200, required=False) or None
    if action not in BOOKING_ACTION_ROLES:
        raise ApiError(422, "VALIDATION_ERROR", "Unknown action", {"field": "action", "allowed": sorted(BOOKING_ACTION_ROLES)})

    row = tx.one("SELECT * FROM bookings WHERE id = %s", (booking_id,), lock=True)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Booking not found")
    if row["version"] != version:
        raise ApiError(409, "VERSION_CONFLICT", "The booking was changed by someone else; reload and retry",
                       {"current_version": row["version"], "current_status": row["status"]})

    next_status = BOOKING_TRANSITIONS.get((row["status"], action))
    if next_status is None:
        raise ApiError(409, "INVALID_TRANSITION", f"Cannot '{action}' a booking that is {row['status']}",
                       {"current_status": row["status"]})

    is_requester = row["requester_id"] == user["id"] and action in REQUESTER_ACTIONS
    if user["role"] not in BOOKING_ACTION_ROLES[action] and not is_requester:
        raise ApiError(403, "FORBIDDEN", f"Role '{user['role']}' cannot '{action}' this booking")

    changed = tx.execute(
        "UPDATE bookings SET status = %s, decision_note = %s, last_actor_id = %s, version = version + 1, "
        "updated_at = %s WHERE id = %s AND version = %s",
        (next_status, note, user["id"], now_iso(), booking_id, version),
    )
    if changed != 1:
        raise ApiError(409, "VERSION_CONFLICT", "The booking was changed by someone else; reload and retry")
    record(tx, "booking", booking_id, action, user["id"], {"from": row["status"], "to": next_status, "note": note})
    return 200, _fetch(tx, booking_id)
