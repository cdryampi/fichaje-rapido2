from datetime import datetime, timezone
from flask_login import UserMixin
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship
from werkzeug.security import generate_password_hash, check_password_hash
import enum
import os

DB_URL = os.getenv("DATABASE_URL", "sqlite:///fichaje.db")

class Base(DeclarativeBase): pass

engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Role(str, enum.Enum):
    employee = "employee"
    admin = "admin"

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
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    attendances = relationship("Attendance", back_populates="user")

    def set_password(self, raw): self.password_hash = generate_password_hash(raw)
    def check_password(self, raw): return check_password_hash(self.password_hash, raw)

class Attendance(Base):
    __tablename__ = "attendance"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(Enum(AttendanceAction), nullable=False)
    ts = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    ip = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


    user = relationship("User", back_populates="attendances")

def init_db_with_demo():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    # Usuario demo si no existe
    if not db.query(User).filter_by(email="demo@demo.local").first():
        u = User(email="demo@demo.local", name="Jaume", role=Role.admin)
        u.set_password("demo1234")  # cámbialo luego
        db.add(u)
        db.commit()
    db.close()
