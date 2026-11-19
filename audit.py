"""Append-only audit trail. Every state-changing operation writes one row in the same transaction."""
import json

from .db import now_iso


def record(tx, entity_type, entity_id, action, actor_id, detail=None):
    tx.execute(
        "INSERT INTO audit_events (entity_type, entity_id, action, actor_id, detail, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (entity_type, entity_id, action, actor_id, json.dumps(detail or {}, sort_keys=True), now_iso()),
    )
