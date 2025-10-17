"""Forms for the employees admin module."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Length, Optional


class EmployeeForm(FlaskForm):
    name = StringField(
        "Nombre",
        validators=[DataRequired(message="El nombre es obligatorio."), Length(max=120)],
    )
    email = EmailField(
        "Email",
        validators=[
            DataRequired(message="El email es obligatorio."),
            Email(message="Introduce un email valido."),
            Length(max=255),
        ],
    )
    role_id = SelectField("Rol", coerce=int, validators=[DataRequired()])
    area_id = SelectField("Area", coerce=int, validators=[Optional()])
    group_id = SelectField("Grupo", coerce=int, validators=[Optional()])
    responsible_id = SelectField("Responsable directo", coerce=int, validators=[Optional()])
    is_active = BooleanField("Activo")


class EmployeeFilterForm(FlaskForm):
    role_id = SelectField("Rol", coerce=int, validators=[Optional()])
    area_id = SelectField("Area", coerce=int, validators=[Optional()])
    group_id = SelectField("Grupo", coerce=int, validators=[Optional()])
