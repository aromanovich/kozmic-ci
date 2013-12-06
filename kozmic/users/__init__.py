# coding: utf-8
import certifi
from flask import Blueprint, redirect, url_for
from flask.ext.oauth import OAuth
from flask.ext.login import current_user
from flask.ext.principal import AnonymousIdentity

from kozmic import login_manager, principal
from kozmic.models import User


bp = Blueprint('users', __name__)


@bp.record
def configure(state):
    app = state.app

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    @login_manager.unauthorized_handler
    def unauthorized():
        return redirect(url_for('users.login'))

    @app.errorhandler(401)
    def unauthorized_error_handler(error):
        return redirect(url_for('users.login'))

    @principal.identity_loader
    def load_identity():
        return (current_user.is_authenticated() and
                current_user.get_identity() or AnonymousIdentity())

    init_github_oauth_app(
        app.config['KOZMIC_GITHUB_CLIENT_ID'],
        app.config['KOZMIC_GITHUB_CLIENT_SECRET'])
    register_views()


def init_github_oauth_app(github_client_id, github_client_secret):
    github_oauth_app = OAuth().remote_app(
        'github',
        base_url='https://github.com',
        request_token_url=None,
        access_token_url='https://github.com/login/oauth/access_token',
        authorize_url='https://github.com/login/oauth/authorize',
        consumer_key=github_client_id,
        consumer_secret=github_client_secret,
        request_token_params={'scope': 'repo'})
    github_oauth_app.tokengetter(lambda token=None: None)

    # Hack to avoid the following error:
    # SSLHandshakeError: [Errno 1] _ssl.c:504: error:14090086:SSL
    # routines:SSL3_GET_SERVER_CERTIFICATE:certificate verify failed
    # See http://stackoverflow.com/a/10393381 for details
    github_oauth_app._client.ca_certs = certifi.where()

    # Store OAuth app in the blueprint object to make it available
    # to the views
    bp.github_oauth_app = github_oauth_app


def register_views():
    from . import views
