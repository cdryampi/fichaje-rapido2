"""Routes for managing admin areas and groups."""

from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from admin_panel.areas import bp
from admin_panel.areas.forms import AreaForm, GroupForm
from admin_panel.areas.models import AdminArea, AdminGroup
from admin_panel.employees.models import Employee
from models import Role as UserRole, SessionLocal


@bp.before_request
def ensure_admin_access():
    """Allow only authenticated admins."""
    if not current_user.is_authenticated:
        login_manager = current_app.login_manager
        return login_manager.unauthorized()
    if current_user.role != UserRole.admin:
        abort(403)


@bp.route("/", methods=["GET"])
def list_areas():
    db = SessionLocal()
    try:
        areas = db.execute(select(AdminArea).order_by(AdminArea.name.asc())).scalars().all()
        area_form = AreaForm()
        return render_template("areas/list.html", areas=areas, area_form=area_form)
    finally:
        db.close()


@bp.route("/create", methods=["POST"])
def create_area():
    form = AreaForm()
    if not form.validate_on_submit():
        flash("Please correct the errors in the form.", "error")
        return redirect(url_for("admin_areas.list_areas"))

    db = SessionLocal()
    try:
        existing = db.execute(
            select(AdminArea).where(AdminArea.name == form.name.data.strip())
        ).scalar_one_or_none()
        if existing:
            flash("An area with this name already exists.", "error")
            return redirect(url_for("admin_areas.list_areas"))

        description = (form.description.data or "").strip() or None
        area = AdminArea(name=form.name.data.strip(), description=description)
        db.add(area)
        db.commit()
        flash("Area created successfully.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_areas.list_areas"))


@bp.route("/<int:area_id>/edit", methods=["GET", "POST"])
def edit_area(area_id: int):
    db = SessionLocal()
    try:
        area = db.get(AdminArea, area_id)
        if not area:
            flash("Area not found.", "error")
            return redirect(url_for("admin_areas.list_areas"))

        form = AreaForm(obj=area)
        if form.validate_on_submit():
            candidate = form.name.data.strip()
            duplicate = (
                db.execute(
                    select(AdminArea).where(AdminArea.id != area.id, AdminArea.name == candidate)
                ).scalar_one_or_none()
            )
            if duplicate:
                form.name.errors.append("Another area with this name already exists.")
            else:
                area.name = candidate
                area.description = (form.description.data or "").strip() or None
                db.commit()
                flash("Area updated successfully.", "ok")
                return redirect(url_for("admin_areas.list_areas"))
        return render_template("areas/edit.html", form=form, area=area)
    finally:
        db.close()


@bp.route("/<int:area_id>/delete", methods=["POST"])
def delete_area(area_id: int):
    db = SessionLocal()
    try:
        area = db.get(AdminArea, area_id)
        if not area:
            flash("Area not found.", "error")
            return redirect(url_for("admin_areas.list_areas"))

        # Detach employees before deleting area to keep data consistent.
        group_ids = [g.id for g in area.groups]
        conditions = [Employee.area_id == area.id]
        if group_ids:
            conditions.append(Employee.group_id.in_(group_ids))
        employees = db.execute(select(Employee).where(or_(*conditions))).scalars().all()
        for employee in employees:
            employee.area_id = None
            employee.group_id = None

        db.delete(area)
        db.commit()
        flash("Area deleted successfully.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_areas.list_areas"))


@bp.route("/<int:area_id>/groups", methods=["GET"])
def list_groups(area_id: int):
    db = SessionLocal()
    try:
        area = db.get(AdminArea, area_id)
        if not area:
            flash("Area not found.", "error")
            return redirect(url_for("admin_areas.list_areas"))

        groups = db.execute(
            select(AdminGroup).where(AdminGroup.area_id == area.id).order_by(AdminGroup.name.asc())
        ).scalars().all()
        return render_template("groups/list.html", area=area, groups=groups)
    finally:
        db.close()


def _build_group_form(db, group=None, area_hint=None):
    """Create a group form with populated choices."""
    form = GroupForm(obj=group)
    areas = db.execute(select(AdminArea).order_by(AdminArea.name.asc())).scalars().all()
    form.area_id.choices = [(a.id, a.name) for a in areas]
    if group:
        form.area_id.data = group.area_id
    elif area_hint and area_hint in [choice[0] for choice in form.area_id.choices]:
        form.area_id.data = area_hint
    return form


@bp.route("/groups/create", methods=["GET", "POST"])
def create_group():
    db = SessionLocal()
    try:
        requested_area = request.args.get("area_id", type=int)
        form = _build_group_form(db, area_hint=requested_area)
        if not form.area_id.choices:
            flash("Create an area before adding groups.", "warn")
            return redirect(url_for("admin_areas.list_areas"))

        if form.validate_on_submit():
            target_area = db.get(AdminArea, form.area_id.data)
            if not target_area:
                form.area_id.errors.append("Selected area does not exist.")
            else:
                description = (form.description.data or "").strip() or None
                group = AdminGroup(name=form.name.data.strip(), description=description, area_id=target_area.id)
                db.add(group)
                db.commit()
                flash("Group created successfully.", "ok")
                return redirect(url_for("admin_areas.list_groups", area_id=group.area_id))
        back_target = form.area_id.data or requested_area
        back_url = (
            url_for("admin_areas.list_groups", area_id=back_target)
            if back_target
            else url_for("admin_areas.list_areas")
        )
        return render_template("groups/edit.html", form=form, title="Create group", back_url=back_url)
    finally:
        db.close()


@bp.route("/groups/<int:group_id>/edit", methods=["GET", "POST"])
def edit_group(group_id: int):
    db = SessionLocal()
    try:
        group = db.get(AdminGroup, group_id)
        if not group:
            flash("Group not found.", "error")
            return redirect(url_for("admin_areas.list_areas"))

        form = _build_group_form(db, group=group)
        if form.validate_on_submit():
            target_area = db.get(AdminArea, form.area_id.data)
            if not target_area:
                form.area_id.errors.append("Selected area does not exist.")
            else:
                previous_area_id = group.area_id
                description = (form.description.data or "").strip() or None
                group.name = form.name.data.strip()
                group.description = description
                group.area_id = target_area.id
                try:
                    if previous_area_id != group.area_id:
                        employees = db.execute(
                            select(Employee).where(Employee.group_id == group.id)
                        ).scalars().all()
                        for employee in employees:
                            employee.area_id = group.area_id
                    db.commit()
                    flash("Group updated successfully.", "ok")
                    return redirect(url_for("admin_areas.list_groups", area_id=group.area_id))
                except IntegrityError:
                    db.rollback()
                    form.name.errors.append("Unable to update the group. Please retry.")
        back_url = url_for("admin_areas.list_groups", area_id=group.area_id)
        return render_template("groups/edit.html", form=form, group=group, title="Edit group", back_url=back_url)
    finally:
        db.close()


@bp.route("/groups/<int:group_id>/delete", methods=["POST"])
def delete_group(group_id: int):
    db = SessionLocal()
    try:
        group = db.get(AdminGroup, group_id)
        if not group:
            flash("Group not found.", "error")
            return redirect(url_for("admin_areas.list_areas"))

        # Detach employees belonging to the group.
        employees = db.execute(
            select(Employee).where(Employee.group_id == group.id)
        ).scalars().all()
        for employee in employees:
            employee.group_id = None
            if employee.area_id == group.area_id:
                employee.area_id = None

        area_id = group.area_id
        db.delete(group)
        db.commit()
        flash("Group deleted.", "ok")
        return redirect(url_for("admin_areas.list_groups", area_id=area_id))
    finally:
        db.close()
