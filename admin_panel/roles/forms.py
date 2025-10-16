"""Forms for the roles admin module."""

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Length


class RoleForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[DataRequired(message="Name is required."), Length(max=120)],
    )
    description = TextAreaField("Description", validators=[Length(max=255)])
