import ansi2html
from flask import Blueprint


bp = Blueprint('builds', __name__)


@bp.record
def configure(state):
    register_views()


def register_views():
    from . import views


def get_ansi_to_html_converter():
    return ansi2html.Ansi2HTMLConverter()
