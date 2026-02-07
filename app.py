from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import (
    SessionLocal,
    init_db_with_demo,
    User,
    Attendance,
    AttendanceAction,
    Role,
    Pause,
    TimeEntry,
    EntryStatus,
    Group,
    Area,
)
from rbac import can_view_user, can_edit_entries, require_view_user, require_edit_entry
from sqlalchemy import select, desc, func
from functools import wraps
from datetime import datetime, timezone
import json
import re
from collections import deque
from dotenv import load_dotenv
import random
from admin_panel import register_admin_panel
import jsonschema
from jsonschema import validate
import openai

PII_SCHEMA = {
    "type": "object",
    "properties": {
        "sensitive": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
                },
                "required": ["label", "value", "confidence"]
            }
        },
        "non_sensitive": {"type": "array"}
    },
    "required": ["sensitive", "non_sensitive"]
}

def validate_and_repair_json(json_str, schema, retry_count=1):
    """Intenta parsear y validar JSON. Si falla, intenta repararlo con LLM (1 intento)."""
    try:
        # Limpieza basica de markdown si el modelo se pone creativo
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
             json_str = json_str.split("```")[1].split("```")[0]
             
        data = json.loads(json_str)
        validate(instance=data, schema=schema)
        return data
    except (json.JSONDecodeError, jsonschema.ValidationError) as e:
        if retry_count > 0:
            print(f"JSON Error: {e}. Intentando reparar...")
            try:
                # Usamos client global si existe, o creamos uno efimero
                client = openai.Client() 
                repair_prompt = f"Fix this JSON to match schema. Respond ONLY with valid JSON.\nError: {str(e)}\nJSON:\n{json_str}"
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a JSON repair tool. Output only valid JSON matching the schema."},
                        {"role": "user", "content": repair_prompt}
                    ],
                    temperature=0
                )
                fixed_str = completion.choices[0].message.content
                if "```json" in fixed_str:
                    fixed_str = fixed_str.split("```json")[1].split("```")[0]
                elif "```" in fixed_str:
                    fixed_str = fixed_str.split("```")[1].split("```")[0]
                    
                data = json.loads(fixed_str)
                validate(instance=data, schema=schema)
                return data
            except Exception as repair_err:
                print(f"Repair failed: {repair_err}")
                
        # Fallback seguro
        return {"sensitive": [], "non_sensitive": [], "error": "Validation Failed"}

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

def parse_local_date(d: str):
    """Parsea 'YYYY-MM-DD' como datetime en zona local (00:00)."""
    try:
        parts = d.split('-')
        if len(parts) != 3:
            return None
        y, m, day = [int(x) for x in parts]
        return datetime(y, m, day, 0, 0, 0, tzinfo=TZ)
    except Exception:
        return None

import os

load_dotenv()

app = Flask(__name__)
# Lee SECRET_KEY del entorno, usa valor por defecto en desarrollo
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

from flask_wtf import CSRFProtect
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# Inicializa BD y usuario demo al arrancar
with app.app_context():
    init_db_with_demo()
    register_admin_panel(app)


@app.context_processor
def inject_template_globals():
    return {
        "current_year": datetime.now(TZ).year,
        # Nombre del propietario/empresa configurable por entorno
        "owner_name": os.environ.get("OWNER_NAME", "Fichaje Rapido"),
        "TZ": TZ,
    }


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


def admin_or_rrhh_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in (Role.admin, Role.rrhh):
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
    # Cargar lista de usuarios para el select principal de login
    db = SessionLocal()
    try:
        users_for_login = db.execute(select(User).order_by(User.name, User.email)).scalars().all()
    finally:
        db.close()
    return render_template("login.html", users_for_login=users_for_login, test_users=test_users, show_dev_login=show_dev_login)

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
        areas = db.execute(select(Area).order_by(Area.name)).scalars().all()
        supervisors = (
            db.execute(
                select(User)
                .where(User.is_active.is_(True), User.role.in_((Role.responsable, Role.cap_area, Role.rrhh, Role.admin)))
                .order_by(User.name.asc())
            )
            .scalars()
            .all()
        )
        return render_template(
            "admin/users.html",
            users=users,
            groups=groups,
            areas=areas,
            supervisors=supervisors,
        )
    finally:
        db.close()


@app.route("/admin/areas", methods=["GET"])
@login_required
@admin_or_rrhh_required
def admin_areas_page():
    db = SessionLocal()
    try:
        areas = db.execute(select(Area).order_by(Area.id)).scalars().all()
        manager_candidates = (
            db.execute(
                select(User)
                .where(User.is_active.is_(True), User.role.in_((Role.cap_area, Role.responsable, Role.rrhh, Role.admin)))
                .order_by(User.name.asc())
            )
            .scalars()
            .all()
        )
        return render_template(
            "admin/areas.html",
            areas=areas,
            managers=manager_candidates,
        )
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
    area_id = request.form.get("area_id")
    supervisor_id = request.form.get("supervisor_id")

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
        elif area_id:
            try:
                aid = int(area_id)
                area = db.get(Area, aid)
                if area:
                    u.area_id = area.id
            except Exception:
                pass
        if supervisor_id:
            try:
                sid = int(supervisor_id)
                supervisor = db.get(User, sid)
                if supervisor and supervisor.id != u.id:
                    u.supervisor_id = supervisor.id
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
            u.group_id = None
            group_name = "sin grupo"
        else:
            try:
                g = db.get(Group, int(group_id))
            except Exception:
                g = None
            if not g:
                flash("Grupo no encontrado.", "error")
                return redirect(url_for("admin_users"))
            u.group_id = g.id
            u.area_id = g.area_id
            group_name = g.name
        db.commit()
        flash(f"Grupo de {u.email} actualizado a {group_name}.", "ok")
        return redirect(url_for("admin_users"))
    finally:
        db.close()


@app.route("/admin/users/<int:user_id>/set_area", methods=["POST"])
@login_required
@admin_required
def admin_users_set_area(user_id):
    area_id = request.form.get("area_id")
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if not u:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for("admin_users"))
        if not area_id:
            u.area_id = None
            area_name = "sin área"
        else:
            try:
                a = db.get(Area, int(area_id))
            except Exception:
                a = None
            if not a:
                flash("Área no encontrada.", "error")
                return redirect(url_for("admin_users"))
            u.area_id = a.id
            area_name = a.name
        db.commit()
        flash(f"Área de {u.email} actualizada a {area_name}.", "ok")
        return redirect(url_for("admin_users"))
    finally:
        db.close()


