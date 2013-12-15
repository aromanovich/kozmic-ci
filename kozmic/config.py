# coding: utf-8
"""
kozmic.config
~~~~~~~~~~~~~

Kozmic default configurations
"""
import os


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
    MAIL_DEFAULT_SENDER = None  # _must_ be configured


class DevelopmentConfig(DefaultConfig):
    DEBUG = True
    SECRET_KEY = 'development'


class TestingConfig(DefaultConfig):
    TESTING = True
    SECRET_KEY = 'testing'
    SERVER_NAME = 'kozmic.test'
    KOZMIC_GITHUB_CLIENT_ID = ''
    KOZMIC_GITHUB_CLIENT_SECRET = ''
    # We need to specify LOGIN_DISABLED = False explicitly,
    # otherwise Flask-Login will turn off `login_required`
    # decorator because of TESTING variable:
    LOGIN_DISABLED = False
    MAIL_SUPPRESS_SEND = True
    MAIL_DEFAULT_SENDER = 'Kozmic CI <no-reply@kozmic.test>'