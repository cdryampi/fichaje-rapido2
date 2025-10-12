from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import SessionLocal, init_db_with_demo, User, Attendance, AttendanceAction, Role
from sqlalchemy import select, desc
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
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

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

        return render_template("index.html", dentro=dentro, historial=historial)
    finally:
        db.close()

@app.route("/clock", methods=["POST"])
@login_required
def clock():
    db = SessionLocal()
    try:
        # Determinar si toca IN o OUT
        last = db.execute(
            select(Attendance)
            .where(Attendance.user_id == current_user.id)
            .order_by(desc(Attendance.ts))
        ).scalars().first()
        dentro = (last and last.action == AttendanceAction._in)
        action = AttendanceAction._out if dentro else AttendanceAction._in

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

@app.route("/admin/users", methods=["GET"])
@login_required
@admin_required
def admin_users():
    db = SessionLocal()
    try:
        users = db.execute(select(User).order_by(User.id)).scalars().all()
        return render_template("admin/users.html", users=users)
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

    role = Role.admin if role_str == "admin" else Role.employee

    db = SessionLocal()
    try:
        existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing:
            flash("Ese email ya existe.", "error")
            return redirect(url_for("admin_users"))

        u = User(email=email, name=name, role=role)
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

        u.role = Role.admin if role_str == "admin" else Role.employee
        db.commit()
        flash(f"Rol de {u.email} actualizado a {u.role.value}.", "ok")
        return redirect(url_for("admin_users"))
    finally:
        db.close()


if __name__ == "__main__":
    app.run(debug=True)