@app.route("/admin/users/<int:user_id>/set_supervisor", methods=["POST"])
@login_required
@admin_required
def admin_users_set_supervisor(user_id):
    supervisor_id = (request.form.get("supervisor_id") or "").strip()
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if not u:
            flash("Usuario no encontrado.", "error")
            return redirect(url_for("admin_users"))
        if not supervisor_id:
            u.supervisor_id = None
            db.commit()
            flash(f"Supervisor de {u.email} eliminado.", "ok")
            return redirect(url_for("admin_users"))
        try:
            sid = int(supervisor_id)
        except Exception:
            flash("Supervisor inválido.", "error")
            return redirect(url_for("admin_users"))
        if sid == u.id:
            flash("Un usuario no puede ser su propio superior.", "error")
            return redirect(url_for("admin_users"))
        supervisor = db.get(User, sid)
        if not supervisor:
            flash("Supervisor no encontrado.", "error")
            return redirect(url_for("admin_users"))
        u.supervisor_id = supervisor.id
        db.commit()
        flash(f"Supervisor de {u.email} actualizado a {supervisor.name}.", "ok")
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
@admin_or_rrhh_required
def admin_areas_create():
    name = request.form.get("name", "").strip()
    manager_id_raw = (request.form.get("manager_id") or "").strip()
    if not name:
        flash("El nombre del área es obligatorio.", "error")
        return redirect(url_for("admin_areas_page"))
    db = SessionLocal()
    try:
        if db.execute(select(Area).where(Area.name == name)).first():
            flash("Ya existe un área con ese nombre.", "error")
            return redirect(url_for("admin_users"))
        a = Area(name=name)
        if manager_id_raw:
            try:
                manager = db.get(User, int(manager_id_raw))
                if manager:
                    a.manager_id = manager.id
            except Exception:
                flash("Responsable de área inválido.", "error")
                return redirect(url_for("admin_areas_page"))
        db.add(a)
        db.commit()
        if a.manager_id:
            manager = db.get(User, a.manager_id)
            if manager and manager.area_id != a.id:
                manager.area_id = a.id
                db.commit()
        flash("Área creada.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_areas_page"))


@app.route("/admin/areas/<int:area_id>/update", methods=["POST"])
@login_required
@admin_or_rrhh_required
def admin_areas_update(area_id):
    name = request.form.get("name", "").strip()
    manager_id_raw = (request.form.get("manager_id") or "").strip()
    db = SessionLocal()
    try:
        a = db.get(Area, area_id)
        if not a:
            flash("Área no encontrada.", "error")
            return redirect(url_for("admin_areas_page"))
        if name:
            a.name = name
        if manager_id_raw == "":
            a.manager_id = None
        elif manager_id_raw:
            try:
                manager = db.get(User, int(manager_id_raw))
            except Exception:
                manager = None
            if not manager:
                flash("Responsable de área inválido.", "error")
                return redirect(url_for("admin_areas_page"))
            a.manager_id = manager.id
            if manager.area_id != a.id:
                manager.area_id = a.id
        db.commit()
        flash("Área actualizada.", "ok")
    finally:
        db.close()
    return redirect(url_for("admin_areas_page"))


@app.route("/admin/areas/<int:area_id>/delete", methods=["POST"])
@login_required
@admin_or_rrhh_required
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
        allowed_user_ids = None
        if current_user.role == Role.employee:
            allowed_user_ids = {current_user.id}
        elif current_user.role == Role.responsable:
            allowed_user_ids = set()
            if current_user.group_id:
                allowed_user_ids.update(
                    db.execute(select(User.id).where(User.group_id == current_user.group_id)).scalars().all()
                )
        elif current_user.role == Role.cap_area:
            allowed_user_ids = set()
            if current_user.area_id:
                allowed_user_ids.update(
                    db.execute(select(User.id).where(User.area_id == current_user.area_id)).scalars().all()
                )
        elif current_user.role in (Role.rrhh, Role.admin):
            allowed_user_ids = None
        elif current_user.role == Role.invitado:
            from models import GuestAccess
            q = q.where(TimeEntry.user_id.in_(select(GuestAccess.target_user_id).where(GuestAccess.guest_user_id == current_user.id)))
        else:
            allowed_user_ids = {current_user.id}

        if allowed_user_ids is not None:
            direct_reports = db.execute(
                select(User.id).where(User.supervisor_id == current_user.id)
            ).scalars().all()
            allowed_user_ids.update(direct_reports)
            if allowed_user_ids:
                q = q.where(TimeEntry.user_id.in_(list(allowed_user_ids)))
            else:
                q = q.where(TimeEntry.user_id == -1)

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
@app.route("/pdf", methods=["GET"])
@login_required
def pdf_tools():
    return render_template("pdf_tool.html")


def _sanitize_candidate_list(candidates):
    clean = []
    for item in candidates or []:
        label = (item.get("label") or "").strip()
        value = (item.get("value") or "").strip()
        if not label or not value:
            continue
        clean.append({"label": label[:50], "value": value[:400]})
        if len(clean) >= 60:
            break
    return clean


def _excerpt_text(text: str, limit: int = 6000) -> str:
    trimmed = (text or "").strip()
    if len(trimmed) <= limit:
        return trimmed
    return trimmed[:limit] + "\n[...recortado...]"


