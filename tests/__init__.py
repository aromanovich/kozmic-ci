import os
import collections

import sqlalchemy
from alembic.config import Config
from alembic.command import upgrade as alembic_upgrade
from flask.ext.webtest import TestApp, get_scopefunc

from kozmic import create_app, db
from . import factories


class SQLAlchemyMixin(object):
    @property
    def db(self):
        return self.app.extensions['sqlalchemy'].db

    def create_database(self, use_migrations=True):
        self.db.session = self.db.create_scoped_session({
            'scopefunc': get_scopefunc(),
        })

        self.db.session.execute('SET storage_engine=InnoDB;')
        if use_migrations:
            try:
                self.db.session.execute('TRUNCATE alembic_version;')
            except sqlalchemy.exc.ProgrammingError:
                self.db.session.rollback()
            config = Config('migrations/alembic.ini', 'alembic')
            alembic_upgrade(config, 'head')
        else:
            self.db.create_all()

    def drop_database(self):
        self.db.drop_all()


class SQLAlchemyFixtureMixin(object):
    def get_fixtures(self):
        return getattr(self, 'FIXTURES', [])

    def load_fixtures(self):
        for fixture in self.get_fixtures():
            if callable(fixture):
                models_to_merge = fixture()
                if isinstance(models_to_merge, db.Model):
                    models_to_merge = [models_to_merge]
            elif isinstance(fixture, collections.Iterable):
                models_to_merge = fixture
            elif isinstance(fixture, self.db.Model):
                models_to_merge = [fixture]
            else:
                raise Exception(
                    'Don\'t know how to handle fixture of {} type: {}.'.format(
                        type(fixture), fixture))
            for model in models_to_merge:
                self.db.session.merge(model)
                self.db.session.commit()
        self.db.session.remove()


class WebTestMixin(object):
    def create_app(self):
        config = os.environ.get('KOZMIC_CONFIG', 'kozmic.config.TestingConfig')
        return create_app(config)

    def setup_app_and_ctx(self):
        self.app = self.create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.w = TestApp(self.app)

    def teardown_app_and_ctx(self):
        self.ctx.pop()

    def login(self, user_id):
        with self.w.session_transaction() as sess:
            sess['user_id'] = user_id


class TestCase(WebTestMixin, SQLAlchemyMixin, SQLAlchemyFixtureMixin):
    def setup_method(self, method):
        self.setup_app_and_ctx()
        self.drop_database()
        self.create_database()
        factories.setup(self.db.session)
        self.load_fixtures()

    def teardown_method(self, method):
        self.db.session.rollback()
        factories.reset()
        self.teardown_app_and_ctx()
