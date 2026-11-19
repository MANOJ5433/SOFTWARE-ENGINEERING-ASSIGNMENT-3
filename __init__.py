"""Application factory for the Smart Campus Facility and Maintenance Platform."""
from flask import Flask

from .blueprint import bp
from .config import Config
from .db import close_tx
from .errors import register_error_handlers

# Importing these modules registers their routes on the blueprint.
from . import routes_bookings, routes_core, routes_tickets  # noqa: F401


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    register_error_handlers(app)
    app.teardown_appcontext(close_tx)

    @app.after_request
    def tag_instance(response):
        # Lets load-balancing tests see which backend instance served each request.
        response.headers["X-Served-By"] = app.config["INSTANCE_NAME"]
        return response

    app.register_blueprint(bp, url_prefix="/api")
    return app