def _parse_model_json(content: str) -> dict:
    """Intenta interpretar JSON aunque el modelo envíe envoltorios."""
    raw = (content or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty content", raw, 0)

    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        candidates.append(fence.group(1).strip())
    brace = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace:
        candidates.append(brace.group(0).strip())
    candidates.append(raw)

    last_exc: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_exc = exc
    if last_exc:
        raise last_exc
    raise json.JSONDecodeError("Unparseable JSON content", raw, 0)


def _normalize_model_output(parsed: object) -> tuple[list[dict], list[dict]]:
    """Acepta diferentes variantes de salida y normaliza a (sensitive, non_sensitive)."""
    sensitive: list[dict] = []
    non_sensitive: list[dict] = []

    def _push(target: list[dict], item: dict):
        label = (item.get("label") or item.get("data_type") or "").strip()
        value = (item.get("value") or "").strip()
        if not label or not value:
            return
        target.append(
            {
                "label": label[:50],
                "value": value[:400],
                "reason": (item.get("reason") or item.get("explanation") or "").strip()[:500],
                "confidence": (item.get("confidence") or item.get("confidence_level") or "").strip()[:40],
            }
        )

    if isinstance(parsed, dict):
        # Fallback para cuando el modelo usa 'sensitive_data' en lugar de 'sensitive'
        if "sensitive_data" in parsed:
            for item in parsed.get("sensitive_data") or []:
                if isinstance(item, dict):
                    _push(sensitive, item)
            # Si usa sensitive_data, probablemente no use non_sensitive normal, pero por si acaso
            for item in parsed.get("non_sensitive") or []:
                if isinstance(item, dict):
                    _push(non_sensitive, item)
            return sensitive, non_sensitive

        if "sensitive" in parsed or "non_sensitive" in parsed:
            for item in parsed.get("sensitive") or []:
                if isinstance(item, dict):
                    _push(sensitive, item)
            for item in parsed.get("non_sensitive") or []:
                if isinstance(item, dict):
                    _push(non_sensitive, item)
            return sensitive, non_sensitive
        results = parsed.get("results")
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                target = sensitive if item.get("is_personal_data") else non_sensitive
                _push(target, item)
            return sensitive, non_sensitive

    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            target = sensitive if item.get("is_personal_data") else non_sensitive
            _push(target, item)
        return sensitive, non_sensitive

    return sensitive, non_sensitive


def _ai_classify_sensitive(text: str, candidates: list[dict]):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada en el servidor.")
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - depende del runtime
        raise RuntimeError(f"Dependencia openai no disponible: {exc}") from exc

    client = OpenAI(api_key=api_key)
    model = os.environ.get("PDF_AI_MODEL", "gpt-4o-mini")
    try:
        max_tokens = int(os.environ.get("PDF_AI_MAX_OUTPUT_TOKENS", "4000"))
    except ValueError:
        max_tokens = 4000
    max_tokens = max(300, min(max_tokens, 16_000))
    try:
        chunk_size = int(os.environ.get("PDF_AI_CANDIDATES_PER_CALL", "50"))
    except ValueError:
        chunk_size = 50
    chunk_size = max(1, min(chunk_size, 60))

    try:
        excerpt_limit_env = int(os.environ.get("PDF_AI_EXCERPT_LIMIT", "6000"))
    except ValueError:
        excerpt_limit_env = 6000
    excerpt_limit_env = max(500, min(excerpt_limit_env, 12000))

    excerpt_candidates: list[int] = []
    for value in (
        excerpt_limit_env,
        excerpt_limit_env // 2,
        3000,
        2000,
        1200,
        800,
    ):
        value = max(500, min(value, 12000))
        if value not in excerpt_candidates:
            excerpt_candidates.append(value)

    excerpt_cache: dict[int, str] = {}

    # Prompt relajado para mejorar recall
    system_prompt = (
        "# ROL\n"
        "Eres un Oficial de Protección de Datos (DPO) especializado en RGPD/LOPD-GDD.\n"
        "Tu misión es identificar y clasificar TODOS los datos personales en documentos PDF para su censura/redacción.\n\n"
        
        "# CONTEXTO\n"
        "El usuario subirá PDFs de distintos tipos: facturas, informes médicos, documentos legales, nóminas, certificados administrativos.\n"
        "Cada dato identificado será censurado con un recuadro negro. Es CRÍTICO no omitir ningún dato sensible.\n\n"
        
        "# TAREAS\n"
        "1. CLASIFICAR cada candidato en 'sensitive' o 'non_sensitive'\n"
        "2. EXTRAER datos sensibles adicionales del 'document_excerpt' que no estén en los candidatos\n\n"
        
        "# TAXONOMÍA DE DATOS SENSIBLES (por categoría RGPD)\n\n"
        
        "## CATEGORÍA ESPECIAL (Art. 9 RGPD) - Máxima protección - CRÍTICO\n"
        "- Salud: Diagnósticos, medicamentos, nº historia clínica, informes médicos, discapacidad, baja médica, minusvalía, incapacidad\n"
        "- Biométricos: Huellas, patrones faciales, ADN\n"
        "- Orientación sexual: Cualquier referencia directa o indirecta\n"
        "- Ideología/Religión: Afiliación política, sindicatos (cuota sindical), creencias, partido\n"
        "- Origen étnico: Nacionalidad en contexto discriminatorio, etnia\n\n"
        
        "## DATOS FINANCIEROS - Alta protección - ALTO\n"
        "- Cuentas bancarias: IBAN, CCC, nº cuenta (ES12 3456...), CUALQUIER secuencia que parezca cuenta, nombres de bancos (ING, BBVA, Santander...)\n"
        "- Tarjetas: Números de tarjeta (aunque parciales), CVV, fecha expiración\n"
        "- Ingresos: Salario bruto/neto, nóminas, declaraciones IRPF, pensiones\n"
        "- Deudas: Embargos, apremios, ejecuciones fiscales, impagos, juzgado\n"
        "- Situación económica: Bono social, tarifa social, vulnerable, renta mínima\n\n"
        
        "## IDENTIFICADORES PERSONALES - Protección estándar\n"
        "- DNI/NIE/Pasaporte: 12345678A, X1234567B, números de pasaporte - ALTO\n"
        "- Seguridad Social: Nº afiliación SS, NAF - ALTO\n"
        "- Nombres completos: Nombre + apellidos de personas físicas (pacientes, doctores, clientes) - MEDIO\n"
        "- Fechas personales: Fecha nacimiento, fecha defunción, DOB - MEDIO\n"
        "- Direcciones: Calle, nº, piso, CP + localidad - CENSURAR TODAS LAS OCURRENCIAS - MEDIO\n"
        "- Códigos Postales: Asociados a domicilio son SENSIBLES - MEDIO\n"
        "- Teléfonos: Fijos/móviles, prefijos internacionales - MEDIO\n"
        "- Email: Direcciones de correo electrónico personal - MEDIO\n\n"
        
        "## DATOS LEGALES/JUDICIALES - ALTO\n"
        "- Expedientes judiciales: Nº procedimiento, juzgado, sentencias\n"
        "- Antecedentes: Referencias a condenas, delitos - CRÍTICO\n"
        "- Matrículas vehículos: 1234 ABC, M-1234-AB\n"
        "- Referencias catastrales: Identificadores de propiedades\n\n"
        
        "## DATOS ADMINISTRATIVOS/CENSO - MEDIO\n"
        "- Composición familiar: 'X personas empadronadas', 'familia numerosa', habitantes\n"
        "- Nº expediente: Referencias administrativas con datos asociables\n"
        "- Códigos de barras/QR: Si codifican datos personales\n"
        "- Firmas/Sellos: Firmas manuscritas digitalizadas\n\n"
        
        "# REGLAS DE CLASIFICACIÓN\n"
        "1. PRINCIPIO DE PRECAUCIÓN: Ante la MÍNIMA duda → 'sensitive' con confidence 'high'\n"
        "2. DUPLICADOS: Si un dato aparece múltiples veces, INCLUIR TODAS las ocurrencias\n"
        "3. CONTEXTO: Un código postal solo es 'no sensible' si NO está asociado a una dirección\n"
        "4. EMPRESAS: Nombres de empresas/organismos públicos NO son datos personales (excepto autónomos)\n"
        "5. FECHAS: 'Enero 2024' genérico no es sensible; '12/05/1985 (fecha nacimiento)' SÍ lo es\n\n"
        
        "# EJEMPLOS\n"
        "- Factura con IBAN: {\"label\": \"IBAN\", \"value\": \"ES12 3456 7890 1234\", \"reason\": \"Cuenta bancaria - dato financiero protegido\", \"confidence\": \"high\"}\n"
        "- Informe médico: {\"label\": \"Nombre paciente\", \"value\": \"María García\", \"reason\": \"Identidad en contexto sanitario - Art. 9 RGPD\", \"confidence\": \"high\"}\n"
        "- Certificado censo: {\"label\": \"Composición familiar\", \"value\": \"5 personas empadronadas\", \"reason\": \"Estructura del hogar - dato censal\", \"confidence\": \"high\"}\n\n"
        
        "Responde EXCLUSIVAMENTE con un único objeto JSON que cumpla el siguiente esquema:\n"
        "{\n"
        '  "sensitive": [{"label": "...", "value": "...", "reason": "...", "confidence": "high|medium|low"}],\n'
        '  "non_sensitive": []\n'
        "}"
    )
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "sensitive_data_classification",
            "schema": {
                "type": "object",
                "properties": {
                    "sensitive": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                                "reason": {"type": "string"},
                                "confidence": {"type": "string"},
                            },
                            "required": ["label", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "non_sensitive": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                                "reason": {"type": "string"},
                                "confidence": {"type": "string"},
                            },
                            "required": ["label", "value"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["sensitive", "non_sensitive"],
                "additionalProperties": False,
            },
        },
    }

    total_chunks = (len(candidates) + chunk_size - 1) // chunk_size or 1
    combined_sensitive: list[dict] = []
    combined_non_sensitive: list[dict] = []
    # Colección de trazas de depuración
    debug_traces: list[dict] = []
    
    supports_response_format = True
    queue = deque()

    for chunk_index in range(total_chunks):
        chunk = candidates[chunk_index * chunk_size : (chunk_index + 1) * chunk_size]
        if not chunk:
            continue
        queue.append(
            {
                "chunk": chunk,
                "info": {
                    "index": chunk_index + 1,
                    "total": total_chunks,
                    "size": len(chunk),
                    "split_level": 0,
                    "split_part": None,
                },
            }
        )

    if not queue:
        return {"sensitive": [], "non_sensitive": [], "model": model, "debug": []}

    def _get_excerpt(limit: int) -> str:
        if limit not in excerpt_cache:
            excerpt_cache[limit] = _excerpt_text(text, limit=limit)
        return excerpt_cache[limit]

    def _call_model(chunk: list[dict], chunk_info: dict, excerpt_text: str):
        nonlocal supports_response_format
        payload = {
            "document_excerpt": excerpt_text,
            "candidates": chunk,
            "chunk_info": chunk_info,
        }
        user_prompt = json.dumps(payload, ensure_ascii=False)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        request_kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if supports_response_format:
            request_kwargs["response_format"] = response_format
        
        # Trace info for this call
        debug_payload = payload.copy()
        if len(debug_payload.get("document_excerpt", "")) > 200:
             debug_payload["document_excerpt"] = debug_payload["document_excerpt"][:200] + "... [TRUNCATED FOR LOG]"
        
        trace_entry = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "input_system": system_prompt,
            "input_user": json.dumps(debug_payload, ensure_ascii=False),
            "output_raw": None,
            "error": None
        }

        content = None
        truncated = False
        
        try:
            # CORRECT STANDARD CALL
            response = client.chat.completions.create(**request_kwargs)
            choice = response.choices[0]
            content = choice.message.content
            if choice.finish_reason == "length":
                truncated = True
        except TypeError as exc:
            # Fallback for older library versions that don't support response_format
            if supports_response_format and "response_format" in str(exc):
                supports_response_format = False
                request_kwargs.pop("response_format", None)
                # Retry without response_format
                response = client.chat.completions.create(**request_kwargs)
                choice = response.choices[0]
                content = choice.message.content
                if choice.finish_reason == "length":
                    truncated = True
            else:
                trace_entry["error"] = str(exc)
                debug_traces.append(trace_entry)
                raise
        except Exception as exc:
            trace_entry["error"] = str(exc)
            debug_traces.append(trace_entry)
            raise RuntimeError(f"Fallo al invocar al modelo {model}: {exc}") from exc

        trace_entry["output_raw"] = content
        trace_entry["finish_reason"] = choice.finish_reason if choice else None
        debug_traces.append(trace_entry)

        if not content:
            # Log detailed info to help diagnose empty responses
            app.logger.error(
                f"Empty content from model {model}. "
                f"finish_reason={choice.finish_reason if choice else 'N/A'}, "
                f"response={response}"
            )
            raise RuntimeError(f"El modelo {model} devolvió una respuesta vacía (finish_reason: {choice.finish_reason if choice else 'N/A'})")

        parsed = validate_and_repair_json(content, PII_SCHEMA)
        if "error" in parsed:
             # Si falla validación tras reintento, lanzamos error para que se capture y registre
             raise RuntimeError(f"JSON Validation Failed: {parsed.get('error')}")

        sensitive_chunk, non_sensitive_chunk = _normalize_model_output(parsed)
        return sensitive_chunk, non_sensitive_chunk, truncated

    while queue:
        current = queue.popleft()
        chunk = current["chunk"]
        chunk_info = current["info"]
        if not chunk:
            continue

        truncated = True
        last_error = None
        for limit in excerpt_candidates:
            excerpt_text = _get_excerpt(limit)
            try:
                sensitive_chunk, non_sensitive_chunk, truncated = _call_model(chunk, {**chunk_info, "excerpt_limit": limit}, excerpt_text)
                last_error = None
            except RuntimeError as exc:
                last_error = exc
                truncated = False # Stop retrying limits if it's a runtime error not related to context length? 
                                  # Actually, the original code treated RuntimeError as a break condition for the limit loop. 
                                  # We keep it similar but ensuring traces are logged inside _call_model.
                break
            if not truncated:
                combined_sensitive.extend(sensitive_chunk)
                combined_non_sensitive.extend(non_sensitive_chunk)
                break
        else:
            # Loop exhausted without break (still truncated for all limits)
            truncated = True

        if last_error:
            raise last_error

        if truncated:
            if len(chunk) <= 1:
                raise RuntimeError(
                    "La respuesta del modelo fue truncada incluso reduciendo el contexto. "
                    "Reduce el tamaño del PDF o el número de candidatos para esta sección."
                )
            mid = len(chunk) // 2
            left = chunk[:mid]
            right = chunk[mid:]
            split_level = chunk_info.get("split_level", 0) + 1
            # Process left chunk first preserving order
            if right:
                queue.appendleft(
                    {
                        "chunk": right,
                        "info": {
                            **chunk_info,
                            "size": len(right),
                            "split_level": split_level,
                            "split_part": "right",
                        },
                    }
                )
            if left:
                queue.appendleft(
                    {
                        "chunk": left,
                        "info": {
                            **chunk_info,
                            "size": len(left),
                            "split_level": split_level,
                            "split_part": "left",
                        },
                    }
                )
            continue

    return {
        "sensitive": combined_sensitive,
        "non_sensitive": combined_non_sensitive,
        "model": model,
        "debug": debug_traces,
    }

