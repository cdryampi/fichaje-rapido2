"""Routes for the employees admin module."""

import json
from typing import Dict, List

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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from admin_panel.employees import bp
from admin_panel.employees.forms import EmployeeFilterForm, EmployeeForm
from admin_panel.employees.models import Employee
from admin_panel.roles.models import Role
from admin_panel.areas.models import AdminArea, AdminGroup
from models import Role as UserRole, SessionLocal


def _group_options_by_area(groups: List[AdminGroup]) -> Dict[int, List[Dict[str, str]]]:
    grouped: Dict[int, List[Dict[str, str]]] = {}
    for group in groups:
        grouped.setdefault(group.area_id, []).append({"id": group.id, "name": group.name})
    return grouped


@bp.before_request
def ensure_admin_access():
    """Block non-admin users before reaching route handlers."""
    if not current_user.is_authenticated:
        login_manager = current_app.login_manager
        return login_manager.unauthorized()
    if current_user.role != UserRole.admin:
        abort(403)


def _load_reference_data(db):
    roles = db.execute(select(Role).order_by(Role.name.asc())).scalars().all()
    areas = db.execute(select(AdminArea).order_by(AdminArea.name.asc())).scalars().all()
    groups = db.execute(select(AdminGroup).order_by(AdminGroup.name.asc())).scalars().all()
    return roles, areas, groups


def _set_form_choices(
    form: EmployeeForm, roles, areas, groups, selected_area_id=None, selected_group_id=None
):
    form.role_id.choices = [(r.id, r.name) for r in roles]
    form.area_id.choices = [(0, "Selecciona un area")] + [(a.id, a.name) for a in areas]
    if selected_area_id:
        allowed_groups = [g for g in groups if g.area_id == selected_area_id]
    elif selected_group_id:
        allowed_groups = [g for g in groups if g.id == selected_group_id]
    else:
        allowed_groups = []
    form.group_id.choices = [(0, "Selecciona un grupo")] + [(g.id, g.name) for g in allowed_groups]
    if selected_area_id and not allowed_groups:
        form.group_id.data = 0
    form.is_active.render_kw = {"class": "form-check-input"}


def _set_filter_choices(form: EmployeeFilterForm, roles, areas, groups):
    form.role_id.choices = [(0, "Todos los roles")] + [(r.id, r.name) for r in roles]
    form.area_id.choices = [(0, "Todas las areas")] + [(a.id, a.name) for a in areas]
    form.group_id.choices = [(0, "Todos los grupos")] + [(g.id, g.name) for g in groups]


@bp.route("/", methods=["GET"])
def list_employees():
    db = SessionLocal()
    try:
        roles, areas, groups = _load_reference_data(db)
        filter_form = EmployeeFilterForm(meta={"csrf": False})
        filter_form.process(request.args)
        _set_filter_choices(filter_form, roles, areas, groups)

        query = select(Employee).order_by(Employee.name.asc())
        if filter_form.role_id.data:
            query = query.where(Employee.role_id == filter_form.role_id.data)
        if filter_form.area_id.data:
            query = query.where(Employee.area_id == filter_form.area_id.data)
        if filter_form.group_id.data:
            query = query.where(Employee.group_id == filter_form.group_id.data)

        employees = db.execute(query).scalars().all()

        grouped = _group_options_by_area(groups)
        return render_template(
            "employees/list.html",
            employees=employees,
            filter_form=filter_form,
            roles=roles,
            areas=areas,
            groups=groups,
            group_map_json=json.dumps(grouped, ensure_ascii=False),
        )
    finally:
        db.close()


