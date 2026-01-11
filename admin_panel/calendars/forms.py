"""Forms for managing work calendars."""

from datetime import date

from flask_wtf import FlaskForm
from wtforms import DateField, FloatField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class CalendarForm(FlaskForm):
    name = StringField(
        "Nombre del calendario",
        validators=[DataRequired(message="El nombre es obligatorio."), Length(max=140)],
    )
    year = IntegerField(
        "Año",
        validators=[DataRequired(message="El año es obligatorio."), NumberRange(min=2000, max=2100)],
    )
    description = TextAreaField(
        "Descripción",
        validators=[Optional(), Length(max=1000)],
    )
    notes = TextAreaField(
        "Notas",
        validators=[Optional(), Length(max=2000)],
    )
    weekday_hours = FloatField(
        "Horas lunes a viernes",
        validators=[DataRequired(message="Indica las horas de lunes a viernes."), NumberRange(min=0.0, max=24.0)],
        default=8.0,
    )
    saturday_hours = FloatField(
        "Horas sábado",
        validators=[DataRequired(message="Indica las horas del sábado."), NumberRange(min=0.0, max=24.0)],
        default=0.0,
    )
    sunday_hours = FloatField(
        "Horas domingo",
        validators=[DataRequired(message="Indica las horas del domingo."), NumberRange(min=0.0, max=24.0)],
        default=0.0,
    )


class HolidayForm(FlaskForm):
    HOLIDAY_TYPES = [
        ("local", "Festivo local"),
        ("autonomic", "Festivo autonómico"),
        ("national", "Festivo nacional"),
    ]

    date = DateField(
        "Fecha",
        validators=[DataRequired(message="La fecha es obligatoria.")],
        format="%Y-%m-%d",
        default=date.today,
    )
    holiday_type = SelectField(
        "Tipo de festivo",
        choices=HOLIDAY_TYPES,
        validators=[DataRequired(message="Selecciona un tipo de festivo.")],
    )
    name = StringField(
        "Nombre",
        validators=[Optional(), Length(max=140)],
    )
    note = TextAreaField(
        "Notas",
        validators=[Optional(), Length(max=1000)],
    )
