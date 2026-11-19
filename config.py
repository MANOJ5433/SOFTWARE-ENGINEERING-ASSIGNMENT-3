"""All runtime configuration comes from environment variables (see .env.example)."""
import os


class Config:
    DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://campus:campus@localhost:5432/campus")
    INSTANCE_NAME = os.environ.get("INSTANCE_NAME", "backend-local")
    # When true, the simulated issue tracker refuses requests; links are stored as PENDING and can be retried.
    SIMULATE_TRACKER_OUTAGE = os.environ.get("SIMULATE_TRACKER_OUTAGE", "false").lower() == "true"
    BOOKING_MAX_HOURS = float(os.environ.get("BOOKING_MAX_HOURS", "8"))
    TEMPERATURE_THRESHOLD_C = float(os.environ.get("TEMPERATURE_THRESHOLD_C", "30"))
    SMOKE_THRESHOLD = float(os.environ.get("SMOKE_THRESHOLD", "0.5"))
