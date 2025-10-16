"""Employees blueprint package."""

from flask import Blueprint

bp = Blueprint(
    "admin_employees",
    __name__,
    url_prefix="/admin-panel/employees",
    template_folder="templates",
)

from . import routes  # noqa: E402,F401

__all__ = ["bp"]
