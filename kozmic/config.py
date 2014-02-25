# coding: utf-8
"""
kozmic.config
~~~~~~~~~~~~~

Kozmic default configuration
"""
import os


class DefaultConfig(object):
    DEBUG = False
    TESTING = False

    KOZMIC_SENTRY_DSN = None
    KOZMIC_REDIS_HOST = 'localhost'
    KOZMIC_REDIS_PORT = 6379
    KOZMIC_REDIS_DATABASE = 0
    KOZMIC_STALL_TIMEOUT = 900
    KOZMIC_ENABLE_EMAIL_NOTIFICATIONS = False  # They are not very useful
                                               # at the moment
    KOZMIC_CACHED_IMAGES_LIMIT = 3
    KOZMIC_USE_HTTPS_FOR_BADGES = False

    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://kozmic:@127.0.0.1/kozmic'

    DOCKER_URL = 'unix://var/run/docker.sock'
    DOCKER_API_VERSION = '1.8'

    BROKER_URL = 'redis://{host}:{port}/{db}'.format(
        host=KOZMIC_REDIS_HOST,
        port=KOZMIC_REDIS_PORT,
        db=KOZMIC_REDIS_DATABASE)
    CELERY_IMPORTS = ('kozmic.builds',)
    CELERY_ALWAYS_EAGER = False
    CELERY_EAGER_PROPAGATES_EXCEPTIONS = True
    CELERY_IGNORE_RESULT = True
    CELERY_DEFAULT_QUEUE = 'kozmic'

    TAILER_URL_TEMPLATE = None

    MAIL_DEFAULT_SENDER = None  # must be configured if email
                                # notifications are enabled


class DevelopmentConfig(DefaultConfig):
    DEBUG = True
    SECRET_KEY = 'development'


class TestingConfig(DefaultConfig):
    TESTING = True
    SECRET_KEY = 'testing'
    SERVER_NAME = 'kozmic.test'
    KOZMIC_GITHUB_CLIENT_ID = ''
    KOZMIC_GITHUB_CLIENT_SECRET = ''
    KOZMIC_ENABLE_EMAIL_NOTIFICATIONS = True
    # We need to specify LOGIN_DISABLED = False explicitly,
    # otherwise Flask-Login will turn off `login_required`
    # decorator because of TESTING variable:
    LOGIN_DISABLED = False
    MAIL_SUPPRESS_SEND = True
    MAIL_DEFAULT_SENDER = 'Kozmic CI <no-reply@kozmic.test>'
    CELERY_ALWAYS_EAGER = True
    TAILER_URL_TEMPLATE = 'ws://127.0.0.1:8801/{job_id}/'
