"""Health, identity, facilities, users, dashboard and audit endpoints."""
import json
from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, request

from .audit import record
from .auth import auth_required, require_roles
from .blueprint import bp
from .constants import APPROVER_ROLES, MANAGER_ROLES
from .db import get_tx, now_iso, to_iso, write
from .errors import ApiError
from .serializers import facility_out
from .util import json_body, require_int, require_str


@bp.get("/health")
def health():
    get_tx().one("SELECT 1 AS ok")
    return jsonify({"status": "ok", "instance": current_app.config["INSTANCE_NAME"], "database": "ok"})


@bp.get("/me")
@auth_required
def me(user):
    return jsonify({"id": user["id"], "username": user["username"], "full_name": user["full_name"], "role": user["role"]})


@bp.get("/facilities")
@auth_required
def list_facilities(user):
    rows = get_tx().all("SELECT * FROM facilities WHERE active = %s ORDER BY code", (True,))
    return jsonify({"items": [facility_out(r) for r in rows]})


@bp.post("/facilities")
@auth_required
def create_facility(user):
    require_roles(user, MANAGER_ROLES)
    body = json_body()
    code = require_str(body, "code", 2, 20).upper()
    name = require_str(body, "name", 3, 120)
    location = require_str(body, "location", 3, 120)
    capacity = require_int(body, "capacity", 1, 5000)
    restricted = bool(body.get("restricted", False))

    def work(tx):
        fid = tx.insert(
            "INSERT INTO facilities (code, name, location, capacity, restricted, active, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (code, name, location, capacity, restricted, True, now_iso()),
        )
        record(tx, "facility", fid, "created", user["id"], {"code": code})
        return facility_out(tx.one("SELECT * FROM facilities WHERE id = %s", (fid,)))

    return jsonify(write(work)), 201


@bp.patch("/facilities/<int:facility_id>")
@auth_required
def update_facility(user, facility_id):
    require_roles(user, MANAGER_ROLES)
    body = json_body()
    allowed = {"name", "location", "capacity", "restricted", "active"}
    changes = {k: v for k, v in body.items() if k in allowed}
    if not changes:
        raise ApiError(422, "VALIDATION_ERROR", "Provide at least one of: " + ", ".join(sorted(allowed)))
    if "capacity" in changes:
        require_int(changes, "capacity", 1, 5000)

    def work(tx):
        if tx.one("SELECT id FROM facilities WHERE id = %s", (facility_id,)) is None:
            raise ApiError(404, "NOT_FOUND", "Facility not found")
        for field, value in changes.items():
            if field in ("restricted", "active"):
                value = bool(value)
            tx.execute(f"UPDATE facilities SET {field} = %s WHERE id = %s", (value, facility_id))
        record(tx, "facility", facility_id, "updated", user["id"], {"fields": sorted(changes)})
        return facility_out(tx.one("SELECT * FROM facilities WHERE id = %s", (facility_id,)))

    return jsonify(write(work))


@bp.get("/facilities/<int:facility_id>/calendar")
@auth_required
def facility_calendar(user, facility_id):
    raw = request.args.get("date", "")
    try:
        day = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", "date query parameter must be YYYY-MM-DD", {"field": "date"})
    day_end = day + timedelta(days=1)
    rows = get_tx().all(
        "SELECT b.id, b.start_time, b.end_time, b.status, b.purpose, u.username AS requester_username "
        "FROM bookings b JOIN users u ON u.id = b.requester_id "
        "WHERE b.facility_id = %s AND b.status <> %s AND b.start_time < %s AND b.end_time > %s "
        "ORDER BY b.start_time",
        (facility_id, "CANCELLED", day_end.isoformat(), day.isoformat()),
    )
    items = [
        {
            "booking_id": r["id"],
            "start_time": to_iso(r["start_time"]),
            "end_time": to_iso(r["end_time"]),
            "status": r["status"],
            "purpose": r["purpose"],
            "requester_username": r["requester_username"],
        }
        for r in rows
    ]
    return jsonify({"facility_id": facility_id, "date": raw, "items": items})


@bp.get("/users")
@auth_required
def list_users(user):
    require_roles(user, MANAGER_ROLES)
    role = request.args.get("role")
    sql = "SELECT id, username, full_name, role FROM users WHERE active = %s"
    params = [True]
    if role:
        sql += " AND role = %s"
        params.append(role)
    return jsonify({"items": get_tx().all(sql + " ORDER BY username", params)})


@bp.get("/dashboard")
@auth_required
def dashboard(user):
    tx = get_tx()
    booking_counts = {r["status"]: r["n"] for r in tx.all("SELECT status, COUNT(*) AS n FROM bookings GROUP BY status")}
    ticket_counts = {r["status"]: r["n"] for r in tx.all("SELECT status, COUNT(*) AS n FROM tickets GROUP BY status")}
    priority_counts = {r["priority"]: r["n"] for r in tx.all(
        "SELECT priority, COUNT(*) AS n FROM tickets WHERE status <> %s GROUP BY priority", ("CLOSED",))}
    breached = tx.one(
        "SELECT COUNT(*) AS n FROM tickets WHERE status <> %s AND sla_due_at < %s", ("CLOSED", now_iso()))["n"]
    return jsonify({
        "bookings_by_status": booking_counts,
        "tickets_by_status": ticket_counts,
        "open_tickets_by_priority": priority_counts,
        "open_tickets_past_sla": breached,
        "generated_at": now_iso(),
        "instance": current_app.config["INSTANCE_NAME"],
    })


@bp.get("/audit")
@auth_required
def audit(user):
    require_roles(user, APPROVER_ROLES)
    sql = "SELECT a.id, a.entity_type, a.entity_id, a.action, a.actor_id, a.detail, a.created_at, u.username AS actor_username " \
          "FROM audit_events a LEFT JOIN users u ON u.id = a.actor_id WHERE 1 = 1"
    params = []
    if request.args.get("entity_type"):
        sql += " AND a.entity_type = %s"
        params.append(request.args["entity_type"])
    if request.args.get("entity_id"):
        sql += " AND a.entity_id = %s"
        if not request.args["entity_id"].isdigit():
            raise ApiError(422, "VALIDATION_ERROR", "entity_id must be an integer", {"field": "entity_id"})
        params.append(int(request.args["entity_id"]))
    sql += " ORDER BY a.id DESC LIMIT 200"
    items = []
    for r in get_tx().all(sql, params):
        items.append({
            "id": r["id"],
            "entity_type": r["entity_type"],
            "entity_id": r["entity_id"],
            "action": r["action"],
            "actor_username": r["actor_username"],
            "detail": json.loads(r["detail"]),
            "created_at": to_iso(r["created_at"]),
        })
    return jsonify({"items": items})
