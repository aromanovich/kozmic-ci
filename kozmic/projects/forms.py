# coding: utf-8
import os.path

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
            # Normalize and keep only unique paths to provide better UI
            paths = set(os.path.relpath(path, start='.')
                        for path in value.splitlines() if path)
            value = [TrackedFile(path=path) for path in paths]
        valuelist.append(value)
        return super(TrackedFilesField, self).process_formdata(valuelist)

    def populate_obj(self, obj, name):
        getattr(obj, name).delete()
        setattr(obj, name, self.data)


class UnixEndingsTextAreaField(wtforms.TextAreaField):
    def process_formdata(self, valuelist):
        valuelist = ['\n'.join(value.splitlines()) for value in valuelist]
        return super(UnixEndingsTextAreaField, self).process_formdata(valuelist)


class HookForm(wtf.Form):
    title = wtforms.TextField('Title *', [required])
    install_script = UnixEndingsTextAreaField(
        'Install script', [optional],
        description='Install build dependencies here.<br><br>' + shebang_reminder)
    tracked_files = TrackedFilesField(
        'Tracked files', [optional],
        description='Enter one path per line, the order doesn\'t matter.'
                    'Tracked files may include both regular files and directories.<br><br>'
                    'Results of the install script are cached. The cache is invalidated '
                    'whenever the base Docker image, the install script or any of '
                    'the tracked files change.\nRemember to list here all the '
                    'files used by install script (such as pip\'s requirements.txt, '
                    'Gemfile, etc).')
    build_script = UnixEndingsTextAreaField(
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
