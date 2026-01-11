"""Calendars blueprint package."""

from flask import Blueprint

bp = Blueprint(
    "admin_calendars",
    __name__,
    url_prefix="/admin/calendars",
    template_folder="templates",
)

from . import routes  # noqa: E402,F401

__all__ = ["bp"]
