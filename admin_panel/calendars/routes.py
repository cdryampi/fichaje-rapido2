"""Routes for managing work calendars."""

from datetime import date, timedelta

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

from admin_panel.calendars import bp
from admin_panel.calendars.forms import CalendarForm, HolidayForm
from admin_panel.calendars.models import WorkCalendar, WorkCalendarHoliday
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


def _load_calendar(db, calendar_id: int):
    calendar = db.get(WorkCalendar, calendar_id)
    if not calendar:
        flash("Calendario no encontrado.", "error")
        return redirect(url_for("admin_calendars.list_calendars"))
    return calendar


def _calculate_summary(calendar: WorkCalendar, holidays: list[WorkCalendarHoliday]):
    holiday_dates = {holiday.date for holiday in holidays}
    holiday_counts = {"local": 0, "autonomic": 0, "national": 0}
    for holiday in holidays:
        if holiday.holiday_type in holiday_counts:
            holiday_counts[holiday.holiday_type] += 1

    start = date(calendar.year, 1, 1)
    end = date(calendar.year, 12, 31)
    cursor = start
    expected_hours = 0.0
    weekday_count = 0
    saturday_count = 0
    sunday_count = 0

    while cursor <= end:
        if cursor not in holiday_dates:
            weekday = cursor.weekday()
            if weekday < 5:
                expected_hours += calendar.weekday_hours
                weekday_count += 1
            elif weekday == 5:
                expected_hours += calendar.saturday_hours
                saturday_count += 1
            else:
                expected_hours += calendar.sunday_hours
                sunday_count += 1
        cursor += timedelta(days=1)

    return {
        "expected_hours": round(expected_hours, 2),
        "holiday_counts": holiday_counts,
        "weekday_count": weekday_count,
        "saturday_count": saturday_count,
        "sunday_count": sunday_count,
    }


@bp.route("/", methods=["GET"])
@login_required
def list_calendars():
    db = SessionLocal()
    try:
        calendars = db.execute(
            select(WorkCalendar).order_by(WorkCalendar.year.desc(), WorkCalendar.name.asc())
        ).scalars().all()
        summaries = {}
        if calendars:
            calendar_ids = [calendar.id for calendar in calendars]
            holidays = db.execute(
                select(WorkCalendarHoliday).where(WorkCalendarHoliday.calendar_id.in_(calendar_ids))
            ).scalars().all()
            holidays_by_calendar = {}
            for holiday in holidays:
                holidays_by_calendar.setdefault(holiday.calendar_id, []).append(holiday)
            for calendar in calendars:
                summaries[calendar.id] = _calculate_summary(
                    calendar, holidays_by_calendar.get(calendar.id, [])
                )
        return render_template("calendars/list.html", calendars=calendars, summaries=summaries)
    finally:
        db.close()


@bp.route("/create", methods=["GET", "POST"])
@login_required
def create_calendar():
    form = CalendarForm()
    if form.validate_on_submit():
        db = SessionLocal()
        try:
            existing = db.execute(
                select(WorkCalendar).where(
                    WorkCalendar.name == form.name.data.strip(),
                    WorkCalendar.year == form.year.data,
                )
            ).scalar_one_or_none()
            if existing:
                form.name.errors.append("Ya existe un calendario con este nombre y año.")
            else:
                calendar = WorkCalendar(
                    name=form.name.data.strip(),
                    year=form.year.data,
                    description=(form.description.data or "").strip() or None,
                    notes=(form.notes.data or "").strip() or None,
                    weekly_hours=form.weekly_hours.data,
                    weekday_hours=form.weekday_hours.data,
                    saturday_hours=form.saturday_hours.data,
                    sunday_hours=form.sunday_hours.data,
                    break_minutes=form.break_minutes.data or 0,
                    clock_in_start_time=form.clock_in_start_time.data,
                    clock_in_end_time=form.clock_in_end_time.data,
                    max_daily_hours=form.max_daily_hours.data or 0,
                )
                db.add(calendar)
                try:
                    db.commit()
                    flash("Calendario creado correctamente.", "ok")
                    return redirect(url_for("admin_calendars.edit_calendar", calendar_id=calendar.id))
                except IntegrityError:
                    db.rollback()
                    form.name.errors.append("No se pudo crear el calendario. Reintenta.")
        finally:
            db.close()
    return render_template("calendars/edit.html", form=form, title="Crear calendario laboral")


