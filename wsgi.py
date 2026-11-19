"""WSGI entry point used by gunicorn inside the backend containers."""
from app import create_app

app = create_app()
