"""Uniform JSON error responses: {"error": {"code", "message", "details"}}."""
import logging

from flask import jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger("campus")


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def _body(code, message, details=None):
    return jsonify({"error": {"code": code, "message": message, "details": details or {}}})


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return _body(err.code, err.message, err.details), err.status

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(err.code, "HTTP_ERROR")
            return _body(code, err.description or err.name), err.code
        log.exception("Unhandled error: %s", err)
        return _body("INTERNAL_ERROR", "An unexpected error occurred; the change was not applied"), 500