@bp.route("/<int:calendar_id>/edit", methods=["GET", "POST"])
@login_required
def edit_calendar(calendar_id: int):
    db = SessionLocal()
    try:
        calendar = _load_calendar(db, calendar_id)
        if not isinstance(calendar, WorkCalendar):
            return calendar

        form = CalendarForm(obj=calendar)
        holiday_form = HolidayForm()
        if form.validate_on_submit():
            duplicate = db.execute(
                select(WorkCalendar).where(
                    WorkCalendar.id != calendar.id,
                    WorkCalendar.name == form.name.data.strip(),
                    WorkCalendar.year == form.year.data,
                )
            ).scalar_one_or_none()
            if duplicate:
                form.name.errors.append("Ya existe un calendario con este nombre y año.")
            else:
                calendar.name = form.name.data.strip()
                calendar.year = form.year.data
                calendar.description = (form.description.data or "").strip() or None
                calendar.notes = (form.notes.data or "").strip() or None
                calendar.weekly_hours = form.weekly_hours.data
                calendar.weekday_hours = form.weekday_hours.data
                calendar.saturday_hours = form.saturday_hours.data
                calendar.sunday_hours = form.sunday_hours.data
                calendar.break_minutes = form.break_minutes.data or 0
                calendar.clock_in_start_time = form.clock_in_start_time.data
                calendar.clock_in_end_time = form.clock_in_end_time.data
                calendar.max_daily_hours = form.max_daily_hours.data or 0
                try:
                    db.commit()
                    flash("Calendario actualizado correctamente.", "ok")
                    return redirect(url_for("admin_calendars.edit_calendar", calendar_id=calendar.id))
                except IntegrityError:
                    db.rollback()
                    form.name.errors.append("No se pudo actualizar el calendario. Reintenta.")

        holidays = db.execute(
            select(WorkCalendarHoliday)
            .where(WorkCalendarHoliday.calendar_id == calendar.id)
            .order_by(WorkCalendarHoliday.date.asc())
        ).scalars().all()
        summary = _calculate_summary(calendar, holidays)
        return render_template(
            "calendars/edit.html",
            form=form,
            holiday_form=holiday_form,
            calendar=calendar,
            holidays=holidays,
            summary=summary,
            title="Editar calendario laboral",
        )
    finally:
        db.close()


@bp.route("/<int:calendar_id>/holidays", methods=["POST"])
@login_required
def add_holiday(calendar_id: int):
    db = SessionLocal()
    try:
        calendar = _load_calendar(db, calendar_id)
        if not isinstance(calendar, WorkCalendar):
            return calendar

        form = HolidayForm()
        if form.validate_on_submit():
            if form.date.data.year != calendar.year:
                form.date.errors.append("La fecha debe estar dentro del año del calendario.")
            else:
                existing = db.execute(
                    select(WorkCalendarHoliday).where(
                        WorkCalendarHoliday.calendar_id == calendar.id,
                        WorkCalendarHoliday.date == form.date.data,
                    )
                ).scalar_one_or_none()
                if existing:
                    form.date.errors.append("Ya existe un festivo en esa fecha.")
                else:
                    holiday = WorkCalendarHoliday(
                        calendar_id=calendar.id,
                        date=form.date.data,
                        holiday_type=form.holiday_type.data,
                        name=(form.name.data or "").strip() or None,
                        note=(form.note.data or "").strip() or None,
                    )
                    db.add(holiday)
                    db.commit()
                    flash("Festivo añadido correctamente.", "ok")
                    return redirect(url_for("admin_calendars.edit_calendar", calendar_id=calendar.id))

        holidays = db.execute(
            select(WorkCalendarHoliday)
            .where(WorkCalendarHoliday.calendar_id == calendar.id)
            .order_by(WorkCalendarHoliday.date.asc())
        ).scalars().all()
        summary = _calculate_summary(calendar, holidays)
        flash("Revisa los datos del festivo.", "error")
        return render_template(
            "calendars/edit.html",
            form=CalendarForm(obj=calendar),
            holiday_form=form,
            calendar=calendar,
            holidays=holidays,
            summary=summary,
            title="Editar calendario laboral",
        )
    finally:
        db.close()


@bp.route("/<int:calendar_id>/holidays/<int:holiday_id>/delete", methods=["POST"])
@login_required
def delete_holiday(calendar_id: int, holiday_id: int):
    db = SessionLocal()
    try:
        calendar = _load_calendar(db, calendar_id)
        if not isinstance(calendar, WorkCalendar):
            return calendar
        holiday = db.get(WorkCalendarHoliday, holiday_id)
        if not holiday or holiday.calendar_id != calendar.id:
            flash("Festivo no encontrado.", "error")
            return redirect(url_for("admin_calendars.edit_calendar", calendar_id=calendar.id))
        db.delete(holiday)
        db.commit()
        flash("Festivo eliminado.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_calendars.edit_calendar", calendar_id=calendar_id))


@bp.route("/<int:calendar_id>/delete", methods=["POST"])
@login_required
def delete_calendar(calendar_id: int):
    db = SessionLocal()
    try:
        calendar = _load_calendar(db, calendar_id)
        if not isinstance(calendar, WorkCalendar):
            return calendar
        db.delete(calendar)
        db.commit()
        flash("Calendario eliminado.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_calendars.list_calendars"))
