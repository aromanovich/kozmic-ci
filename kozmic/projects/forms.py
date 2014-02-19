# coding: utf-8
import os.path

import wtforms
from flask.ext import wtf

from kozmic.models import TrackedFile


required = wtforms.validators.Required()
optional = wtforms.validators.Optional()


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
        'Install script', [optional])
    tracked_files = TrackedFilesField(
        'Tracked files', [optional])
    build_script = UnixEndingsTextAreaField(
        'Build script *', [required],
        default='#!/bin/bash\n\necho "It works!"')
    docker_image = wtforms.TextField(
        'Docker image *', [required],
        default='kozmic/ubuntu-base:12.04')
    submit = wtforms.SubmitField('Save')


class MemberForm(wtf.Form):
    gh_login = wtforms.TextField('User\'s GitHub login', [required])
    is_manager = wtforms.BooleanField(
        'Is manager?', [wtforms.validators.NumberRange(0, 1)])
    submit = wtforms.SubmitField('Save')
