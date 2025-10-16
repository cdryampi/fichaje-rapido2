"""SQLAlchemy model for admin panel employees."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from models import Base


class Employee(Base):
    __tablename__ = "admin_employees"
    __table_args__ = (UniqueConstraint("email", name="uq_admin_employees_email"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("admin_roles.id", ondelete="RESTRICT"), nullable=False)
    area_id = Column(Integer, ForeignKey("admin_areas.id", ondelete="RESTRICT"), nullable=True)
    group_id = Column(Integer, ForeignKey("admin_groups.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    role = relationship("Role", back_populates="employees")
    area = relationship("AdminArea", back_populates="employees")
    group = relationship("AdminGroup", back_populates="employees")

    def __repr__(self) -> str:
        return f"<Employee id={self.id} email={self.email!r} active={self.is_active}>"


__all__ = ["Employee"]
