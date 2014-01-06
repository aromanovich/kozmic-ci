# coding: utf-8
"""
kozmic.repos
~~~~~~~~~~~~

.. attribute:: bp

    :class:`flask.Blueprint` that gives users the abilities to:
    
    1. View list of GitHub repositories they have admin access to
    2. Create :class:`kozmic.models.Project` for any of them
"""
from flask import Blueprint
from flask.ext.login import login_required


bp = Blueprint('repos', __name__)


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
