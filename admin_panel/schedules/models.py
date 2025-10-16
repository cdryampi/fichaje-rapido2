"""SQLAlchemy model for work schedule policies."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)

from models import Base


class WorkSchedulePolicy(Base):
    __tablename__ = "work_schedule_policies"
    __table_args__ = (UniqueConstraint("name", name="uq_work_schedule_policies_name"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    mode = Column(String(32), nullable=False, default="fixed")
    expected_weekly_hours = Column(Float, nullable=False)
    min_daily_hours = Column(Float, nullable=True)
    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)
    allow_early_entry = Column(Boolean, default=False, nullable=False)
    allow_late_exit = Column(Boolean, default=False, nullable=False)
    break_minutes = Column(Integer, default=0, nullable=False)
    working_days = Column(String(64), default="mon,tue,wed,thu,fri", nullable=False)
    no_time_enforcement = Column(Boolean, default=False, nullable=False)
    allow_overtime = Column(Boolean, default=False, nullable=False)
    overtime_after_minutes = Column(Integer, nullable=True)
    is_night_shift = Column(Boolean, default=False, nullable=False)
    entry_margin_minutes = Column(Integer, default=0, nullable=False)
    exit_margin_minutes = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<WorkSchedulePolicy id={self.id} name={self.name!r}>"


__all__ = ["WorkSchedulePolicy"]
