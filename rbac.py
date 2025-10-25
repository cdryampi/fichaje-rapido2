from functools import wraps
from flask import abort
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import Session
from models import SessionLocal, User, Role, TimeEntry, GuestAccess


def can_view_user(requester: User, target: User, db: Session = None) -> bool:
    if requester.role in (Role.admin, Role.rrhh):
        return True
    if target.supervisor_id and target.supervisor_id == requester.id:
        return True
    if requester.role == Role.employee:
        return requester.id == target.id
    if requester.role == Role.responsable:
        return requester.group_id and requester.group_id == target.group_id
    if requester.role == Role.cap_area:
        return requester.area_id and requester.area_id == target.area_id
    if requester.role == Role.invitado:
        # Solo si hay GuestAccess
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            ga = db.execute(
                select(GuestAccess).where(
                    GuestAccess.guest_user_id == requester.id,
                    GuestAccess.target_user_id == target.id,
                )
            ).scalar_one_or_none()
            return ga is not None
        finally:
            if close_db:
                db.close()
    return False


def can_edit_entries(requester: User, target: User) -> bool:
    # Invitado nunca edita
    if requester.role == Role.invitado:
        return False
    if requester.role in (Role.admin, Role.rrhh):
        return True
    if target.supervisor_id and target.supervisor_id == requester.id:
        return True
    if requester.role == Role.employee:
        # Un empleado puede proponer cambios sobre sus propias entradas
        return requester.id == target.id
    if requester.role == Role.responsable:
        return requester.group_id and requester.group_id == target.group_id
    if requester.role == Role.cap_area:
        return requester.area_id and requester.area_id == target.area_id
    return False


def require_view_user(user_id_param: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            db = SessionLocal()
            try:
                target = db.get(User, int(kwargs[user_id_param]))
                if not target or not can_view_user(current_user, target):
                    abort(403)
                return fn(*args, **kwargs)
            finally:
                db.close()
        return wrapper
    return decorator


def require_edit_entry(entry_id_param: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            db = SessionLocal()
            try:
                entry = db.get(TimeEntry, int(kwargs[entry_id_param]))
                if not entry:
                    abort(404)
                target = db.get(User, entry.user_id)
                if not can_edit_entries(current_user, target):
                    abort(403)
                return fn(*args, **kwargs)
            finally:
                db.close()
        return wrapper
    return decorator

