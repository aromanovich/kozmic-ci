# coding: utf-8
"""
kozmic
~~~~~~

.. autofunction:: create_app
"""
import os
import logging

import docker as _docker
import flask
import raven.contrib
from celery import Celery, Task
from werkzeug.local import LocalProxy
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.migrate import Migrate
from flask.ext.login import LoginManager
from flask.ext.principal import Principal
from flask.ext.assets import Environment, Bundle
from flask.ext.wtf.csrf import CsrfProtect
from flask.ext.mail import Mail
from flask.ext.moment import Moment


VERSION = '0.0.1'


def get_version():
    return VERSION


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
principal = Principal()
celery = Celery()
csrf = CsrfProtect()
mail = Mail()
moment = Moment()
docker = LocalProxy(lambda: _docker.Client(
    base_url=flask.current_app.config['DOCKER_URL'],
    version=flask.current_app.config['DOCKER_API_VERSION']))


def create_app(config=None):
    """Returns a fully configured :class:`Flask` application.

    :param config: a config object or it's name. Will be passed directly
                   to :meth:`flask.config.Config.from_object`.
                   If not specified, the value of ``KOZMIC_CONFIG``
                   environment variable will be used.
                   If ``KOZMIC_CONFIG`` is not specified,
                   ``'kozmic.config.DefaultConfig'`` will be used.
    """
    app = flask.Flask(__name__)
    config = config or os.environ.get('KOZMIC_CONFIG',
                                      'kozmic.config.DefaultConfig')
    app.config.from_object(config)
    configure_logging(app)
    configure_extensions(app)
    configure_blueprints(app)
    register_jinja2_globals_and_filters(app)
    return app


def configure_logging(app):
    app.logger.setLevel(logging.INFO)
    if not (app.debug or app.testing):
        handler = logging.StreamHandler()
        app.logger.addHandler(handler)


def configure_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    principal.init_app(app)
    init_celery_app(app, celery)
    csrf.init_app(app)
    mail.init_app(app)
    moment.init_app(app)
    assets = Environment(app)
    css = Bundle(
        'css/libs/bootstrap.css',
        'css/libs/codemirror.css',
        'css/styles.css',
        output='gen/style.css')
    js = Bundle(
        'js/libs/jquery.js',
        'js/libs/codemirror.js',
        'js/libs/bootstrap.js',
        'js/tailer.js',
        'js/hook-form.js',
        output='gen/common.js')
    assets.register('css', css)
    assets.register('js', js)


def configure_blueprints(app):
    from . import auth
    app.register_blueprint(auth.bp)

    from . import repos
    app.register_blueprint(repos.bp, url_prefix='/repositories')

    from . import accounts
    app.register_blueprint(accounts.bp, url_prefix='/account')

    from . import projects
    app.register_blueprint(projects.bp, url_prefix='/projects')

    from . import builds
    app.register_blueprint(builds.bp)

    @app.route('/')
    def index():
        return flask.redirect(flask.url_for('projects.index'))


def register_jinja2_globals_and_filters(app):
    import wtforms
    from kozmic.builds import get_ansi_to_html_converter
    app.jinja_env.globals['get_version'] = get_version
    app.jinja_env.globals['bootstrap_is_hidden_field'] = \
        lambda field: isinstance(field, wtforms.HiddenField)
    ansi_converter = get_ansi_to_html_converter()
    app.jinja_env.filters['ansi2html'] = \
        lambda ansi: ansi_converter.convert(ansi, full=False)
    app.jinja_env.filters['precise_moment'] = \
        lambda dt: moment.create(dt).format('H:mm:ss, MMM DD')
    app.jinja_env.globals['render_ansi2html_style_tag'] = \
        ansi_converter.produce_headers


def init_celery_app(app, celery):
    celery.config_from_object(app.config)

    class ContextTask(Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with create_app().app_context():
                return super(ContextTask, self).__call__(*args, **kwargs)

    celery.Task = ContextTask

    sentry_dsn = app.config['KOZMIC_SENTRY_DSN']
    if sentry_dsn:
        client = raven.Client(sentry_dsn)
        raven.contrib.celery.register_signal(client)
