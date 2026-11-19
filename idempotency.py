"""Idempotent handling of create and change requests.

Protocol: the client sends an `Idempotency-Key` header (8-128 chars) and retries with the SAME key
and body after a timeout. The key row is inserted inside the same transaction as the work, and it
has a UNIQUE constraint. Therefore:
  * a retry of a completed request returns the stored response (header Idempotent-Replayed: true);
  * two simultaneous requests with the same key cannot both perform the work: the second blocks on
    the unique index (PostgreSQL) or on the write lock (SQLite), then replays the stored response;
  * reusing a key with a different body returns 422 IDEMPOTENCY_KEY_REUSED;
  * a failed request rolls back, including its key row, so the client may retry with the same key.
"""
import hashlib
import json

from flask import jsonify, request

from .db import INTEGRITY_ERRORS, get_tx, now_iso, translate_integrity
from .errors import ApiError


def _digest(endpoint, body):
    raw = json.dumps({"endpoint": endpoint, "body": body}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_idempotent(endpoint, user, body, handler):
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not 8 <= len(key) <= 128:
        raise ApiError(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Send an Idempotency-Key header of 8 to 128 characters with every create or change request",
        )
    scope = f"{user['id']}:{key}"
    digest = _digest(endpoint, body)
    tx = get_tx()
    tx.begin()
    try:
        tx.execute(
            "INSERT INTO idempotency_keys (scope_key, endpoint, request_hash, created_at) VALUES (%s, %s, %s, %s)",
            (scope, endpoint, digest, now_iso()),
        )
    except INTEGRITY_ERRORS:
        tx.rollback()
        return _replay(scope, digest)

    try:
        status, payload = handler(tx)
        tx.execute(
            "UPDATE idempotency_keys SET response_status = %s, response_body = %s WHERE scope_key = %s",
            (status, json.dumps(payload), scope),
        )
        tx.commit()
    except Exception as exc:
        tx.rollback()
        if isinstance(exc, INTEGRITY_ERRORS):
            raise translate_integrity(exc) from exc
        raise
    return status, payload, False


def _replay(scope, digest):
    row = get_tx().one(
        "SELECT request_hash, response_status, response_body FROM idempotency_keys WHERE scope_key = %s",
        (scope,),
    )
    if row is None:
        raise ApiError(409, "IDEMPOTENT_REQUEST_IN_PROGRESS", "The original request is still in progress; retry shortly")
    if row["request_hash"].strip() != digest:
        raise ApiError(422, "IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was already used for a different request")
    if row["response_status"] is None:
        raise ApiError(409, "IDEMPOTENT_REQUEST_IN_PROGRESS", "The original request is still in progress; retry shortly")
    return row["response_status"], json.loads(row["response_body"]), True


def respond_idempotent(endpoint, user, body, handler):
    status, payload, replayed = run_idempotent(endpoint, user, body, handler)
    return jsonify(payload), status, {"Idempotent-Replayed": "true" if replayed else "false"}
