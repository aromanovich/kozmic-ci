# coding: utf-8
import wtforms.fields.html5
from flask.ext import wtf


class SettingsForm(wtf.Form):
    email = wtforms.fields.html5.EmailField(
        'E-mail', [wtforms.validators.Optional(), wtforms.validators.Email()],
        description='E-mail address that will be used for notifications.')
    submit = wtforms.SubmitField('Save')
