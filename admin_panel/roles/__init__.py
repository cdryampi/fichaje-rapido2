"""Roles blueprint package."""

from flask import Blueprint

bp = Blueprint(
    "admin_roles",
    __name__,
    url_prefix="/admin-panel/roles",
    template_folder="templates",
)

from . import routes  # noqa: E402,F401

__all__ = ["bp"]
