"""Forms for work schedule policy management."""

from datetime import time

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    FloatField,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError


class SchedulePolicyForm(FlaskForm):
    DAY_CHOICES = [
        ("mon", "Monday"),
        ("tue", "Tuesday"),
        ("wed", "Wednesday"),
        ("thu", "Thursday"),
        ("fri", "Friday"),
        ("sat", "Saturday"),
        ("sun", "Sunday"),
    ]

    MODE_CHOICES = [
        ("fixed", "Fixed"),
        ("flexible", "Flexible"),
        ("free", "Free"),
        ("night_shift", "Night shift"),
    ]

    name = StringField(
        "Name",
        validators=[DataRequired(message="Name is required."), Length(max=120)],
    )
    description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])
    mode = SelectField("Mode", choices=MODE_CHOICES, validators=[DataRequired()])
    expected_weekly_hours = FloatField(
        "Expected weekly hours",
        validators=[DataRequired(message="Weekly hours are required."), NumberRange(min=0.1, max=168.0)],
    )
    min_daily_hours = FloatField(
        "Minimum daily hours",
        validators=[Optional(), NumberRange(min=0.0, max=24.0)],
    )
    start_time = TimeField("Start time", validators=[Optional()])
    end_time = TimeField("End time", validators=[Optional()])
    allow_early_entry = BooleanField("Allow early entry")
    allow_late_exit = BooleanField("Allow late exit")
    break_minutes = IntegerField(
        "Break (minutes)",
        validators=[Optional(), NumberRange(min=0, max=600)],
        default=0,
    )
    working_days = SelectMultipleField(
        "Working days",
        choices=DAY_CHOICES,
        validators=[DataRequired(message="Select at least one working day.")],
    )
    no_time_enforcement = BooleanField("No time enforcement")
    allow_overtime = BooleanField("Allow overtime")
    overtime_after_minutes = IntegerField(
        "Overtime after (minutes)",
        validators=[Optional(), NumberRange(min=0, max=1440)],
    )
    is_night_shift = BooleanField("Night shift")
    entry_margin_minutes = IntegerField(
        "Entry margin (minutes)",
        validators=[Optional(), NumberRange(min=0, max=240)],
        default=0,
    )
    exit_margin_minutes = IntegerField(
        "Exit margin (minutes)",
        validators=[Optional(), NumberRange(min=0, max=240)],
        default=0,
    )

    def validate_end_time(self, field):
        if self.start_time.data and field.data and field.data <= self.start_time.data:
            raise ValidationError("End time must be later than start time.")

    def validate_overtime_after_minutes(self, field):
        if self.allow_overtime.data:
            if field.data is None:
                raise ValidationError("Specify minutes before overtime starts.")
        else:
            # allow clearing the field when overtime disabled
            if field.raw_data and field.raw_data[0].strip() == "":
                field.data = None
