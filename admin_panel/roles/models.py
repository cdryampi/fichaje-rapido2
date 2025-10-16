"""SQLAlchemy models for the roles module."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from models import Base


class Role(Base):
    __tablename__ = "admin_roles"
    __table_args__ = (UniqueConstraint("name", name="uq_admin_roles_name"),)

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

    employees = relationship("Employee", back_populates="role")

    def __repr__(self) -> str:
        return f"<Role id={self.id} name={self.name!r}>"


__all__ = ["Role"]
