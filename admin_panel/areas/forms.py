"""Forms for areas and groups management."""

from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class AreaForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[DataRequired(message="Name is required."), Length(max=120)],
    )
    description = TextAreaField("Description", validators=[Optional(), Length(max=255)])


class GroupForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[DataRequired(message="Name is required."), Length(max=120)],
    )
    description = TextAreaField("Description", validators=[Optional(), Length(max=255)])
    area_id = SelectField(
        "Area",
        coerce=int,
        validators=[DataRequired(message="Area selection is required.")],
    )
