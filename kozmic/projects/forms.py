# coding: utf-8
import wtforms
from flask.ext import wtf


class HookForm(wtf.Form):
    title = wtforms.TextField('Title', [wtforms.validators.Required()])
    build_script = wtforms.TextAreaField(
        'Build bash script', [wtforms.validators.Required()])
    docker_image = wtforms.TextField(
        'Docker image', [wtforms.validators.Required()],
        description='The name of a Docker container image that will be used '
                    'to run the build script. Use https://index.docker.io/ '
                    'to find an appropriate image or create and upload it '
                    'yourself.',
        default='ubuntu')
    submit = wtforms.SubmitField('Save')


class MemberForm(wtf.Form):
    gh_login = wtforms.TextField(
        'User\'s GitHub login', [wtforms.validators.Required()])
    submit = wtforms.SubmitField('Save')
