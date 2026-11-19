"""Bearer-token authentication and server-side role checks.

Tokens are never stored in the database: only their SHA-256 hash is kept in users.token_hash.
"""
import hashlib
from functools import wraps

from flask import g, request

from .db import get_tx
from .errors import ApiError


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate():
    if "user" in g:
        return g.user
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or len(header) <= 7:
        raise ApiError(401, "UNAUTHENTICATED", "Send 'Authorization: Bearer <token>'")
    row = get_tx().one(
        "SELECT id, username, full_name, role, active FROM users WHERE token_hash = %s",
        (hash_token(header[7:].strip()),),
    )
    if row is None or not row["active"]:
        raise ApiError(401, "UNAUTHENTICATED", "Token is not recognised or the account is disabled")
    g.user = row
    return row


def auth_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        return view(authenticate(), *args, **kwargs)

    return wrapper


def require_roles(user, roles):
    if user["role"] not in roles:
        raise ApiError(403, "FORBIDDEN", f"Role '{user['role']}' is not permitted to perform this action")
