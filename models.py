from datetime import datetime, timezone
from flask_login import UserMixin
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker
from werkzeug.security import generate_password_hash, check_password_hash
import enum
import os

DB_URL = os.getenv("DATABASE_URL", "sqlite:///fichaje.db")

class Base(DeclarativeBase):
    pass

engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Role(str, enum.Enum):
    """Clase del rol"""
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
    supervisor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    attendances = relationship("Attendance", back_populates="user")
    group = relationship("Group", back_populates="users")
    area = relationship("Area", back_populates="users", foreign_keys=[area_id])
    managed_areas = relationship(
        "Area",
        back_populates="manager",
        foreign_keys="Area.manager_id",
    )
    supervisor = relationship(
        "User",
        remote_side="User.id",
        back_populates="direct_reports",
        foreign_keys="User.supervisor_id",
    )
    direct_reports = relationship(
        "User",
        back_populates="supervisor",
        foreign_keys="User.supervisor_id",
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def can_validate_request_for(self, target: "User") -> bool:
        """Return True when the user can validate a request for the target user."""

        if not target or not self.is_active:
            return False

        if self.role in (Role.admin, Role.rrhh):
            return True

        if target.responsible_id and target.responsible_id == self.id:
            return True

        # Area heads can validate requests in their area regardless of direct responsibility.
        if self.role == Role.cap_area and self.area_id and target.area_id == self.area_id:
            return True

        if target.area and target.area.cap_id and target.area.cap_id == self.id:
            return True

        return False


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
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    users = relationship("User", back_populates="area", foreign_keys="User.area_id")
    groups = relationship("Group", back_populates="area")
    manager = relationship(
        "User",
        back_populates="managed_areas",
        foreign_keys=[manager_id],
    )


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
    subtype = Column(String(50))
    status = Column(Enum(EntryStatus), default=EntryStatus.pending, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user = relationship("User")

    def can_be_validated_by(self, user: User) -> bool:
        """Return True when the given user can validate this absence."""

        if not user:
            return False

        requester = self.user
        if requester is None:
            return False

        return user.can_validate_request_for(requester)


class GuestAccess(Base):
    __tablename__ = "guest_access"
    id = Column(Integer, primary_key=True)
    guest_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

# Import admin panel models so they are registered on shared metadata.
for module in (
    "admin_panel.roles.models",
    "admin_panel.areas.models",
    "admin_panel.employees.models",
    "admin_panel.schedules.models",
):
    try:
        __import__(module)
    except ModuleNotFoundError:
        pass


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
            if 'supervisor_id' not in cols:
                con.exec_driver_sql("ALTER TABLE users ADD COLUMN supervisor_id INTEGER")
                migrated.append('supervisor_id')
            # Ensure 'subtype' column exists on 'absences'
            try:
                abs_cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info('absences')").fetchall()]
                if 'subtype' not in abs_cols:
                    con.exec_driver_sql("ALTER TABLE absences ADD COLUMN subtype VARCHAR(50)")
                    print("✔ Columna 'subtype' agregada a 'absences'")
            except Exception as e:
                print(f"⚠ Advertencia al migrar 'absences.subtype': {e}")
            # Ensure manager column exists on areas
            area_cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info('areas')").fetchall()]
            if 'manager_id' not in area_cols:
                con.exec_driver_sql("ALTER TABLE areas ADD COLUMN manager_id INTEGER")
                migrated.append('areas.manager_id')
            if migrated:
                print(f"✓ Columnas migradas: {', '.join(migrated)}")
    except Exception as e:
        print(f"⚠ Advertencia al migrar columnas: {e}")
    
    # 3. Crear datos de demostración si NO existen
    db = SessionLocal()
    try:
        # IMPORTANTE: Verificar DENTRO de una transacción para evitar race conditions
        existing_admin = db.execute(
            select(User).where(User.email == "admin@demo.local")
        ).scalar_one_or_none()
        
        if existing_admin:
            print("✓ Base de datos ya inicializada")
            db.close()
            return
        
        # Intentar obtener o crear el área (manejo de race condition)
        existing_area = db.execute(
            select(Area).where(Area.name == "Area Demo")
        ).scalar_one_or_none()
        
        if existing_area:
            # Otro worker ya creó el área, verificamos si completó todo
            print("✓ Área demo ya existe, verificando usuarios...")
            existing_admin_check = db.execute(
                select(User).where(User.email == "admin@demo.local")
            ).scalar_one_or_none()
            if existing_admin_check:
                print("✓ Datos de demostración ya completos")
                db.close()
                return
            # Si el área existe pero no el admin, puede ser race condition, salimos
            print("⚠ Otro worker está inicializando, saliendo...")
            db.close()
            return
        
        # Si llegamos aquí, somos el primer worker, creamos todo
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

        # Asignar jerarquías de ejemplo
        users_by_email = {u.email: u for u in created_users}
        area.manager_id = users_by_email.get("cap@demo.local").id if users_by_email.get("cap@demo.local") else None
        responsable = users_by_email.get("resp@demo.local")
        cap_area_user = users_by_email.get("cap@demo.local")
        if responsable and cap_area_user:
            responsable.supervisor_id = cap_area_user.id
        for email in ("emp1@demo.local", "emp2@demo.local", "emp3@demo.local"):
            employee = users_by_email.get(email)
            if employee and responsable:
                employee.supervisor_id = responsable.id

        # Crear accesos para invitado
        guest_user = created_users[-1]
        emp1_user = created_users[4]  # emp1@demo.local
        emp2_user = created_users[5]  # emp2@demo.local
        
        db.add_all([
            GuestAccess(guest_user_id=guest_user.id, target_user_id=emp1_user.id),
            GuestAccess(guest_user_id=guest_user.id, target_user_id=emp2_user.id),
        ])
        
        db.commit()
        print(f"✓ Base de datos inicializada con {len(created_users)} usuarios de demostración")
        print("  Credenciales: cualquier usuario con password 'demo1234'")
        
    except Exception as e:
        db.rollback()
        # Si falla por UNIQUE constraint, es porque otro worker ganó la carrera
        if "UNIQUE constraint failed" in str(e):
            print("⚠ Otro worker ya inicializó la BD (race condition detectada)")
        else:
            print(f"✗ Error al crear datos de demostración: {e}")
    finally:
        db.close()
