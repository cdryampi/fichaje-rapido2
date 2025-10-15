from datetime import datetime, timezone
from flask_login import UserMixin
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Enum, Boolean, select
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
    """Inicializa la base de datos y crea datos de demostración si no existen."""
    print("Iniciando configuración de base de datos...")
    
    # 1. Crear tablas si no existen
    try:
        Base.metadata.create_all(engine)
        print("✓ Tablas verificadas/creadas")
    except Exception as e:
        print(f"⚠ Advertencia al crear tablas: {e}")
    
    # 2. Migrar columnas faltantes en SQLite (solo si es necesario)
    try:
        with engine.begin() as con:
            cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info('users')").fetchall()]
            migrated = []
            if 'is_active' not in cols:
                con.exec_driver_sql("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL")
                migrated.append('is_active')
            if 'group_id' not in cols:
                con.exec_driver_sql("ALTER TABLE users ADD COLUMN group_id INTEGER")
                migrated.append('group_id')
            if 'area_id' not in cols:
                con.exec_driver_sql("ALTER TABLE users ADD COLUMN area_id INTEGER")
                migrated.append('area_id')
            if migrated:
                print(f"✓ Columnas migradas: {', '.join(migrated)}")
    except Exception as e:
        print(f"⚠ Advertencia al migrar columnas: {e}")
    
    # 3. Crear datos de demostración si NO existen
    db = SessionLocal()
    try:
        # Verificar si ya hay datos (checking por usuario admin)
        existing_admin = db.execute(
            select(User).where(User.email == "admin@demo.local")
        ).scalar_one_or_none()
        
        if existing_admin:
            print("✓ Base de datos ya inicializada con datos de demostración")
            return
        
        # Verificar si hay áreas existentes
        existing_area = db.execute(
            select(Area).where(Area.name == "Area Demo")
        ).scalar_one_or_none()
        
        if existing_area:
            print("✓ Área demo ya existe, omitiendo creación de datos")
            return
        
        # Si llegamos aquí, no hay datos demo, los creamos
        print("Creando datos de demostración...")
        
        # Crear área
        area = Area(name="Area Demo")
        db.add(area)
        db.flush()
        
        # Crear grupos
        g1 = Group(name="Grupo A", area=area)
        g2 = Group(name="Grupo B", area=area)
        db.add_all([g1, g2])
        db.flush()
        
        # Crear usuarios
        users_to_create = [
            ("admin@demo.local", "Admin", Role.admin, g1),
            ("rrhh@demo.local", "RRHH", Role.rrhh, g1),
            ("cap@demo.local", "Cap Área", Role.cap_area, g1),
            ("resp@demo.local", "Responsable", Role.responsable, g1),
            ("emp1@demo.local", "Empleado 1", Role.employee, g1),
            ("emp2@demo.local", "Empleado 2", Role.employee, g1),
            ("emp3@demo.local", "Empleado 3", Role.employee, g2),
            ("demo@demo.local", "Jaume", Role.admin, g1),
        ]
        
        created_users = []
        for email, name, role, group in users_to_create:
            # Verificar que no exista
            existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if not existing:
                u = User(
                    email=email,
                    name=name,
                    role=role,
                    area=area,
                    group=group,
                    is_active=True
                )
                u.set_password("demo1234")
                db.add(u)
                created_users.append(u)
        
        # Crear invitado (sin grupo)
        guest_existing = db.execute(select(User).where(User.email == "guest@demo.local")).scalar_one_or_none()
        if not guest_existing:
            guest = User(
                email="guest@demo.local",
                name="Invitado",
                role=Role.invitado,
                is_active=True
            )
            guest.set_password("demo1234")
            db.add(guest)
            created_users.append(guest)
        
        db.flush()
        
        # Crear accesos para invitado
        if not guest_existing and len(created_users) >= 3:
            guest_user = next((u for u in created_users if u.email == "guest@demo.local"), None)
            emp1_user = next((u for u in created_users if u.email == "emp1@demo.local"), None)
            emp2_user = next((u for u in created_users if u.email == "emp2@demo.local"), None)
            
            if guest_user and emp1_user and emp2_user:
                db.add_all([
                    GuestAccess(guest_user_id=guest_user.id, target_user_id=emp1_user.id),
                    GuestAccess(guest_user_id=guest_user.id, target_user_id=emp2_user.id),
                ])
        
        db.commit()
        print(f"✓ Base de datos inicializada con {len(created_users)} usuarios de demostración")
        print("  Credenciales: cualquier usuario con password 'demo1234'")
        
    except Exception as e:
        db.rollback()
        print(f"✗ Error al crear datos de demostración: {e}")
        # No re-lanzamos el error, permitimos que la app continúe
    finally:
        db.close()
