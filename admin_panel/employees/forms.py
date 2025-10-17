"""Forms for the employees admin module."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Length, Optional, ValidationError


def _validate_email(form, field):
    """Lightweight email validator that does not require external deps."""

    value = (field.data or "").strip()

    if " " in value:
        raise ValidationError("Introduce un email valido.")

    if value.count("@") != 1:
        raise ValidationError("Introduce un email valido.")

    local_part, domain_part = value.split("@", 1)
    if not local_part or not domain_part:
        raise ValidationError("Introduce un email valido.")

    if domain_part.startswith(".") or domain_part.endswith("."):
        raise ValidationError("Introduce un email valido.")

    if "." not in domain_part:
        raise ValidationError("Introduce un email valido.")

    if ".." in domain_part:
        raise ValidationError("Introduce un email valido.")


class EmployeeForm(FlaskForm):
    name = StringField(
        "Nombre",
        validators=[DataRequired(message="El nombre es obligatorio."), Length(max=120)],
    )
    email = EmailField(
        "Email",
        validators=[
            DataRequired(message="El email es obligatorio."),
            _validate_email,
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
