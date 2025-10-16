"""Routes for the roles admin module."""

from flask import abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from admin_panel.roles import bp
from admin_panel.roles.forms import RoleForm
from admin_panel.roles.models import Role
from models import Role as UserRole, SessionLocal


@bp.before_request
def ensure_admin_access():
    """Block non-admins before reaching route handlers."""
    if not current_user.is_authenticated:
        login_manager = current_app.login_manager
        return login_manager.unauthorized()
    if current_user.role != UserRole.admin:
        abort(403)


@bp.route("/", methods=["GET"])
def list_roles():
    db = SessionLocal()
    try:
        roles = db.execute(select(Role).order_by(Role.name.asc())).scalars().all()
    finally:
        db.close()
    return render_template("roles/list.html", roles=roles)


@bp.route("/create", methods=["GET", "POST"])
def create_role():
    form = RoleForm()
    if form.validate_on_submit():
        db = SessionLocal()
        try:
            description = (form.description.data or "").strip() or None
            role = Role(name=form.name.data.strip(), description=description)
            db.add(role)
            db.commit()
            flash("Role created successfully.", "ok")
            return redirect(url_for("admin_roles.list_roles"))
        except IntegrityError:
            db.rollback()
            form.name.errors.append("A role with this name already exists.")
        finally:
            db.close()
    return render_template("roles/form.html", form=form, form_action=url_for("admin_roles.create_role"), title="Create Role")


@bp.route("/<int:role_id>/edit", methods=["GET", "POST"])
def edit_role(role_id: int):
    db = SessionLocal()
    try:
        role = db.get(Role, role_id)
        if not role:
            flash("Role not found.", "error")
            return redirect(url_for("admin_roles.list_roles"))

        form = RoleForm(obj=role)
        if form.validate_on_submit():
            role.name = form.name.data.strip()
            role.description = (form.description.data or "").strip() or None
            try:
                db.commit()
                flash("Role updated successfully.", "ok")
                return redirect(url_for("admin_roles.list_roles"))
            except IntegrityError:
                db.rollback()
                form.name.errors.append("A role with this name already exists.")
        return render_template(
            "roles/form.html",
            form=form,
            form_action=url_for("admin_roles.edit_role", role_id=role_id),
            title="Edit Role",
            role=role,
        )
    finally:
        db.close()


@bp.route("/<int:role_id>/delete", methods=["POST"])
def delete_role(role_id: int):
    db = SessionLocal()
    role = db.get(Role, role_id)
    if not role:
        db.close()
        flash("Role not found.", "error")
        return redirect(url_for("admin_roles.list_roles"))
    db.delete(role)
    db.commit()
    db.close()
    flash("Role deleted.", "ok")
    return redirect(url_for("admin_roles.list_roles"))
