Installation: the Hard Way
==========================

The system comprises of three components:

* A web application that implements UI and exposes webhooks (:mod:`kozmic`)
* A uWSGI-application that sends a job log into a websocket (:mod:`tailer`)
* A Celery-worker that runs jobs

If you're planning to use Kozmic CI status images in GitHub README files,
they must be served through HTTPS to prevent GitHub from caching them
(see :setting:`KOZMIC_USE_HTTPS_FOR_BADGES` setting).

:mod:`tailer` **must** be run using uWSGI that is listed in its requirements
(``./requirements/tailer.txt``).

A `Kozmic CI's Dockerfile`_ is pretty much self-documenting.

It uses `Supervisor`_ for running all the components (see the last
three sections of `supervisor.conf`_) and `uWSGI`_ as an
application server for :mod:`kozmic` and :mod:`tailer` (see
`kozmic-uwsgi.ini`_ and `tailer-uwsgi.ini`_).

It also runs database migrations on start::

    KOZMIC_CONFIG=kozmic.config_local.Config ./manage.py db upgrade

.. _Supervisor: http://supervisord.org/
.. _uWSGI: http://uwsgi-docs.readthedocs.org/en/latest/
.. _Kozmic CI's Dockerfile: https://github.com/aromanovich/kozmic-ci/tree/master/docker/Dockerfile
.. _supervisor.conf: https://github.com/aromanovich/kozmic-ci/blob/master/docker/files/supervisor.conf
.. _kozmic-uwsgi.ini: https://github.com/aromanovich/kozmic-ci/blob/master/docker/files/kozmic-uwsgi.ini
.. _tailer-uwsgi.ini: https://github.com/aromanovich/kozmic-ci/blob/master/docker/files/tailer-uwsgi.ini
