"""Schedules blueprint package."""

from flask import Blueprint

bp = Blueprint(
    "admin_schedules",
    __name__,
    url_prefix="/admin/schedules",
    template_folder="templates",
)

from . import routes  # noqa: E402,F401

__all__ = ["bp"]