@app.route("/api/pdf/redact", methods=["POST"])
@login_required
def api_pdf_redact():
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return jsonify({"ok": False, "error": "Librería de redacción segura (PyMuPDF) no instalada en el servidor."}), 501

    if 'file' not in request.files:
         return jsonify({"ok": False, "error": "No se recibió archivo PDF."}), 400
    
    file = request.files['file']
    redactions_json = request.form.get('redactions', '[]')
    try:
        redactions = json.loads(redactions_json)
    except:
        redactions = []

    if not file or file.filename == '':
        return jsonify({"ok": False, "error": "Archivo vacío."}), 400

    try:
        # Procesar en memoria
        pdf_bytes = file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        for r in redactions:
            page_num = int(r.get('page', 1)) - 1 # 1-based a 0-based
            if page_num < 0 or page_num >= doc.page_count:
                continue
                
            page = doc[page_num]
            # Coordenadas: [x, y, width, height] -> rect [x, y, x+w, y+h]
            # Nota: fitz usa coordenadas bottom-left? No, top-left standard.
            # pdf.js da [x, y, w, h] con y invertida a veces?
            # Asumimos que frontend manda: x, y, width, height en sistema PDF standard.
            
            x, y, w, h = r.get('x', 0), r.get('y', 0), r.get('width', 0), r.get('height', 0)
            
            # PDF (frontend/pdf.js) uses Bottom-Left origin.
            # PyMuPDF uses Top-Left origin.
            # We must flip the Y coordinate.
            # pdf.js 'y' is the baseline/bottom of text component.
            # So the box goes from y to y+h in PDF space.
            # In PyMuPDF:
            # Top Y = page.rect.height - (y + h)
            # Bottom Y = page.rect.height - y
            
            page_h = page.rect.height
            # Invert Y
            ry0 = page_h - (y + h)
            ry1 = page_h - y
            
            # Adjust slightly for baseline descent if needed, but strict box is safer.
            # Ensure ry0 < ry1
            if ry0 > ry1:
                ry0, ry1 = ry1, ry0
                
            rect = fitz.Rect(x, ry0, x + w, ry1)
            
            # Añadir anotación de redacción
            page.add_redact_annot(rect, fill=(0, 0, 0)) # Relleno negro
            
        # Aplicar redacciones (elimina text/imagenes e impacta las anotaciones)
        for page in doc:
            page.apply_redactions()
            
        output_bytes = doc.tobytes()
        doc.close()
        
        # Devolver archivo
        from io import BytesIO
        from flask import send_file
        return send_file(
            BytesIO(output_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name='documento_censurado_seguro.pdf'
        )

    except Exception as e:
        app.logger.error(f"Error redacting PDF: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


def _ai_extract_sensitive(text: str):
    """
    Simplified: sends text directly to AI to find all sensitive data.
    No regex pre-filtering, no candidate lists.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada en el servidor.")
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(f"Dependencia openai no disponible: {exc}") from exc

    client = OpenAI(api_key=api_key)
    model = os.environ.get("PDF_AI_MODEL", "gpt-4o-mini")
    
    # Simplified system prompt (~300 tokens instead of ~900)
    system_prompt = """Eres un DPO (Oficial de Protección de Datos) especializado en RGPD.

TAREA: Analiza el texto del documento y encuentra TODOS los datos personales sensibles.

BUSCAR:
- Nombres completos de personas (no empresas)
- DNI/NIE/Pasaporte (ej: 12345678A, X1234567B)
- Direcciones postales completas (calle, número, piso, código postal, ciudad)
- Teléfonos (fijos y móviles, ej: 612345678, 934567890)
- Emails personales
- Fechas de nacimiento
- IBAN y cuentas bancarias (ej: ES12 3456 7890 1234 5678 9012)
- Números de cuenta (CCC, código cuenta cliente)
- Datos de salud (diagnósticos, historiales clínicos, nº historia clínica)
- Datos financieros (ingresos, deudas, embargos, nóminas)
- Números de Seguridad Social / NAF

REGLAS:
- Ante la duda, incluir el dato
- Incluir TODAS las ocurrencias (aunque se repitan)
- NO incluir nombres de empresas u organismos públicos

RESPUESTA: Solo JSON válido:
{"sensitive": [{"label": "tipo", "value": "dato exacto", "reason": "explicación"}]}"""

    # Truncate text if too long
    max_text_length = int(os.environ.get("PDF_AI_MAX_TEXT", "8000"))
    truncated_text = text[:max_text_length] if len(text) > max_text_length else text
    if len(text) > max_text_length:
        truncated_text += "\n... [TEXTO TRUNCADO]"
    
    user_prompt = f"Analiza este documento:\n\n{truncated_text}"
    
    debug_trace = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "text_length": len(text),
        "input_system": system_prompt,
        "input_user": user_prompt[:500] + "..." if len(user_prompt) > 500 else user_prompt,
        "output_raw": None,
        "error": None
    }
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0,
            max_tokens=4000,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        debug_trace["output_raw"] = content
        
        if not content:
            raise RuntimeError("El modelo devolvió una respuesta vacía")
        
        data = json.loads(content)
        sensitive = data.get("sensitive", [])
        
        # Ensure required fields
        for item in sensitive:
            if "label" not in item:
                item["label"] = "Dato sensible"
            if "reason" not in item:
                item["reason"] = "Dato personal identificado"
            if "confidence" not in item:
                item["confidence"] = "high"
        
        return {
            "sensitive": sensitive,
            "non_sensitive": [],
            "model": model,
            "debug": [debug_trace]
        }
        
    except json.JSONDecodeError as e:
        debug_trace["error"] = f"JSON inválido: {e}"
        raise RuntimeError(f"Respuesta JSON inválida del modelo: {e}") from e
    except Exception as exc:
        debug_trace["error"] = str(exc)
        raise RuntimeError(f"Error al analizar con IA: {exc}") from exc


@app.route("/api/pdf/analyze", methods=["POST"])
@login_required
def api_pdf_analyze():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    
    if not text:
        return jsonify({"ok": False, "error": "El texto del PDF es obligatorio."}), 400
    
    try:
        result = _ai_extract_sensitive(text)
    except RuntimeError as exc:
        app.logger.warning("AI extraction failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        app.logger.error("AI extraction failed (unexpected): %s", exc, exc_info=True)
        return jsonify({"ok": False, "error": f"Error inesperado: {type(exc).__name__}: {str(exc)}"}), 500
    
    return jsonify({"ok": True, **result})


@app.route("/requests")
@login_required
def requests_page():
    return render_template("requests.html")


# --------- AUSENCIAS (VACACIONES) ---------
from models import Absence, EntryStatus

def _is_approver_for(approver: User, target: User) -> bool:
    if approver.role in (Role.admin, Role.rrhh):
        return True
    if target.supervisor_id and target.supervisor_id == approver.id:
        return True
    if approver.role == Role.responsable:
        return approver.group_id and approver.group_id == target.group_id
    if approver.role == Role.cap_area:
        return approver.area_id and approver.area_id == target.area_id
    return False


@app.route("/absences", methods=["GET"])
@login_required
def absences_page():
    db = SessionLocal()
    try:
        mine = db.execute(select(Absence).where(Absence.user_id == current_user.id).order_by(Absence.date_from.desc())).scalars().all()

        pending_for_me = []
        if current_user.role in (Role.admin, Role.rrhh, Role.responsable, Role.cap_area):
            user_ids = set()
            if current_user.role in (Role.admin, Role.rrhh):
                user_ids.update(db.execute(select(User.id)).scalars().all())
            elif current_user.role == Role.responsable and current_user.group_id:
                user_ids.update(
                    db.execute(select(User.id).where(User.group_id == current_user.group_id)).scalars().all()
                )
            elif current_user.role == Role.cap_area and current_user.area_id:
                user_ids.update(
                    db.execute(select(User.id).where(User.area_id == current_user.area_id)).scalars().all()
                )
            user_ids.update(
                db.execute(select(User.id).where(User.supervisor_id == current_user.id)).scalars().all()
            )
            if user_ids:
                pending_for_me = db.execute(
                    select(Absence)
                    .where(Absence.user_id.in_(list(user_ids)), Absence.status == EntryStatus.pending)
                    .order_by(Absence.date_from.desc())
                ).scalars().all()
                pending_for_me = [
                    absence
                    for absence in pending_records
                    if absence.can_be_validated_by(current_user)
                ]

        return render_template("absences.html", mine=mine, pending=pending_for_me)
    finally:
        db.close()


@app.route("/absences/create", methods=["POST"])
@login_required
def absences_create():
    a_type = (request.form.get("type") or "").strip().lower()
    a_subtype = (request.form.get("subtype") or "").strip().lower() or None
    f = parse_local_date(request.form.get("from") or "")
    t = parse_local_date(request.form.get("to") or "")
    if not a_type or not f or not t:
        flash("Faltan campos obligatorios.", "error")
        return redirect(url_for("absences_page"))
    if t < f:
        flash("Rango de fechas inválido.", "error")
        return redirect(url_for("absences_page"))

    start_utc = f.astimezone(timezone.utc)
    end_utc = t.replace(hour=23, minute=59, second=59, microsecond=999999).astimezone(timezone.utc)

    db = SessionLocal()
    try:
        rec = Absence(user_id=current_user.id, date_from=start_utc, date_to=end_utc, type=a_type, subtype=a_subtype, status=EntryStatus.pending)
        db.add(rec)
        db.commit()
        flash("Solicitud de ausencia creada.", "ok")
    finally:
        db.close()
    return redirect(url_for("absences_page"))


@app.route("/absences/<int:abs_id>/approve", methods=["POST"])
@login_required
def absences_approve(abs_id):
    db = SessionLocal()
    try:
        a = db.get(Absence, abs_id)
        if not a:
            abort(404)
        if not a.can_be_validated_by(current_user):
            abort(403)
        a.status = EntryStatus.approved
        db.commit()
        flash("Ausencia aprobada.", "ok")
        return redirect(url_for("absences_page"))
    finally:
        db.close()


@app.route("/absences/<int:abs_id>/reject", methods=["POST"])
@login_required
def absences_reject(abs_id):
    db = SessionLocal()
    try:
        a = db.get(Absence, abs_id)
        if not a:
            abort(404)
        if not a.can_be_validated_by(current_user):
            abort(403)
        a.status = EntryStatus.rejected
        db.commit()
        flash("Ausencia rechazada.", "ok")
        return redirect(url_for("absences_page"))
    finally:
        db.close()


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




@app.route("/firmas")
@login_required
def firmas_page():
    defaults = {
        "full_name": "Laura Martinez",
        "role": "Head of Customer Success",
        "company": "Fichaje Labs",
        "phone": "+34 900 123 456",
        "mobile": "+34 600 123 123",
        "email": "laura.martinez@fichaje.com",
        "website": "www.fichaje.com",
        "profile_photo_url": "https://randomuser.me/api/portraits/women/44.jpg",
        "logo_url": "https://dummyimage.com/110x40/0a84ff/ffffff.png&text=Fichaje",
        "logo_secondary_url": "https://dummyimage.com/110x40/111827/ffffff.png&text=HQ",
        "logo_tertiary_url": "https://dummyimage.com/110x40/cccccc/111111.png&text=ISO",
        "cta_label": "Agenda una demo",
        "cta_url": "https://calendly.com/fichaje/demo",
        "banner_text": "Impulsa la identidad visual en cada correo.",
        "primary_color": "#0A84FF",
        "accent_color": "#111827",
        "disclaimer": "Este pie de firma se genera automaticamente para la prueba de proyecto independiente.",
        "linkedin": "https://www.linkedin.com/company/fichaje",
        "twitter": "https://twitter.com/fichaje",
        "instagram": "",
        "youtube": "",
        "tagline": "Construyendo experiencias memorables.",
        "theme": "classic-split",
        "badge_text": "",
        "badge_color": "#FFB020",
    }
    color_presets = [
        {"label": "Azul corporativo", "primary": "#0A84FF", "accent": "#111827"},
        {"label": "Verde sostenible", "primary": "#0B8A6A", "accent": "#0F2A1C"},
        {"label": "Naranja creativo", "primary": "#FF7A18", "accent": "#2D1600"},
        {"label": "Neutro elegante", "primary": "#3C3C3C", "accent": "#939393"},
    ]
    social_networks = [
        {"key": "linkedin", "label": "LinkedIn", "placeholder": "https://linkedin.com/in/tu-nombre"},
        {"key": "twitter", "label": "Twitter", "placeholder": "https://x.com/usuario"},
        {"key": "instagram", "label": "Instagram", "placeholder": "https://instagram.com/usuario"},
        {"key": "youtube", "label": "YouTube", "placeholder": "https://youtube.com/@canal"},
    ]
    profile_photos = [
        {"label": "Laura (CS)", "role": "Customer Success", "url": "https://randomuser.me/api/portraits/women/44.jpg"},
        {"label": "Daniel (Mkt)", "role": "Marketing", "url": "https://randomuser.me/api/portraits/men/23.jpg"},
        {"label": "Nora (Producto)", "role": "Product", "url": "https://randomuser.me/api/portraits/women/12.jpg"},
        {"label": "Victor (Soporte)", "role": "Support", "url": "https://randomuser.me/api/portraits/men/32.jpg"},
        {"label": "Ines (Eventos)", "role": "Events", "url": "https://randomuser.me/api/portraits/women/68.jpg"},
        {"label": "Marcos (Talento)", "role": "People", "url": "https://randomuser.me/api/portraits/men/52.jpg"},
        {"label": "Sara (Partners)", "role": "Alliances", "url": "https://randomuser.me/api/portraits/women/11.jpg"},
        {"label": "Leo (Ops)", "role": "Operations", "url": "https://randomuser.me/api/portraits/men/29.jpg"},
        {"label": "Eva (Legal)", "role": "Legal", "url": "https://randomuser.me/api/portraits/women/48.jpg"},
        {"label": "Hector (Wellness)", "role": "Wellness", "url": "https://randomuser.me/api/portraits/men/80.jpg"},
    ]
    logo_library = [
        {"label": "Fichaje Labs", "url": "https://dummyimage.com/110x40/0a84ff/ffffff.png&text=Fichaje"},
        {"label": "Growfy", "url": "https://dummyimage.com/110x40/ff6b2c/ffffff.png&text=Growfy"},
        {"label": "Launchy", "url": "https://dummyimage.com/110x40/00b2a9/ffffff.png&text=Launchy"},
        {"label": "NovaCare", "url": "https://dummyimage.com/110x40/9333ea/ffffff.png&text=Nova"},
        {"label": "Sunrise", "url": "https://dummyimage.com/110x40/fcd34d/111111.png&text=Sunrise"},
        {"label": "LexCorp", "url": "https://dummyimage.com/110x40/0f172a/ffffff.png&text=Lex"},
        {"label": "EcoPulse", "url": "https://dummyimage.com/110x40/16a34a/ffffff.png&text=Eco"},
        {"label": "Eventia", "url": "https://dummyimage.com/110x40/f97316/ffffff.png&text=Event"},
        {"label": "Omnilink", "url": "https://dummyimage.com/110x40/1d4ed8/ffffff.png&text=Omni"},
        {"label": "Wellbeing Co", "url": "https://dummyimage.com/110x40/14b8a6/ffffff.png&text=Wellness"},
    ]
    themes = [
        {"key": "classic-split", "label": "Clasico dividido (dos columnas)"},
        {"key": "left-highlight", "label": "Barra vertical moderna"},
        {"key": "card-compact", "label": "Tarjeta compacta"},
        {"key": "photo-focus", "label": "Foto centrada minimal"},
        {"key": "bold-banner", "label": "Banner superior llamativo"},
        {"key": "dark-strip", "label": "Bloque oscuro elegante"},
        {"key": "logo-stack", "label": "Logos destacados"},
    ]
    signature_presets = [
        {
            "name": "Clasica corporativa",
            "description": "Distribucion a dos columnas con logos alineados al lado.",
            "data": dict(defaults),
        },
        {
            "name": "Impacto marketing",
            "description": "Tema banner destacado con CTA superior.",
            "data": dict(
                defaults,
                theme="bold-banner",
                full_name="Daniel Rios",
                role="Marketing Lead",
                company="Growfy",
                phone="+34 933 123 999",
                mobile="+34 722 111 222",
                email="daniel.rios@growfy.co",
                website="growfy.co",
                tagline="Campanas omnicanal y creatividad digital.",
                badge_text="Novedad 2026",
                badge_color="#FFD166",
                cta_label="Descarga el media kit",
                cta_url="https://growfy.co/media-kit",
                banner_text="Lanzamos nuevo reporte de tendencias 2026.",
                primary_color="#FF6B2C",
                accent_color="#1F1F1F",
                profile_photo_url="https://randomuser.me/api/portraits/men/23.jpg",
                logo_url="https://dummyimage.com/110x40/ff6b2c/ffffff.png&text=Growfy",
                logo_secondary_url="https://dummyimage.com/110x40/f97316/ffffff.png&text=Event",
                logo_tertiary_url="https://dummyimage.com/110x40/ffd166/111111.png&text=Hub",
                instagram="https://instagram.com/growfy_creative",
            ),
        },
        {
            "name": "Soporte global 24/7",
            "description": "Barra vertical con foto circular para equipos de soporte.",
            "data": dict(
                defaults,
                theme="left-highlight",
                full_name="Victor Ruiz",
                role="Global Support Lead",
                company="Omnilink",
                phone="+34 910 333 999",
                mobile="+34 600 440 880",
                email="victor.ruiz@omnilink.io",
                website="omnilink.io/help",
                tagline="Respuestas en menos de 5 minutos.",
                badge_text="24/7",
                badge_color="#1D4ED8",
                cta_label="Ver estado de la plataforma",
                cta_url="https://status.omnilink.io",
                banner_text="Canales premium + WhatsApp + Slack Connect.",
                primary_color="#1D4ED8",
                accent_color="#0F172A",
                profile_photo_url="https://randomuser.me/api/portraits/men/32.jpg",
                logo_url="https://dummyimage.com/110x40/1d4ed8/ffffff.png&text=Omni",
                logo_secondary_url="https://dummyimage.com/110x40/0a84ff/ffffff.png&text=Fichaje",
                logo_tertiary_url="https://dummyimage.com/110x40/ced4ff/111111.png&text=ISO",
                linkedin="https://www.linkedin.com/company/omnilink",
            ),
        },
        {
            "name": "Startup minimal",
            "description": "Tarjeta compacta con fondo claro y CTA simple.",
            "data": dict(
                defaults,
                theme="card-compact",
                full_name="Nora Vidal",
                role="Product Manager",
                company="Launchy",
                phone="+34 910 001 002",
                mobile="+34 611 202 303",
                email="nora@launchy.app",
                website="launchy.app",
                tagline="Roadmaps livianos y lanzamientos coordinados.",
                badge_text="Beta publica",
                badge_color="#00B2A9",
                cta_label="Probar gratis",
                cta_url="https://app.launchy.app/signup",
                banner_text="Gestiona tus lanzamientos desde Launchy.",
                primary_color="#00B2A9",
                accent_color="#062225",
                profile_photo_url="https://randomuser.me/api/portraits/women/12.jpg",
                logo_url="https://dummyimage.com/110x40/00b2a9/ffffff.png&text=Launchy",
                logo_secondary_url="https://dummyimage.com/110x40/16a34a/ffffff.png&text=Eco",
                logo_tertiary_url="",
                linkedin="https://www.linkedin.com/company/launchy-app",
                twitter="https://twitter.com/launchy_app",
            ),
        },
        {
            "name": "Estudio creativo",
            "description": "Tema foto centrada inspirado en agencias boutique.",
            "data": dict(
                defaults,
                theme="photo-focus",
                full_name="Ines Fabra",
                role="Directora Creative Studio",
                company="Eventia",
                phone="+34 910 222 100",
                mobile="+34 699 100 200",
                email="ines@eventia.eu",
                website="eventia.eu/studio",
                tagline="Diseno experiencial y storytelling inmersivo.",
                badge_text="Showcase 2025",
                badge_color="#F97316",
                cta_label="Reservar moodboard",
                cta_url="https://eventia.eu/showcase",
                banner_text="Summit Experience 2025 - 12 al 14 noviembre",
                primary_color="#F97316",
                accent_color="#1F2933",
                profile_photo_url="https://randomuser.me/api/portraits/women/68.jpg",
                logo_url="https://dummyimage.com/110x40/f97316/ffffff.png&text=Event",
                logo_secondary_url="https://dummyimage.com/110x40/fcd34d/111111.png&text=Sunrise",
                logo_tertiary_url="https://dummyimage.com/110x40/ff6b2c/ffffff.png&text=Bold",
                instagram="https://instagram.com/eventia_live",
            ),
        },
        {
            "name": "Consultoria legal premium",
            "description": "Tema oscuro elegante con tiras y texto formal.",
            "data": dict(
                defaults,
                theme="dark-strip",
                full_name="Eva Ramos",
                role="Socia directora",
                company="LexCorp",
                phone="+34 910 555 600",
                mobile="+34 699 555 000",
                email="eva.ramos@lexcorp.es",
                website="lexcorp.es",
                tagline="Especialistas en compliance y fusiones.",
                badge_text="Confidencial",
                badge_color="#8B5CF6",
                cta_label="Agendar consulta",
                cta_url="https://lexcorp.es/contacto",
                banner_text="Atendemos nuevos casos corporativos en 2025.",
                primary_color="#0F172A",
                accent_color="#94A3B8",
                profile_photo_url="https://randomuser.me/api/portraits/women/48.jpg",
                logo_url="https://dummyimage.com/110x40/0f172a/ffffff.png&text=Lex",
                logo_secondary_url="https://dummyimage.com/110x40/111827/ffffff.png&text=HQ",
                logo_tertiary_url="https://dummyimage.com/110x40/cccccc/111111.png&text=ISO",
                disclaimer="La informacion contenida en este correo es confidencial y podria estar sujeta a secreto profesional.",
                linkedin="https://www.linkedin.com/company/lexcorp-spain",
            ),
        },
        {
            "name": "Programas de bienestar",
            "description": "Bloque logo-stack con recursos saludables.",
            "data": dict(
                defaults,
                theme="logo-stack",
                full_name="Hector Mena",
                role="Wellness Director",
                company="NovaCare",
                phone="+34 931 400 900",
                mobile="+34 644 100 300",
                email="hector@novacare.health",
                website="novacare.health",
                tagline="Acompanamiento integral para equipos remotos.",
                badge_text="Nuevo programa Q4",
                badge_color="#14B8A6",
                cta_label="Unete al reto saludable",
                cta_url="https://novacare.health/reto",
                banner_text="Sesiones de mindfulness cada viernes.",
                primary_color="#14B8A6",
                accent_color="#134E4A",
                profile_photo_url="https://randomuser.me/api/portraits/men/80.jpg",
                logo_url="https://dummyimage.com/110x40/14b8a6/ffffff.png&text=Wellness",
                logo_secondary_url="https://dummyimage.com/110x40/16a34a/ffffff.png&text=Eco",
                logo_tertiary_url="https://dummyimage.com/110x40/00b2a9/ffffff.png&text=Launchy",
                instagram="https://instagram.com/novacare_health",
                youtube="https://youtube.com/@novacare",
            ),
        },
        {
            "name": "Hospitalidad boutique",
            "description": "Tema foto centrada con badge premium.",
            "data": dict(
                defaults,
                theme="photo-focus",
                full_name="Leo Romero",
                role="Hospitality Manager",
                company="Sunrise Hotels",
                phone="+34 952 200 100",
                mobile="+34 666 120 450",
                email="leo.romero@sunrisehotels.es",
                website="sunrisehotels.es",
                tagline="Experiencias mediterraneas personalizadas.",
                badge_text="Luxury pick",
                badge_color="#FCD34D",
                cta_label="Reservar visita",
                cta_url="https://sunrisehotels.es/reserva",
                banner_text="Nuevo hotel boutique abierto en Mallorca.",
                primary_color="#FCD34D",
                accent_color="#78350F",
                profile_photo_url="https://randomuser.me/api/portraits/men/29.jpg",
                logo_url="https://dummyimage.com/110x40/fcd34d/111111.png&text=Sunrise",
                logo_secondary_url="https://dummyimage.com/110x40/f97316/ffffff.png&text=Event",
                logo_tertiary_url="https://dummyimage.com/110x40/cccccc/111111.png&text=Michelin",
                instagram="https://instagram.com/sunrisehotels",
            ),
        },
        {
            "name": "Alianzas SaaS",
            "description": "Tarjeta logo-stack con logotipos de partners.",
            "data": dict(
                defaults,
                theme="logo-stack",
                full_name="Sara Molina",
                role="Strategic Alliances",
                company="Synergy Cloud",
                phone="+34 917 777 700",
                mobile="+34 611 888 777",
                email="sara.molina@synergy.cloud",
                website="synergy.cloud/partners",
                tagline="Integraciones con ISVs y marketplace global.",
                badge_text="ISV program",
                badge_color="#9333EA",
                cta_label="Agendar partnership call",
                cta_url="https://calendly.com/synergy/partners",
                banner_text="Nuevo acuerdo ISV - plazas limitadas",
                primary_color="#9333EA",
                accent_color="#2E1065",
                profile_photo_url="https://randomuser.me/api/portraits/women/11.jpg",
                logo_url="https://dummyimage.com/110x40/9333ea/ffffff.png&text=Nova",
                logo_secondary_url="https://dummyimage.com/110x40/1d4ed8/ffffff.png&text=Omni",
                logo_tertiary_url="https://dummyimage.com/110x40/0a84ff/ffffff.png&text=Fichaje",
                linkedin="https://www.linkedin.com/company/synergy-cloud",
                twitter="https://twitter.com/synergy_cloud",
            ),
        },
        {
            "name": "Talento remoto",
            "description": "Tarjeta compacta con badge de cultura y logos ESG.",
            "data": dict(
                defaults,
                theme="card-compact",
                full_name="Marcos Vidal",
                role="People Partner",
                company="Remoteia",
                phone="+34 933 765 123",
                mobile="+34 622 555 100",
                email="marcos@remoteia.com",
                website="remoteia.com/talento",
                tagline="Cultura distribuida y programas de mentoria.",
                badge_text="Cultura remote-first",
                badge_color="#16A34A",
                cta_label="Descargar handbook",
                cta_url="https://remoteia.com/handbook",
                banner_text="Nueva guia de beneficios 2025 disponible.",
                primary_color="#16A34A",
                accent_color="#052E16",
                profile_photo_url="https://randomuser.me/api/portraits/men/52.jpg",
                logo_url="https://dummyimage.com/110x40/16a34a/ffffff.png&text=Eco",
                logo_secondary_url="https://dummyimage.com/110x40/00b2a9/ffffff.png&text=Launchy",
                logo_tertiary_url="https://dummyimage.com/110x40/cccccc/111111.png&text=B-Corp",
                linkedin="https://www.linkedin.com/company/remoteia",
            ),
        },
        {
            "name": "Tecnologia industrial",
            "description": "Bloque oscuro con detalle de certificaciones.",
            "data": dict(
                defaults,
                theme="dark-strip",
                full_name="Javier Ortiz",
                role="CTO Industrial",
                company="Omnilink Industry",
                phone="+34 910 120 450",
                mobile="+34 690 880 123",
                email="javier.ortiz@omnilink.io",
                website="omnilink.io/industry",
                tagline="Integraciones OT + TI y seguridad operacional.",
                badge_text="ISO 27001",
                badge_color="#38BDF8",
                cta_label="Solicitar assessment OT",
                cta_url="https://omnilink.io/ot",
                banner_text="Nueva suite IIoT + Digital Twins 2025.",
                primary_color="#111827",
                accent_color="#93C5FD",
                profile_photo_url="https://randomuser.me/api/portraits/men/18.jpg",
                logo_url="https://dummyimage.com/110x40/111827/ffffff.png&text=Omni",
                logo_secondary_url="https://dummyimage.com/110x40/1d4ed8/ffffff.png&text=Edge",
                logo_tertiary_url="https://dummyimage.com/110x40/38bdf8/111111.png&text=ISO",
                linkedin="https://www.linkedin.com/company/omnilink",
            ),
        },
    ]
    features = [
        "Editor en vivo con vista previa fija.",
        "Temas inspirados en generadores de firmas profesionales.",
        "Agrega foto de perfil y hasta tres logotipos.",
        "Controla CTA, banner, badges y redes para todo el equipo.",
        "Exporta HTML limpio listo para Gmail u Outlook.",
    ]
    logo_slots = [
        {"key": "logo_url", "label": "Logo principal"},
        {"key": "logo_secondary_url", "label": "Logo secundario"},
        {"key": "logo_tertiary_url", "label": "Logo terciario"},
    ]
    return render_template(
        "firmas.html",
        defaults=defaults,
        color_presets=color_presets,
        social_networks=social_networks,
        signature_presets=signature_presets,
        features=features,
        profile_photos=profile_photos,
        logo_library=logo_library,
        logo_slots=logo_slots,
        themes=themes,
    )


@app.route("/cementerio", methods=["GET", "POST"])
@login_required
def cementerio_page():
    first_names = [
        "Lucía",
        "Martín",
        "Sofía",
        "Hugo",
        "Valeria",
        "Mateo",
        "Paula",
        "Daniel",
        "Alba",
        "Leo",
    ]
    last_names = [
        "García",
        "Martínez",
        "Rodríguez",
        "López",
        "Sánchez",
        "Pérez",
        "Gómez",
        "Fernández",
        "Díaz",
        "Moreno",
    ]
    domains = ["memorial.es", "recordatorios.com", "eterno.org", "descanso.net"]

    result = None
    dni = ""

    if request.method == "POST":
        dni = request.form.get("dni", "").strip().upper()
        name = random.choice(first_names)
        surname = random.choice(last_names)
        phone = "+34 {} {} {}".format(
            random.randint(600, 799),
            str(random.randint(0, 999)).zfill(3),
            str(random.randint(0, 999)).zfill(3),
        )
        email = f"{name}.{surname}{random.randint(10, 99)}@{random.choice(domains)}".lower()
        is_up_to_date = random.choice([True, False])
        result = {
            "dni": dni or "(sin DNI)",
            "name": name,
            "surname": surname,
            "phone": phone,
            "email": email,
            "is_up_to_date": is_up_to_date,
            "status_text": "Al corriente de pago" if is_up_to_date else "Con pagos pendientes",
            "status_class": "btn-green" if is_up_to_date else "btn-red",
        }

    return render_template("cementerio.html", result=result, last_dni=dni)


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

        # Approved vacation days: expected hours should be 0
        vac_days = set()
        vacs = db.execute(
            select(Absence)
            .where(
                Absence.user_id == current_user.id,
                Absence.status == EntryStatus.approved,
                func.lower(Absence.type) == 'vacaciones'
            )
        ).scalars().all()
        for a in vacs:
            a_start_local = ensure_aware_utc(a.date_from).astimezone(TZ).date()
            a_end_local = ensure_aware_utc(a.date_to).astimezone(TZ).date()
            cur = a_start_local
            while cur <= a_end_local:
                vac_days.add(cur)
                from datetime import timedelta
                cur = cur + timedelta(days=1)

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
                if d in vac_days:
                    expected = 0
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
