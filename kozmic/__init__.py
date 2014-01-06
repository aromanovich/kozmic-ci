# coding: utf-8
import os

import flask
import wtforms
import raven.contrib
from celery import Celery, Task
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.migrate import Migrate
from flask.ext.login import LoginManager
from flask.ext.principal import Principal
from flask.ext.assets import Environment, Bundle
from flask.ext.wtf.csrf import CsrfProtect
from flask.ext.mail import Mail


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
principal = Principal()
celery = Celery()
csrf = CsrfProtect()
mail = Mail()


def create_app(config=None):
    app = flask.Flask(__name__)
    config = config or os.environ.get('KOZMIC_CONFIG',
                                      'kozmic.config.DefaultConfig')
    app.config.from_object(config)
    configure_extensions(app)
    configure_blueprints(app)
    register_jinja2_globals_and_filters(app)
    return app


def configure_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    principal.init_app(app)
    init_celery_app(app, celery)
    csrf.init_app(app)
    mail.init_app(app)
    assets = Environment(app)
    css = Bundle('css/bootstrap.css', output='gen/style.css')
    js = Bundle('js/bootstrap.js', output='gen/common.js')
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
    from kozmic.builds import get_ansi_to_html_converter
    app.jinja_env.globals['bootstrap_is_hidden_field'] = \
        lambda field: isinstance(field, wtforms.HiddenField)
    ansi_converter = get_ansi_to_html_converter()
    app.jinja_env.filters['ansi2html'] = \
        lambda ansi: ansi_converter.convert(ansi, full=False)
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
