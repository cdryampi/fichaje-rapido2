"""Shared helpers for admin panel authentication and authorization."""

from functools import wraps
from typing import Callable, TypeVar, cast

from flask import abort, current_app
from flask_login import current_user

from models import Role as UserRole  # Existing enum for user roles

F = TypeVar("F", bound=Callable[..., object])


def admin_required(view_func: F) -> F:
    """Ensure the current user is authenticated and has admin role."""

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            login_manager = current_app.login_manager
            return login_manager.unauthorized()
        if current_user.role != UserRole.admin:
            abort(403)
        return view_func(*args, **kwargs)

    return cast(F, wrapper)
