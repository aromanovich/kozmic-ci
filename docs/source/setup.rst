Installation and Set Up
=======================

Basic prerequisites you’ll need in order to run Kozmic CI:

* UNIX-based operating system 
* Python 2.7
* Redis
* MySQL
* Docker > 0.7.0

Clone the code from https://github.com/aromanovich/kozmic-ci.

Set up the requirements listed by ``./requirements/kozmic.txt`` and
``./requirements/tailer.txt`` using pip.

Register a new OAuth apllication on GitHub:
https://github.com/settings/applications/new.

Configuration
-------------

Fill ``./kozmic/config_local.py`` using ``./kozmic/config_local.py-dist``
as an example. The following variables must be specified:

* ``SECRET_KEY``: a secret string. Used for signing cookie-based sessions,
                  as a passphrase for private deploy keys, etc.
* ``SERVER_NAME``: The name and port number of the server
                   (e.g., ``'kozmic-ci.company.com'`` or ``'127.0.0.1:5000'``);
* ``BROKER_URL``: Celery broker URL (default: ``'redis://localhost:6379/0'``);
* ``MAIL_DEFAULT_SENDER``: "From" e-mail address to be used for notifications;
* ``KOZMIC_REDIS_HOST``: Redis host (default: ``'localhost'``);
* ``KOZMIC_REDIS_PORT``: Redis port (default: ``6379``);
* ``KOZMIC_REDIS_DATABASE``: Redis database (default: ``0``);
* ``KOZMIC_STALL_TIMEOUT``: Number of seconds since the last job output after
                            which the job is considered "hung" and it's Docker
                            container gets killed;
* ``KOZMIC_GITHUB_CLIENT_ID``: OAuth client id;
* ``KOZMIC_GITHUB_CLIENT_SECRET``: OAuth client secret;
* ``SQLALCHEMY_DATABASE_URI``: SQLAlchemy connection string (e.g.,
                               ``'mysql+pymysql://user:password@127.0.0.1/kozmic'``);
* ``TAILER_URL_TEMPLATE``: URL template to be used to get a websocket URL for a job.
                           Must point to a :mod:`tailer` application instance and
                           contain ``task_uuid`` variable. (e.g.,
                           ``'ws://kozmic-ci.company.com:8080/{task_uuid}/'``);

Default configuration expects to find an SMTP server on a local machine on port 25.
It can be changed: http://pythonhosted.org/Flask-Mail/#configuring-flask-mail.

.. note:: 
    Environment variable ``KOZMIC_CONFIG`` tells :func:`kozmic.create_app` which
    config to use. For example, to run development server you can type:
    ``KOZMIC_CONFIG=kozmic.config_local.DevelopmentConfig ./manage.py runserver``

Notes
-----

* :mod:`tailer` must be run using uWSGI that is listed in its requirements
  (``./requirements/tailer.txt``).
* Kozmic CI status images are served through HTTPS to prevent GitHub from
  caching them. If you're planning to use status badges, :mod:`kozmic`
  server must support HTTPS.

Deployment example with Supervisor and uWSGI
--------------------------------------------

The system contains of a three main components:

* A web application that implements UI and exposes webhooks (:mod:`kozmic`);
* A uWSGI-application that tails job log into a websocket (:mod:`tailer`);
* A Celery-worker that runs jobs.

As of now, only single-node configuration is supported. It is recommended to use
Supervisor for running all the components. Here are Supervisor example configuration files.

Supervisor ``celery.conf``:

.. literalinclude:: setup/supervisor-celery.conf

Supervisor ``uwsgi.conf``:

.. literalinclude:: setup/supervisor-uwsgi.conf

uWSGI configuration files (to put in ``/etc/uwsgi/apps/``):

.. literalinclude:: setup/uwsgi-kozmic.ini

.. literalinclude:: setup/uwsgi-tailer.ini
