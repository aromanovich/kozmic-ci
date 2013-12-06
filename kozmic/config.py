# coding: utf-8
"""
kozmic.config
~~~~~~~~~~~~~

Kozmic default configurations
"""
import os


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


class DefaultConfig(object):
    DEBUG = False
    TESTING = False

    KOZMIC_SENTRY_DSN = None
    KOZMIC_REDIS_HOST = 'localhost'
    KOZMIC_REDIS_PORT = 6379
    KOZMIC_REDIS_DATABASE = 0
    BROKER_URL = 'redis://{host}:{port}/{db}'.format(
        host=KOZMIC_REDIS_HOST,
        port=KOZMIC_REDIS_PORT,
        db=KOZMIC_REDIS_DATABASE)
    CELERY_IMPORTS = ('kozmic.builds',)
    CELERY_ALWAYS_EAGER = False
    CELERY_EAGER_PROPAGATES_EXCEPTIONS = True
    CELERY_IGNORE_RESULT = True
    CELERY_DEFAULT_QUEUE = 'kozmic'
    SERVER_NAME = None
    TAILER_URL_TEMPLATE = None


class DevelopmentConfig(DefaultConfig):
    DEBUG = True
    SECRET_KEY = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'
    KOZMIC_GITHUB_CLIENT_ID = '2ee444daf6b2437b8b48'
    KOZMIC_GITHUB_CLIENT_SECRET = '5412fdcb332cf1cbcac4cbd28093792523d27a4f'
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://user:@192.168.33.10/kozmic'
    SERVER_NAME = '217.76.184.49:10001'
    SESSION_COOKIE_DOMAIN = SERVER_NAME
    TAILER_URL_TEMPLATE = 'ws://217.76.184.49:4506/{task_uuid}/'


class TestingConfig(DefaultConfig):
    TESTING = True
    SECRET_KEY = 'testing'
    KOZMIC_GITHUB_CLIENT_ID = ''
    KOZMIC_GITHUB_CLIENT_SECRET = ''
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://user:@192.168.33.10/kozmic_test'
    # We need to specify LOGIN_DISABLED = False explicitly.
    # Otherwise Flask-Login will turn off `login_required`
    # decorator because of TESTING variable.
    LOGIN_DISABLED = False
    SERVER_NAME = 'kozmic.test'
    SESSION_COOKIE_DOMAIN = SERVER_NAME

    KOZMIC_REDIS_HOST = '192.168.33.20'
    KOZMIC_REDIS_PORT = 6379
    KOZMIC_REDIS_DATABASE = 1
    BROKER_URL = 'redis://{host}:{port}/{db}'.format(
        host=KOZMIC_REDIS_HOST,
        port=KOZMIC_REDIS_PORT,
        db=KOZMIC_REDIS_DATABASE)
