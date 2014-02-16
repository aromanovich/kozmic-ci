.. _configuration:

Configuration
=============

An environment variable ``KOZMIC_CONFIG`` tells the application
(:func:`kozmic.create_app` and :mod:`tailer`) which config to use. For example,
to run a development server you can use the following command:
``KOZMIC_CONFIG=kozmic.config_local.DevelopmentConfig ./manage.py runserver``

Variables
~~~~~~~~~

.. setting:: SECRET_KEY
``SECRET_KEY``
    A secret string. Used for signing cookie-based sessions, as a passphrase
    for private deploy keys, etc.

.. setting:: SERVER_NAME
``SERVER_NAME``
    The name and port number of the server (e.g., ``'kozmic-ci.company.com'``
    or ``'127.0.0.1:5000'``.

.. setting:: SESSION_COOKIE_DOMAIN
``SESSION_COOKIE_DOMAIN``
    The domain for the session cookie. If this is not set, the cookie will
    be valid for all subdomains of :setting:`SERVER_NAME`.

    .. note::

        If you're using an IP address as a :setting:`SERVER_NAME`, you must
        specify the same IP address in :setting:`SESSION_COOKIE_DOMAIN`.
        Otherwise cookies will not work.

.. setting:: KOZMIC_GITHUB_CLIENT_ID
``KOZMIC_GITHUB_CLIENT_ID``
    OAuth client id

.. setting:: KOZMIC_GITHUB_CLIENT_SECRET
``KOZMIC_GITHUB_CLIENT_SECRET``
    OAuth client secret

.. setting:: BROKER_URL
``BROKER_URL``
    Celery broker URL (default: ``'redis://localhost:6379/0'``)

.. setting:: MAIL_DEFAULT_SENDER
``MAIL_DEFAULT_SENDER``
    "From" e-mail address to be used for notifications

.. setting:: KOZMIC_REDIS_HOST
``KOZMIC_REDIS_HOST``
    Redis host (default: ``'localhost'``)

.. setting:: KOZMIC_REDIS_PORT
``KOZMIC_REDIS_PORT``
    Redis port (default: ``6379``)

.. setting:: KOZMIC_REDIS_DATABASE
``KOZMIC_REDIS_DATABASE``
    Redis database (default: ``0``)

.. setting:: KOZMIC_STALL_TIMEOUT
``KOZMIC_STALL_TIMEOUT``
    Number of seconds since the last job output after which the job is
    considered "hung" and it's Docker container gets killed (default: ``900``)

.. setting:: KOZMIC_ENABLE_EMAIL_NOTIFICATIONS
``KOZMIC_ENABLE_EMAIL_NOTIFICATIONS``
    Whether e-mail notification enabled? (default: ``True``)

.. setting:: KOZMIC_CACHED_IMAGES_LIMIT
``KOZMIC_CACHED_IMAGES_LIMIT``
    The maximum number of cached Docker images (a cached image is a result of
    an install script) per project (default: ``3``)

.. setting:: KOZMIC_USE_HTTPS_FOR_BADGES
``KOZMIC_USE_HTTPS_FOR_BADGES``
    If you're planning to use Kozmic CI status images in GitHub README files,
    they must be served through HTTPS to prevent GitHub from caching them.

    This variable only affects the UI and used for showing a correct badge URL
    (default: ``False``)

.. setting:: SQLALCHEMY_DATABASE_URI
``SQLALCHEMY_DATABASE_URI``
    SQLAlchemy connection string (e.g.,
    ``'mysql+pymysql://user:password@127.0.0.1/kozmic'``);

.. setting:: TAILER_URL_TEMPLATE
``TAILER_URL_TEMPLATE``
    URL template to be used to get a websocket URL for a job.  Must point to a
    :mod:`tailer` application instance and contain ``job_id`` variable.  (e.g.,
    ``'ws://kozmic-ci.company.com:8080/{job_id}/'``);

.. setting:: DOCKER_URL
``DOCKER_URL``
    Docker API URL (default: ``'unix://var/run/docker.sock'``)


Default configuration expects to find an SMTP server on a local machine on port 25.
It can be changed: http://pythonhosted.org/Flask-Mail/#configuring-flask-mail.
