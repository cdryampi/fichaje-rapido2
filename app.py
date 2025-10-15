from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import SessionLocal, init_db_with_demo, User, Attendance, AttendanceAction, Role, Pause, TimeEntry, EntryStatus, Group, Area
from rbac import can_view_user, can_edit_entries, require_view_user, require_edit_entry
from sqlalchemy import select, desc, func
from functools import wraps
from datetime import datetime, timezone

# Zona horaria (con fallback si falta tzdata en Windows)
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Madrid")
except Exception:
    TZ = timezone.utc

def to_local(ts):
    """Convierte cualquier datetime de BD a hora local Europe/Madrid.
    Si viene naive (sin tz), lo tratamos como UTC."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(TZ).strftime("%d/%m/%Y %H:%M:%S")

def ensure_aware_utc(ts):
    """Devuelve ts como datetime consciente en UTC (naive => UTC)."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)

def to_utc_epoch(ts) -> float:
    """Epoch segundos asumiendo UTC si naive."""
    return ensure_aware_utc(ts).timestamp()

def local_day_bounds_utc(ref_utc: datetime):
    """Devuelve (inicio_dia_utc, fin_dia_utc) para el día local Europe/Madrid.
    ref_utc debe ser aware en UTC."""
    ref_local = ref_utc.astimezone(TZ)
    start_local = ref_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    return start_utc, end_utc
