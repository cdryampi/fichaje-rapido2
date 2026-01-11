"""SQLAlchemy models for work calendars."""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from models import Base


class WorkCalendar(Base):
    __tablename__ = "work_calendars"
    __table_args__ = (
        UniqueConstraint("name", "year", name="uq_work_calendars_name_year"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(140), nullable=False)
    year = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    weekday_hours = Column(Float, nullable=False, default=8.0)
    saturday_hours = Column(Float, nullable=False, default=0.0)
    sunday_hours = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    holidays = relationship(
        "WorkCalendarHoliday",
        back_populates="calendar",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<WorkCalendar id={self.id} name={self.name!r} year={self.year}>"


class WorkCalendarHoliday(Base):
    __tablename__ = "work_calendar_holidays"
    __table_args__ = (
        UniqueConstraint("calendar_id", "date", name="uq_calendar_holiday_date"),
    )

    id = Column(Integer, primary_key=True)
    calendar_id = Column(Integer, ForeignKey("work_calendars.id"), nullable=False)
    date = Column(Date, nullable=False)
    name = Column(String(140), nullable=True)
    holiday_type = Column(String(32), nullable=False, default="local")
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    calendar = relationship("WorkCalendar", back_populates="holidays")

    def __repr__(self) -> str:
        return f"<WorkCalendarHoliday id={self.id} date={self.date} type={self.holiday_type}>"


__all__ = ["WorkCalendar", "WorkCalendarHoliday"]
