from datetime import datetime, timezone
from flask_login import UserMixin
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Enum, Boolean
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship
from werkzeug.security import generate_password_hash, check_password_hash
import enum
import os

DB_URL = os.getenv("DATABASE_URL", "sqlite:///fichaje.db")

class Base(DeclarativeBase):
    pass

engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Role(str, enum.Enum):
    employee = "employee"        # EMPLEADO
    responsable = "responsable"  # RESPONSABLE (grupo)
    cap_area = "cap_area"        # CAP_AREA (área)
    rrhh = "rrhh"                # RRHH (empresa)
    admin = "admin"              # ADMIN (total)
    invitado = "invitado"        # INVITADO (solo lectura)


class AttendanceAction(str, enum.Enum):
    _in = "in"
    _out = "out"


class User(Base, UserMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(Role), default=Role.employee, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    area_id = Column(Integer, ForeignKey("areas.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    attendances = relationship("Attendance", back_populates="user")
    group = relationship("Group", back_populates="users")
    area = relationship("Area", back_populates="users")

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class Attendance(Base):
    __tablename__ = "attendance"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(Enum(AttendanceAction), nullable=False)
    ts = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ip = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="attendances")


class Pause(Base):
    __tablename__ = "pauses"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    start_ts = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    end_ts = Column(DateTime(timezone=True))  # null mientras está activa
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Area(Base):
    __tablename__ = "areas"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    users = relationship("User", back_populates="area")
    groups = relationship("Group", back_populates="area")


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    area_id = Column(Integer, ForeignKey("areas.id"), nullable=False)
    area = relationship("Area", back_populates="groups")
    users = relationship("User", back_populates="group")


class TimeEntryType(str, enum.Enum):
    in_ = "in"
    out = "out"
    pause = "pause"


class EntryStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TimeEntry(Base):
    __tablename__ = "time_entries"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ts_in = Column(DateTime(timezone=True))
    ts_out = Column(DateTime(timezone=True))
    type = Column(Enum(TimeEntryType), nullable=False)
    status = Column(Enum(EntryStatus), default=EntryStatus.pending, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user = relationship("User")


class Absence(Base):
    __tablename__ = "absences"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date_from = Column(DateTime(timezone=True), nullable=False)
    date_to = Column(DateTime(timezone=True), nullable=False)
    type = Column(String(50), nullable=False)
    status = Column(Enum(EntryStatus), default=EntryStatus.pending, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user = relationship("User")


class GuestAccess(Base):
    __tablename__ = "guest_access"
    id = Column(Integer, primary_key=True)
    guest_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)


def init_db_with_demo():
    # Crear tablas nuevas y luego asegurar columnas nuevas en SQLite existente
    Base.metadata.create_all(engine)
    # Migra columnas faltantes en SQLite (users.is_active, users.group_id, users.area_id)
    try:
        with engine.begin() as con:
            cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info('users')").fetchall()]
            if 'is_active' not in cols:
                con.exec_driver_sql("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL")
            if 'group_id' not in cols:
                con.exec_driver_sql("ALTER TABLE users ADD COLUMN group_id INTEGER")
            if 'area_id' not in cols:
                con.exec_driver_sql("ALTER TABLE users ADD COLUMN area_id INTEGER")
    except Exception:
        # Si falla (no SQLite o ya migrado), seguimos
        pass
    db = SessionLocal()
    # Seed más completo con RBAC si no hay áreas
    if not db.query(Area).first():
        area = Area(name="Area Demo")
        db.add(area)
        db.flush()
        g1 = Group(name="Grupo A", area=area)
        g2 = Group(name="Grupo B", area=area)
        db.add_all([g1, g2])
        db.flush()

        admin = User(email="admin@demo.local", name="Admin", role=Role.admin, area=area, group=g1)
        admin.set_password("demo1234")
        rrhh = User(email="rrhh@demo.local", name="RRHH", role=Role.rrhh, area=area, group=g1)
        rrhh.set_password("demo1234")
        cap = User(email="cap@demo.local", name="Cap Área", role=Role.cap_area, area=area, group=g1)
        cap.set_password("demo1234")
        resp = User(email="resp@demo.local", name="Responsable", role=Role.responsable, area=area, group=g1)
        resp.set_password("demo1234")
        emp1 = User(email="emp1@demo.local", name="Empleado 1", role=Role.employee, area=area, group=g1)
        emp1.set_password("demo1234")
        emp2 = User(email="emp2@demo.local", name="Empleado 2", role=Role.employee, area=area, group=g1)
        emp2.set_password("demo1234")
        emp3 = User(email="emp3@demo.local", name="Empleado 3", role=Role.employee, area=area, group=g2)
        emp3.set_password("demo1234")
        guest = User(email="guest@demo.local", name="Invitado", role=Role.invitado)
        guest.set_password("demo1234")
        # Evitar duplicado si ya existía el usuario legacy demo
        legacy_demo = db.query(User).filter_by(email="demo@demo.local").first()
        if not legacy_demo:
            legacy_demo = User(email="demo@demo.local", name="Jaume", role=Role.admin, area=area, group=g1)
            legacy_demo.set_password("demo1234")
            db.add(legacy_demo)
        db.add_all([admin, rrhh, cap, resp, emp1, emp2, emp3, guest])
        db.flush()

        db.add_all([
            GuestAccess(guest_user_id=guest.id, target_user_id=emp1.id),
            GuestAccess(guest_user_id=guest.id, target_user_id=emp2.id),
        ])
        db.commit()
    db.close()
