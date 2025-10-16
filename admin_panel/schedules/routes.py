"""Routes for managing work schedule policies."""

from datetime import time

from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from admin_panel.schedules import bp
from admin_panel.schedules.forms import SchedulePolicyForm
from admin_panel.schedules.models import WorkSchedulePolicy
from models import Role as UserRole, SessionLocal


def _require_admin():
    if not current_user.is_authenticated:
        login_manager = current_app.login_manager
        return login_manager.unauthorized()
    if current_user.role != UserRole.admin:
        abort(403)


@bp.before_request
def before_request():
    return _require_admin()


def _format_time(value: time | None) -> str:
    if not value:
        return "-"
    return value.strftime("%H:%M")


def _load_policy(db, policy_id: int):
    policy = db.get(WorkSchedulePolicy, policy_id)
    if not policy:
        flash("Work schedule policy not found.", "error")
        return redirect(url_for("admin_schedules.list_schedules"))
    return policy


def _prepare_form_days(form: SchedulePolicyForm, policy: WorkSchedulePolicy | None):
    if request.method == "POST":
        return
    if policy and policy.working_days:
        form.working_days.data = policy.working_days.split(",")
    else:
        form.working_days.data = ["mon", "tue", "wed", "thu", "fri"]


def _clean_int(value, default=0):
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return int(value)


def _localize_form(form: SchedulePolicyForm, lang: str) -> None:
    """Translate form labels to Spanish when requested."""
    if lang != "es":
        return
    labels = {
        "name": "Nombre",
        "mode": "Modo",
        "description": "Descripción",
        "expected_weekly_hours": "Horas semanales previstas",
        "min_daily_hours": "Horas mínimas por día",
        "start_time": "Hora de entrada",
        "end_time": "Hora de salida",
        "allow_early_entry": "Permitir entrada anticipada",
        "allow_late_exit": "Permitir salida tardía",
        "break_minutes": "Descanso (minutos)",
        "working_days": "Días laborables",
        "no_time_enforcement": "Sin control horario",
        "allow_overtime": "Permitir horas extra",
        "overtime_after_minutes": "Horas extra después de (minutos)",
        "is_night_shift": "Turno nocturno",
        "entry_margin_minutes": "Margen de entrada (minutos)",
        "exit_margin_minutes": "Margen de salida (minutos)",
    }
    for field_name, label in labels.items():
        if hasattr(form, field_name):
            getattr(form, field_name).label.text = label


@bp.route("/", methods=["GET"])
@login_required
def list_schedules():
    db = SessionLocal()
    try:
        policies = db.execute(
            select(WorkSchedulePolicy).order_by(WorkSchedulePolicy.name.asc())
        ).scalars().all()
        return render_template("schedules/list.html", policies=policies, format_time=_format_time)
    finally:
        db.close()


@bp.route("/create", methods=["GET", "POST"])
@login_required
def create_schedule():
    form = SchedulePolicyForm()
    lang = request.args.get("lang", "en")
    _localize_form(form, lang)
    _prepare_form_days(form, policy=None)
    if form.validate_on_submit():
        db = SessionLocal()
        try:
            existing = db.execute(
                select(WorkSchedulePolicy).where(WorkSchedulePolicy.name == form.name.data.strip())
            ).scalar_one_or_none()
            if existing:
                form.name.errors.append("Another policy with this name already exists.")
            else:
                policy = WorkSchedulePolicy(
                    name=form.name.data.strip(),
                    description=(form.description.data or "").strip() or None,
                    mode=form.mode.data,
                    expected_weekly_hours=form.expected_weekly_hours.data,
                    min_daily_hours=form.min_daily_hours.data,
                    start_time=form.start_time.data,
                    end_time=form.end_time.data,
                    allow_early_entry=bool(form.allow_early_entry.data),
                    allow_late_exit=bool(form.allow_late_exit.data),
                    break_minutes=_clean_int(form.break_minutes.data, default=0),
                    working_days=",".join(form.working_days.data),
                    no_time_enforcement=bool(form.no_time_enforcement.data),
                    allow_overtime=bool(form.allow_overtime.data),
                    overtime_after_minutes=form.overtime_after_minutes.data
                    if form.allow_overtime.data
                    else None,
                    is_night_shift=bool(form.is_night_shift.data),
                    entry_margin_minutes=_clean_int(form.entry_margin_minutes.data, default=0),
                    exit_margin_minutes=_clean_int(form.exit_margin_minutes.data, default=0),
                )
                db.add(policy)
                db.commit()
                flash("Work schedule policy created successfully.", "ok")
                return redirect(url_for("admin_schedules.list_schedules"))
        finally:
            db.close()
    title = "Crear política de jornada" if lang == "es" else "Create work schedule policy"
    return render_template("schedules/edit.html", form=form, title=title, current_lang=lang)


@bp.route("/<int:policy_id>/edit", methods=["GET", "POST"])
@login_required
def edit_schedule(policy_id: int):
    db = SessionLocal()
    try:
        policy = _load_policy(db, policy_id)
        if not isinstance(policy, WorkSchedulePolicy):
            return policy

        form = SchedulePolicyForm(obj=policy)
        lang = request.args.get("lang", "en")
        _localize_form(form, lang)
        _prepare_form_days(form, policy=policy)
        if form.validate_on_submit():
            duplicate = (
                db.execute(
                    select(WorkSchedulePolicy).where(
                        WorkSchedulePolicy.id != policy.id,
                        WorkSchedulePolicy.name == form.name.data.strip(),
                    )
                ).scalar_one_or_none()
            )
            if duplicate:
                form.name.errors.append("Another policy with this name already exists.")
            else:
                policy.name = form.name.data.strip()
                policy.description = (form.description.data or "").strip() or None
                policy.mode = form.mode.data
                policy.expected_weekly_hours = form.expected_weekly_hours.data
                policy.min_daily_hours = form.min_daily_hours.data
                policy.start_time = form.start_time.data
                policy.end_time = form.end_time.data
                policy.allow_early_entry = bool(form.allow_early_entry.data)
                policy.allow_late_exit = bool(form.allow_late_exit.data)
                policy.break_minutes = _clean_int(form.break_minutes.data, default=0)
                policy.working_days = ",".join(form.working_days.data)
                policy.no_time_enforcement = bool(form.no_time_enforcement.data)
                policy.allow_overtime = bool(form.allow_overtime.data)
                policy.overtime_after_minutes = (
                    form.overtime_after_minutes.data if form.allow_overtime.data else None
                )
                policy.is_night_shift = bool(form.is_night_shift.data)
                policy.entry_margin_minutes = _clean_int(form.entry_margin_minutes.data, default=0)
                policy.exit_margin_minutes = _clean_int(form.exit_margin_minutes.data, default=0)
                try:
                    db.commit()
                    flash("Work schedule policy updated successfully.", "ok")
                    return redirect(url_for("admin_schedules.list_schedules"))
                except IntegrityError:
                    db.rollback()
                    form.name.errors.append("Unable to update policy. Please retry.")
        title = "Editar política de jornada" if lang == "es" else "Edit work schedule policy"
        return render_template(
            "schedules/edit.html",
            form=form,
            title=title,
            policy=policy,
            current_lang=lang,
        )
    finally:
        db.close()


@bp.route("/<int:policy_id>/delete", methods=["POST"])
@login_required
def delete_schedule(policy_id: int):
    db = SessionLocal()
    try:
        policy = _load_policy(db, policy_id)
        if not isinstance(policy, WorkSchedulePolicy):
            return policy
        db.delete(policy)
        db.commit()
        flash("Work schedule policy deleted.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_schedules.list_schedules"))
