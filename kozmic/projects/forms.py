# coding: utf-8
import wtforms
from flask.ext import wtf

from kozmic.models import TrackedFile


required = wtforms.validators.Required()
optional = wtforms.validators.Optional()

shebang_reminder = ('It will be run as an executable, so do not forget to put '
                    'a shebang directive at the beginning.')


class TrackedFilesField(wtforms.TextAreaField):
    def process_data(self, value):
        if value:
            value = '\n'.join(tracked_file.path for tracked_file in value)
        return super(TrackedFilesField, self).process_data(value)

    def process_formdata(self, valuelist):
        assert len(valuelist) == 1
        value = valuelist.pop()
        if value:
            value = [TrackedFile(path=path)
                     for path in set(filter(bool, value.splitlines()))]
        valuelist.append(value)
        return super(TrackedFilesField, self).process_formdata(valuelist)

    def populate_obj(self, obj, name):
        getattr(obj, name).delete()
        setattr(obj, name, self.data)


class HookForm(wtf.Form):
    title = wtforms.TextField('Title *', [required])
    install_script = wtforms.TextAreaField(
        'Install script', [optional], description=shebang_reminder)
    tracked_files = TrackedFilesField(
        'Tracked files', [optional],
        description='Results of the install script are cached. The cache is invalidated '
                    'whenever the base Docker image, the install script or any of '
                    'the tracked files change.\nRemember to list here all the '
                    'files used by install script (such as pip\'s requirements.txt, '
                    'Gemfile, etc).')
    build_script = wtforms.TextAreaField(
        'Build script *', [required], description=shebang_reminder)
    docker_image = wtforms.TextField(
        'Docker image *', [required],
        description='The name of a Docker container image that will be used '
                    'to run the scripts. Use https://index.docker.io/ '
                    'to find an appropriate image or create and upload it '
                    'yourself.',
        default='kozmic/ubuntu-base:12.04')
    submit = wtforms.SubmitField('Save')


class MemberForm(wtf.Form):
    gh_login = wtforms.TextField('User\'s GitHub login', [required])
    is_manager = wtforms.BooleanField(
        'Is manager?', [wtforms.validators.NumberRange(0, 1)])
    submit = wtforms.SubmitField('Save')
