from flask import Blueprint
from flask.ext.login import login_required


bp = Blueprint('projects', __name__)


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