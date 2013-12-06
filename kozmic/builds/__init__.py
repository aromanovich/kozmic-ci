from flask import Blueprint


bp = Blueprint('builds', __name__)


@bp.record
def configure(state):
    register_views()


def register_views():
    from . import views
