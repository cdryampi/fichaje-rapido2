"""Shared SQLAlchemy models for areas and groups within the admin panel."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from models import Base


class AdminArea(Base):
    __tablename__ = "admin_areas"
    __table_args__ = (UniqueConstraint("name", name="uq_admin_areas_name"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    groups = relationship("AdminGroup", back_populates="area", cascade="all, delete-orphan")
    employees = relationship("Employee", back_populates="area")

    def __repr__(self) -> str:
        return f"<Area id={self.id} name={self.name!r}>"


class AdminGroup(Base):
    __tablename__ = "admin_groups"
    __table_args__ = (
        UniqueConstraint("name", "area_id", name="uq_admin_groups_name_area"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(String(255), nullable=True)
    area_id = Column(Integer, ForeignKey("admin_areas.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    area = relationship("AdminArea", back_populates="groups")
    employees = relationship("Employee", back_populates="group")

    def __repr__(self) -> str:
        return f"<Group id={self.id} name={self.name!r}>"


__all__ = ["AdminArea", "AdminGroup"]
