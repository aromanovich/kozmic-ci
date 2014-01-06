# coding: utf-8
"""
kozmic.accounts
~~~~~~~~~~~~~~~

.. attribute:: bp

    :class:`flask.Blueprint` that gives users a means to manage their
    account settings.
"""
from flask import Blueprint
from flask.ext.login import login_required


bp = Blueprint('accounts', __name__)


@bp.before_request
@login_required
def before_request():
    # Do nothing, just require login
    pass


@bp.record
def configure(state):
    register_views()


def register_views():
    from . import views
