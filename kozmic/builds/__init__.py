# coding: utf-8
"""
kozmic.builds
~~~~~~~~~~~~~

.. attribute:: bp

    :class:`flask.Blueprint` that implements webhooks to be triggered by
    GitHub and serves status badges.

    .. note::
        Does not require authentication.
"""
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
