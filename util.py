"""Request parsing and validation helpers. Every invalid input raises ApiError(422) or ApiError(400)."""
from datetime import datetime, timezone

from flask import request

from .errors import ApiError


def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "BAD_JSON", "Request body must be a JSON object")
    return body


def parse_datetime(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(422, "VALIDATION_ERROR", f"{field} must be an ISO-8601 datetime", {"field": field})
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", f"{field} must be an ISO-8601 datetime", {"field": field})
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def require_str(body, field, min_len=1, max_len=255, required=True):
    value = body.get(field)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        if required:
            raise ApiError(422, "VALIDATION_ERROR", f"{field} is required", {"field": field})
        return ""
    if not isinstance(value, str):
        raise ApiError(422, "VALIDATION_ERROR", f"{field} must be text", {"field": field})
    value = value.strip()
    if not (min_len <= len(value) <= max_len):
        raise ApiError(422, "VALIDATION_ERROR", f"{field} must be {min_len} to {max_len} characters", {"field": field})
    return value


def require_int(body, field, minimum=1, maximum=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(422, "VALIDATION_ERROR", f"{field} must be an integer", {"field": field})
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError(422, "VALIDATION_ERROR", f"{field} is out of range", {"field": field})
    return value


def require_number(body, field):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(422, "VALIDATION_ERROR", f"{field} must be a number", {"field": field})
    return float(value)


def require_choice(body, field, choices):
    value = body.get(field)
    if value not in choices:
        raise ApiError(422, "VALIDATION_ERROR", f"{field} must be one of {', '.join(choices)}", {"field": field})
    return value