@bp.route("/create", methods=["GET", "POST"])
def create_employee():
    db = SessionLocal()
    try:
        roles, areas, groups = _load_reference_data(db)
        if not roles:
            flash("Debe crear roles antes de anadir empleados.", "warn")
            return redirect(url_for("admin_roles.create_role"))

        form = EmployeeForm()
        if request.method == "GET":
            form.is_active.data = True
        selected_area = form.area_id.data or None
        if selected_area == 0:
            selected_area = None
        selected_group = form.group_id.data or None
        if selected_group == 0:
            selected_group = None
        _set_form_choices(
            form,
            roles,
            areas,
            groups,
            selected_area_id=selected_area,
            selected_group_id=selected_group,
        )

        if form.validate_on_submit():
            email = form.email.data.strip().lower()
            existing = db.execute(select(Employee).where(Employee.email == email)).scalar_one_or_none()
            if existing:
                form.email.errors.append("Ya existe un empleado con este email.")
            else:
                role = db.get(Role, form.role_id.data)
                if not role:
                    form.role_id.errors.append("Rol no valido.")
                else:
                    area_id = form.area_id.data if form.area_id.data else None
                    if area_id == 0:
                        area_id = None
                    group_id = form.group_id.data if form.group_id.data else None
                    if group_id == 0:
                        group_id = None

                    if group_id:
                        group = db.get(AdminGroup, group_id)
                        if not group:
                            form.group_id.errors.append("Grupo no valido.")
                        elif area_id and group.area_id != area_id:
                            form.group_id.errors.append("El grupo seleccionado no pertenece al area elegida.")
                        else:
                            area_id = group.area_id if group else area_id
                    if not form.errors:
                        employee = Employee(
                            name=form.name.data.strip(),
                            email=email,
                            role_id=role.id,
                            area_id=area_id,
                            group_id=group_id,
                            is_active=form.is_active.data,
                        )
                        db.add(employee)
                        db.commit()
                        flash("Empleado creado correctamente.", "ok")
                        return redirect(url_for("admin_employees.list_employees"))
        grouped = _group_options_by_area(groups)
        return render_template(
            "employees/form.html",
            form=form,
            form_action=url_for("admin_employees.create_employee"),
            title="Crear empleado",
            roles=roles,
            areas=areas,
            groups=groups,
            group_map_json=json.dumps(grouped, ensure_ascii=False),
        )
    finally:
        db.close()


@bp.route("/<int:employee_id>/edit", methods=["GET", "POST"])
def edit_employee(employee_id: int):
    db = SessionLocal()
    try:
        employee = db.get(Employee, employee_id)
        if not employee:
            flash("Empleado no encontrado.", "error")
            return redirect(url_for("admin_employees.list_employees"))

        roles, areas, groups = _load_reference_data(db)
        form = EmployeeForm(obj=employee)
        selected_area = employee.area_id or None
        selected_group = employee.group_id or None
        if request.method == "POST":
            selected_area = form.area_id.data or None
            if selected_area == 0:
                selected_area = None
            selected_group = form.group_id.data or None
            if selected_group == 0:
                selected_group = None
        _set_form_choices(
            form,
            roles,
            areas,
            groups,
            selected_area_id=selected_area,
            selected_group_id=selected_group,
        )

        if form.validate_on_submit():
            email = form.email.data.strip().lower()
            duplicate = (
                db.execute(
                    select(Employee).where(Employee.email == email, Employee.id != employee.id)
                ).scalar_one_or_none()
            )
            if duplicate:
                form.email.errors.append("Ya existe otro empleado con este email.")
            else:
                role = db.get(Role, form.role_id.data)
                if not role:
                    form.role_id.errors.append("Rol no valido.")
                else:
                    area_id = form.area_id.data if form.area_id.data else None
                    if area_id == 0:
                        area_id = None
                    group_id = form.group_id.data if form.group_id.data else None
                    if group_id == 0:
                        group_id = None
                    group = None
                    if group_id:
                        group = db.get(AdminGroup, group_id)
                        if not group:
                            form.group_id.errors.append("Grupo no valido.")
                        elif area_id and group.area_id != area_id:
                            form.group_id.errors.append("El grupo seleccionado no pertenece al area elegida.")
                        else:
                            area_id = group.area_id
                    if not form.errors:
                        employee.name = form.name.data.strip()
                        employee.email = email
                        employee.role_id = role.id
                        employee.area_id = area_id
                        employee.group_id = group_id
                        employee.is_active = form.is_active.data
                        try:
                            db.commit()
                            flash("Empleado actualizado correctamente.", "ok")
                            return redirect(url_for("admin_employees.list_employees"))
                        except IntegrityError:
                            db.rollback()
                            form.email.errors.append("No se pudo guardar el empleado. Revise los datos.")
        grouped = _group_options_by_area(groups)
        return render_template(
            "employees/form.html",
            form=form,
            form_action=url_for("admin_employees.edit_employee", employee_id=employee_id),
            title="Editar empleado",
            roles=roles,
            areas=areas,
            groups=groups,
            group_map_json=json.dumps(grouped, ensure_ascii=False),
            employee=employee,
        )
    finally:
        db.close()


@bp.route("/<int:employee_id>/toggle", methods=["POST"])
def toggle_employee_status(employee_id: int):
    db = SessionLocal()
    try:
        employee = db.get(Employee, employee_id)
        if not employee:
            flash("Empleado no encontrado.", "error")
        else:
            employee.is_active = not employee.is_active
            db.commit()
            flash(
                "Empleado activado." if employee.is_active else "Empleado desactivado.",
                "ok",
            )
        return redirect(url_for("admin_employees.list_employees"))
    finally:
        db.close()