def to_local_hms(ts):
    """Hora local HH:MM:SS del servidor."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(TZ).strftime("%H:%M:%S")

def fmt_hm(seconds: int) -> str:
    sign = '-' if seconds < 0 else ''
    s = abs(int(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    return f"{sign}{h:02d}:{m:02d}"

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"

from flask_wtf import CSRFProtect
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# Inicializa BD y usuario demo al arrancar
with app.app_context():
    init_db_with_demo()

@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        return db.get(User, int(user_id))
    finally:
        db.close()

# --------- Guard de ADMIN ---------
def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != Role.admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper

# ---------- RUTAS ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = SessionLocal()
        try:
            user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if user and user.check_password(password):
                login_user(user)
                return redirect(url_for("index"))
            flash("Credenciales inválidas", "error")
        finally:
            db.close()
    # Mostrar select de usuarios solo en modo debug o con ALLOW_LOGIN_AS=1
    import os
    show_dev_login = app.debug or os.getenv("ALLOW_LOGIN_AS") == "1"
    test_users = []
    if show_dev_login:
        db = SessionLocal()
        try:
            test_users = db.execute(select(User).order_by(User.role, User.id)).scalars().all()
        finally:
            db.close()
    return render_template("login.html", test_users=test_users, show_dev_login=show_dev_login)

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/dev/login_as", methods=["POST"])
def dev_login_as():
    import os
    if not (app.debug or os.getenv("ALLOW_LOGIN_AS") == "1"):
        abort(404)
    user_id = request.form.get("user_id")
    if not user_id:
        abort(400)
    db = SessionLocal()
    try:
        u = db.get(User, int(user_id))
        if not u:
            abort(404)
        login_user(u)
        return redirect(url_for("index"))
    finally:
        db.close()

@app.route("/")
@login_required
def index():
    db = SessionLocal()
    try:
        last = db.execute(
            select(Attendance)
            .where(Attendance.user_id == current_user.id)
            .order_by(desc(Attendance.ts))
        ).scalars().first()
        dentro = (last and last.action == AttendanceAction._in)

        hist_rows = db.execute(
            select(Attendance)
            .where(Attendance.user_id == current_user.id)
            .order_by(desc(Attendance.ts))
            .limit(5)
        ).scalars().all()

        historial = [
            {"action": r.action.value, "ts_local": to_local(r.ts)}
            for r in hist_rows
        ]

        # Últimas entradas/salidas para métrica rápida
        last_in_local = next((to_local(r.ts) for r in hist_rows if r.action == AttendanceAction._in), None)
        last_out_local = next((to_local(r.ts) for r in hist_rows if r.action == AttendanceAction._out), None)

        now_utc = datetime.now(timezone.utc)
        server_now_utc = now_utc.timestamp()

        # Estado de pausa actual
        pausa_activa = db.execute(
            select(Pause)
            .where(Pause.user_id == current_user.id, Pause.end_ts.is_(None))
            .order_by(desc(Pause.start_ts))
        ).scalars().first()
        pausa_start_epoch = to_utc_epoch(pausa_activa.start_ts) if pausa_activa else None

        # Total de pausas de hoy (en la zona local) EXCLUYENDO pausas activas
        day_start_utc, day_end_utc = local_day_bounds_utc(now_utc)
        pauses = db.execute(
            select(Pause)
            .where(
                Pause.user_id == current_user.id,
                Pause.start_ts <= day_end_utc,
                Pause.end_ts.is_not(None),
                Pause.end_ts >= day_start_utc,
            )
        ).scalars().all()

        total_secs = 0
        for p in pauses:
            if not p.end_ts:
                continue  # ignorar pausas activas
            p_start = ensure_aware_utc(p.start_ts)
            p_end = ensure_aware_utc(p.end_ts)
            start = max(p_start, day_start_utc)
            end = min(p_end, day_end_utc)
            if end > start:
                total_secs += int((end - start).total_seconds())

        pause_total_today_fmt = _fmt_hms(total_secs)

        return render_template("index.html",
                               dentro=dentro,
                               historial=historial,
                               server_now_utc=server_now_utc,
                               pausa_activa=bool(pausa_activa),
                               pausa_start_epoch=pausa_start_epoch,
                               pause_total_today_fmt=pause_total_today_fmt,
                               last_in_local=last_in_local,
                               last_out_local=last_out_local)
    finally:
        db.close()

@app.route("/clock", methods=["POST"])
@login_required
def clock():
    db = SessionLocal()
    try:
        # Acción explícita solicitada por el usuario: 'in' o 'out'
        action_str = (request.form.get("action") or request.args.get("action") or "").strip().lower()
        if action_str not in {"in", "out"}:
            abort(400, description="Acción inválida")

        action = AttendanceAction._in if action_str == "in" else AttendanceAction._out

        # Guardar fichaje
        rec = Attendance(
            user_id=current_user.id,
            action=action,
            ts=datetime.now(timezone.utc),
            ip=request.headers.get("X-Forwarded-For", request.remote_addr),
        )
        db.add(rec)
        db.commit()

        # Recalcular historial
        last5 = db.execute(
            select(Attendance)
            .where(Attendance.user_id == current_user.id)
            .order_by(desc(Attendance.ts))
            .limit(5)
        ).scalars().all()

        historial = [
            {"action": r.action.value, "ts_local": to_local(r.ts)}
            for r in last5
        ]

        mensaje = f"Has fichado {'SALIDA' if action == AttendanceAction._out else 'ENTRADA'}."
        return render_template(
            "_status.html",
            dentro=(action == AttendanceAction._in),
            historial=historial,
            mensaje=mensaje,
        )
    finally:
        db.close()

# ---------- ADMIN ----------

@app.route("/admin", methods=["GET"])
@login_required
@admin_required
def admin_home():
    db = SessionLocal()
    try:
        total_users = db.execute(select(func.count()).select_from(User)).scalar() or 0
        total_groups = db.execute(select(func.count()).select_from(Group)).scalar() or 0
        total_areas = db.execute(select(func.count()).select_from(Area)).scalar() or 0
        return render_template(
            "admin/index.html",
            users_count=total_users,
            groups_count=total_groups,
            areas_count=total_areas,
        )
    finally:
        db.close()


@app.route("/admin/users", methods=["GET"])
@login_required
@admin_required
def admin_users():
    db = SessionLocal()
    try:
        users = db.execute(select(User).order_by(User.id)).scalars().all()
        groups = db.execute(select(Group).order_by(Group.id)).scalars().all()
        return render_template("admin/users.html", users=users, groups=groups)
    finally:
        db.close()


@app.route("/admin/areas", methods=["GET"])
@login_required
@admin_required
def admin_areas_page():
    db = SessionLocal()
    try:
        areas = db.execute(select(Area).order_by(Area.id)).scalars().all()
        return render_template("admin/areas.html", areas=areas)
    finally:
        db.close()


@app.route("/admin/groups", methods=["GET"])
@login_required
@admin_required
def admin_groups_page():
    db = SessionLocal()
    try:
        groups = db.execute(select(Group).order_by(Group.id)).scalars().all()
        areas = db.execute(select(Area).order_by(Area.id)).scalars().all()
        return render_template("admin/groups.html", groups=groups, areas=areas)
    finally:
        db.close()

@app.route("/admin/users/create", methods=["POST"])
@login_required
@admin_required
def admin_users_create():
    email = request.form.get("email", "").strip().lower()
    name = request.form.get("name", "").strip()
    password = request.form.get("password", "").strip()
    role_str = request.form.get("role", "employee").strip()

    if not email or not name or not password:
        flash("Faltan campos obligatorios.", "error")
        return redirect(url_for("admin_users"))

    try:
        role = Role(role_str)
    except Exception:
        role = Role.employee
    group_id = request.form.get("group_id")

    db = SessionLocal()
    try:
        existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing:
            flash("Ese email ya existe.", "error")
            return redirect(url_for("admin_users"))

        u = User(email=email, name=name, role=role)
        if group_id:
            try:
                gid = int(group_id)
                g = db.get(Group, gid)
                if g:
                    u.group_id = g.id
                    u.area_id = g.area_id
            except Exception:
                pass
        u.set_password(password)
        db.add(u)
        db.commit()
        flash("Usuario creado correctamente.", "ok")
        return redirect(url_for("admin_users"))
    finally:
        db.close()
@app.route("/admin/users/<int:user_id>/reset_password", methods=["POST"])
@login_required
@admin_required
def admin_users_reset_password(user_id):
    new_pass = request.form.get("new_password", "").strip()
    if not new_pass:
        flash("La nueva contraseña no puede estar vacía.", "error")
        return redirect(url_for("admin_users"))

    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if not u:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for("admin_users"))
        if u.id == current_user.id and len(new_pass) < 6:
            flash("Como admin, pon al menos 6 caracteres.", "error")
            return redirect(url_for("admin_users"))

        u.set_password(new_pass)
        db.commit()
        flash(f"Contraseña de {u.email} actualizada.", "ok")
        return redirect(url_for("admin_users"))
    finally:
        db.close()


@app.route("/admin/users/<int:user_id>/set_role", methods=["POST"])
@login_required
@admin_required
def admin_users_set_role(user_id):
    role_str = request.form.get("role", "employee").strip()
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if not u:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for("admin_users"))
        if u.id == current_user.id and role_str != "admin":
            flash("No puedes quitarte a ti mismo el rol de admin.", "error")
            return redirect(url_for("admin_users"))

        try:
            u.role = Role(role_str)
        except Exception:
            u.role = Role.employee
        db.commit()
        flash(f"Rol de {u.email} actualizado a {u.role.value}.", "ok")
        return redirect(url_for("admin_users"))
    finally:
        db.close()

@app.route("/admin/users/<int:user_id>/set_group", methods=["POST"])
@login_required
@admin_required
def admin_users_set_group(user_id):
    group_id = request.form.get("group_id")
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if not u:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for("admin_users"))
        if not group_id:
            flash("Grupo inválido.", "error")
            return redirect(url_for("admin_users"))
        g = db.get(Group, int(group_id))
        if not g:
            flash("Grupo no encontrado.", "error")
            return redirect(url_for("admin_users"))
        u.group_id = g.id
        u.area_id = g.area_id
        db.commit()
        flash(f"Grupo de {u.email} actualizado a {g.name}.", "ok")
        return redirect(url_for("admin_users"))
    finally:
        db.close()

# ---------- ADMIN: GROUPS CRUD ----------

@app.route("/admin/groups/create", methods=["POST"])
@login_required
@admin_required
def admin_groups_create():
    name = request.form.get("name", "").strip()
    area_id = request.form.get("area_id", "").strip()
    if not name:
        flash("El nombre del grupo es obligatorio.", "error")
        return redirect(url_for("admin_groups_page"))
    db = SessionLocal()
    try:
        g = Group(name=name)
        if area_id:
            try:
                a = db.get(Area, int(area_id))
                if a:
                    g.area_id = a.id
            except Exception:
                pass
        db.add(g)
        db.commit()
        flash("Grupo creado.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_groups_page"))


@app.route("/admin/groups/<int:group_id>/update", methods=["POST"])
@login_required
@admin_required
def admin_groups_update(group_id):
    name = request.form.get("name", "").strip()
    area_id = request.form.get("area_id", "").strip()
    db = SessionLocal()
    try:
        g = db.get(Group, group_id)
        if not g:
            flash("Grupo no encontrado.", "error")
            return redirect(url_for("admin_groups_page"))
        if name:
            g.name = name
        if area_id:
            try:
                a = db.get(Area, int(area_id))
                if a:
                    g.area_id = a.id
            except Exception:
                pass
        db.commit()
        flash("Grupo actualizado.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_groups_page"))


@app.route("/admin/groups/<int:group_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_groups_delete(group_id):
    db = SessionLocal()
    try:
        g = db.get(Group, group_id)
        if not g:
            flash("Grupo no encontrado.", "error")
            return redirect(url_for("admin_groups_page"))
        has_users = db.execute(select(User).where(User.group_id == g.id)).first()
        if has_users:
            flash("No se puede borrar: hay usuarios en el grupo.", "error")
            return redirect(url_for("admin_groups_page"))
        db.delete(g)
        db.commit()
        flash("Grupo borrado.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_groups_page"))


# ---------- ADMIN: AREAS CRUD ----------

@app.route("/admin/areas/create", methods=["POST"])
@login_required
@admin_required
def admin_areas_create():
    name = request.form.get("name", "").strip()
    if not name:
        flash("El nombre del área es obligatorio.", "error")
        return redirect(url_for("admin_areas_page"))
    db = SessionLocal()
    try:
        if db.execute(select(Area).where(Area.name == name)).first():
            flash("Ya existe un área con ese nombre.", "error")
            return redirect(url_for("admin_users"))
        a = Area(name=name)
        db.add(a)
        db.commit()
        flash("Área creada.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_areas_page"))


@app.route("/admin/areas/<int:area_id>/update", methods=["POST"])
@login_required
@admin_required
def admin_areas_update(area_id):
    name = request.form.get("name", "").strip()
    db = SessionLocal()
    try:
        a = db.get(Area, area_id)
        if not a:
            flash("Área no encontrada.", "error")
            return redirect(url_for("admin_areas_page"))
        if name:
            a.name = name
        db.commit()
        flash("Área actualizada.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_areas_page"))


@app.route("/admin/areas/<int:area_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_areas_delete(area_id):
    db = SessionLocal()
    try:
        a = db.get(Area, area_id)
        if not a:
            flash("Área no encontrada.", "error")
            return redirect(url_for("admin_areas_page"))
        has_groups = db.execute(select(Group).where(Group.area_id == a.id)).first()
        has_users = db.execute(select(User).where(User.area_id == a.id)).first()
        if has_groups or has_users:
            flash("No se puede borrar: área con grupos o usuarios.", "error")
            return redirect(url_for("admin_areas_page"))
        db.delete(a)
        db.commit()
        flash("Área borrada.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_areas_page"))


# ---------- ENTRIES (RBAC) ----------

@app.route("/entries", methods=["GET"])
@login_required
def entries_list():
    db = SessionLocal()
    try:
        q = select(TimeEntry)
        if current_user.role == Role.employee:
            q = q.where(TimeEntry.user_id == current_user.id)
        elif current_user.role == Role.responsable:
            group_id = current_user.group_id
            if group_id:
                q = q.where(TimeEntry.user_id.in_(select(User.id).where(User.group_id == group_id)))
            else:
                q = q.where(TimeEntry.user_id == -1)
        elif current_user.role == Role.cap_area:
            area_id = current_user.area_id
            if area_id:
                q = q.where(TimeEntry.user_id.in_(select(User.id).where(User.area_id == area_id)))
            else:
                q = q.where(TimeEntry.user_id == -1)
        elif current_user.role in (Role.rrhh, Role.admin):
            pass
        elif current_user.role == Role.invitado:
            from models import GuestAccess
            q = q.where(TimeEntry.user_id.in_(select(GuestAccess.target_user_id).where(GuestAccess.guest_user_id == current_user.id)))

        rows = db.execute(q.order_by(TimeEntry.id.desc())).scalars().all()
        entries = [
            {
                "id": r.id,
                "user": (db.get(User, r.user_id).email if r.user_id else "-"),
                "type": r.type.value,
                "status": r.status.value,
                "ts_in": to_local(r.ts_in) if r.ts_in else "-",
                "ts_out": to_local(r.ts_out) if r.ts_out else "-",
            }
            for r in rows
        ]
        return render_template("entries.html", entries=entries)
    finally:
        db.close()


@app.route("/entries/<int:entry_id>/approve", methods=["POST"])
@login_required
@require_edit_entry("entry_id")
def entries_approve(entry_id):
    db = SessionLocal()
    try:
        e = db.get(TimeEntry, entry_id)
        if not e:
            abort(404)
        e.status = EntryStatus.approved
        db.commit()
        flash("Entrada aprobada", "ok")
        return redirect(url_for("entries_list"))
    finally:
        db.close()


@app.route("/entries/<int:entry_id>/edit", methods=["POST"])
@login_required
@require_edit_entry("entry_id")
def entries_edit(entry_id):
    flash("Editar (demo): permitido para tu rol/scope.", "ok")
    return redirect(url_for("entries_list"))


# ----- Simple pages for menu -----
@app.route("/requests")
@login_required
def requests_page():
    return render_template("requests.html")


@app.route("/requests/adelanto", methods=["GET", "POST"])
@login_required
def advance_request():
    if request.method == "POST":
        income_raw = (request.form.get("annual_income") or "").strip()
        # Sanitizar entrada: permitir "," o "." como separadores
        income_sanitized = income_raw.replace(" ", "").replace(",", ".")
        try:
            income_val = float(income_sanitized)
        except Exception:
            income_val = None

        # Nota: archivos no se guardan en esta demo
        # Validación de ingresos
        if income_val is None:
            flash("Introduce un ingreso anual válido.", "error")
            return render_template("advance.html", annual_income=income_raw)

        if income_val < 10000:
            # Mostrar popup con el mensaje solicitado y permanecer en la página
            popup_message = "NOOOO con estos ingresos no te podemos adelantear."
            return render_template("advance.html", annual_income=income_raw, popup_message=popup_message)

        flash("Solicitud de adelanto enviada (demo).", "ok")
        return redirect(url_for("requests_page"))

    return render_template("advance.html")


@app.route("/info")
@login_required
def info_page():
    return render_template("info.html")


@app.route("/schedules")
@login_required
def schedules_page():
    # Demo: cuadrante semanal vacío (Lunes a Domingo)
    return render_template('weekly.html')


@app.route("/time-info")
@login_required
def time_info_page():
    # Mueve el informe mensual de fichajes aquí
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        year = now.astimezone(TZ).year
        start_year = datetime(year, 1, 1, 0, 0, 0, tzinfo=TZ).astimezone(timezone.utc)
        end_year = datetime(year, 12, 31, 23, 59, 59, tzinfo=TZ).astimezone(timezone.utc)
        rows = db.execute(
            select(Attendance)
            .where(
                Attendance.user_id == current_user.id,
                Attendance.ts >= start_year,
                Attendance.ts <= end_year,
            )
            .order_by(Attendance.ts)
        ).scalars().all()

        by_day = {}
        for r in rows:
            ts_local = ensure_aware_utc(r.ts).astimezone(TZ)
            d = ts_local.date()
            by_day.setdefault(d, []).append((ts_local, r.action))

        import calendar
        months = []
        for month in range(1, 13):
            month_name = calendar.month_name[month].capitalize()
            _, days_in_month = calendar.monthrange(year, month)
            daily = []
            month_worked = 0
            month_expected = 0
            for day in range(1, days_in_month + 1):
                from datetime import date as date_cls
                d = date_cls(year, month, day)
                weekday = d.weekday()
                entries = by_day.get(d, [])
                pair_strs = []
                worked = 0
                last_in = None
                for ts, act in entries:
                    if act == AttendanceAction._in and last_in is None:
                        last_in = ts
                    elif act == AttendanceAction._out and last_in is not None:
                        delta = (ts - last_in).total_seconds()
                        if delta > 0:
                            worked += int(delta)
                            pair_strs.append(f"{last_in.strftime('%H:%M')} → {ts.strftime('%H:%M')}")
                        last_in = None
                expected = 27000 if weekday < 5 else 0
                month_worked += worked
                month_expected += expected
                daily.append({
                    'date': d.strftime('%d/%m/%Y'),
                    'pairs': pair_strs,
                    'worked_hm': fmt_hm(worked),
                    'expected_hm': fmt_hm(expected),
                    'balance_hm': fmt_hm(worked - expected),
                })
            months.append({
                'month': month,
                'name': month_name,
                'daily': daily,
                'month_worked_hm': fmt_hm(month_worked),
                'month_expected_hm': fmt_hm(month_expected),
                'month_balance_hm': fmt_hm(month_worked - month_expected),
            })

        current_month = now.astimezone(TZ).month
        return render_template('time_info.html', months=months, current_month=current_month)
    finally:
        db.close()


@app.route("/documents")
@login_required
def documents_page():
    # Demo: categorías típicas de documentos RRHH
    categories = [
        {"key": "contracts", "name": "Contratos", "items": []},
        {"key": "payrolls", "name": "Nóminas", "items": []},
        {"key": "withholding", "name": "Certificados de retenciones", "items": []},
        {"key": "others", "name": "Otros documentos", "items": []},
    ]
    return render_template("documents.html", categories=categories)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile_page():
    db = SessionLocal()
    try:
        if request.method == "POST":
            # Solo admin puede guardar cambios desde aquí (demo)
            if current_user.role != Role.admin:
                abort(403)
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            u = db.get(User, current_user.id)
            if not u:
                abort(404)
            if name:
                u.name = name
            if email:
                # Evitar colisión de emails de otros usuarios
                existing = db.execute(select(User).where(User.email == email, User.id != u.id)).scalar_one_or_none()
                if existing:
                    flash("Ese email ya está en uso.", "error")
                else:
                    u.email = email
            db.commit()
            flash("Perfil actualizado.", "ok")
            return redirect(url_for("profile_page"))

        # GET
        u = db.get(User, current_user.id)
        return render_template("profile.html", user=u)
    finally:
        db.close()


def _fmt_hms(seconds: int) -> str:
    seconds = int(max(0, seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


@app.route("/pause", methods=["POST"])
@login_required
def toggle_pause():
    db = SessionLocal()
    try:
        # ¿Hay una pausa abierta?
        active = db.execute(
            select(Pause)
            .where(Pause.user_id == current_user.id, Pause.end_ts.is_(None))
            .order_by(desc(Pause.start_ts))
        ).scalars().first()

        now = datetime.now(timezone.utc)
        if active:
            # Cerrar pausa
            active.end_ts = now
            db.commit()
            # Normalizar a UTC para evitar naive vs aware
            start_utc = ensure_aware_utc(active.start_ts)
            end_utc = ensure_aware_utc(active.end_ts)
            total_secs = int((end_utc - start_utc).total_seconds())
            mensaje_pause = f"Pausa finalizada. Duración: {_fmt_hms(total_secs)}"
            pausa_activa = False
            pausa_start_epoch = None
        else:
            # Abrir nueva pausa
            p = Pause(user_id=current_user.id, start_ts=now, end_ts=None)
            db.add(p)
            db.commit()
            mensaje_pause = "Pausa iniciada."
            pausa_activa = True
            pausa_start_epoch = now.timestamp()

        # Recalcular total del día EXCLUYENDO pausas activas
        day_start_utc, day_end_utc = local_day_bounds_utc(now)
        pauses = db.execute(
            select(Pause)
            .where(
                Pause.user_id == current_user.id,
                Pause.start_ts <= day_end_utc,
                Pause.end_ts.is_not(None),
                Pause.end_ts >= day_start_utc,
            )
        ).scalars().all()
        total_secs_today = 0
        for p in pauses:
            if not p.end_ts:
                continue
            p_start = ensure_aware_utc(p.start_ts)
            p_end = ensure_aware_utc(p.end_ts)
            start = max(p_start, day_start_utc)
            end = min(p_end, day_end_utc)
            if end > start:
                total_secs_today += int((end - start).total_seconds())

        return render_template(
            "_pause.html",
            pausa_activa=pausa_activa,
            pausa_start_epoch=pausa_start_epoch,
            mensaje_pause=mensaje_pause,
            server_now_utc=now.timestamp(),
            pause_total_today_fmt=_fmt_hms(total_secs_today),
        )
    finally:
        db.close()

@app.route("/time")
@login_required
def server_time():
    # Devolver el mismo span con atributos HTMX para que siga auto-actualizándose
    now_hms = to_local_hms(datetime.now(timezone.utc))
    return (
        '<span id="server-time" class="muted" '
        'hx-get="/time" hx-trigger="every 1s" hx-swap="outerHTML">'
        f"{now_hms}"
        "</span>"
    )


if __name__ == "__main__":
    # Debug siempre activo en desarrollo
    debug = True
    # Habilita autoreload si NO hay depurador adjunto (VS Code)
    # y permite forzarlo con FLASK_RELOAD=1|true|on
    import os, sys
    forced = os.getenv("FLASK_RELOAD")
    if forced is not None:
        use_reloader = forced.strip().lower() in ("1", "true", "on", "yes")
    else:
        use_reloader = (sys.gettrace() is None)
    app.run(debug=debug, use_reloader=use_reloader)
