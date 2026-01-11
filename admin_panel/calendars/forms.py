"""Forms for managing work calendars."""

from datetime import date

from flask_wtf import FlaskForm
from wtforms import DateField, FloatField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.fields import TimeField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class CalendarForm(FlaskForm):
    name = StringField(
        "Nombre del calendario",
        validators=[DataRequired(message="El nombre es obligatorio."), Length(max=140)],
    )
    year = SelectField(
        "Ano",
        coerce=int,
        validators=[DataRequired(message="El ano es obligatorio.")],
    )
    description = TextAreaField(
        "Descripcion",
        validators=[Optional(), Length(max=1000)],
    )
    notes = TextAreaField(
        "Notas",
        validators=[Optional(), Length(max=2000)],
    )
    weekly_hours = FloatField(
        "Horas semanales",
        validators=[DataRequired(message="Indica las horas semanales."), NumberRange(min=0.0, max=168.0)],
        default=40.0,
    )
    weekday_hours = FloatField(
        "Horas lunes a viernes",
        validators=[DataRequired(message="Indica las horas de lunes a viernes."), NumberRange(min=0.0, max=24.0)],
        default=8.0,
    )
    saturday_hours = FloatField(
        "Horas sabado",
        validators=[DataRequired(message="Indica las horas del sabado."), NumberRange(min=0.0, max=24.0)],
        default=0.0,
    )
    sunday_hours = FloatField(
        "Horas domingo",
        validators=[DataRequired(message="Indica las horas del domingo."), NumberRange(min=0.0, max=24.0)],
        default=0.0,
    )
    break_minutes = IntegerField(
        "Minutos de descanso",
        validators=[Optional(), NumberRange(min=0, max=600)],
        default=0,
    )
    clock_in_start_time = TimeField(
        "Hora desde la que se puede fichar",
        validators=[Optional()],
        format="%H:%M",
    )
    clock_in_end_time = TimeField(
        "Hora maxima de fichaje",
        validators=[Optional()],
        format="%H:%M",
    )
    max_daily_hours = FloatField(
        "Maximo de horas por dia",
        validators=[Optional(), NumberRange(min=0.0, max=24.0)],
        default=8.0,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_year = date.today().year
        years = list(range(current_year, current_year + 11))
        if self.year.data and self.year.data not in years:
            years.insert(0, self.year.data)
        self.year.choices = [(year, str(year)) for year in years]
        if not self.year.data:
            self.year.data = current_year


class HolidayForm(FlaskForm):
    HOLIDAY_TYPES = [
        ("local", "Festivo local"),
        ("autonomic", "Festivo autonomico"),
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
