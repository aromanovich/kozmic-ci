Installation and Set Up
=======================

The Fast Way
------------
Kozmic CI offers a Docker-based single-node distribution.

It has some limitations (no HTTPS support; cached Docker images are
stored inside the container and will be lost after it's death;
and it is a single node configuration, after all), but it's
the fastest and easiest way to get started.

Step 0: Install basic requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The basic requirements are:

* Ubuntu 12.04+
* MySQL
* Redis
* Docker 0.7+

Add Docker repository key to the local keychain::

     apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 36A1D7869245C8950F966E92D8576A8BA88D21E9

Add Docker repository to the apt sources list::
    
    echo deb http://get.docker.io/ubuntu docker main > /etc/apt/sources.list.d/docker.list

Install Docker, MySQL and Redis::

    apt-get update
    apt-get install -f lxc-docker mysql-server redis-server

Run ``ifconfig`` to find out the IP address assigned to the ``docker0`` bridge::

    $ ifconfig
    docker0   Link encap:Ethernet  HWaddr fe:a1:e0:60:a8:64
              inet addr:172.17.42.1  Bcast:0.0.0.0  Mask:255.255.0.0
              inet6 addr: fe80::3c08:caff:fe68:7f3c/64 Scope:Link
              [...output omitted for brevity...]

Create ``/etc/mysql/conf.d/my.cnf`` and put the following lines into it::

    [mysqld]
    bind-address = 172.17.42.1
    collation-server = utf8_unicode_ci
    character-set-server = utf8

Find line ``bind 127.0.0.1`` in ``/etc/redis/redis.conf`` and replace it
with ``bind 172.17.42.1``.

Restart MySQL and Redis servers::

    service mysql restart
    service redis-server restart

Create a MySQL database and a user with access to it::
    
    mysql -u root -p <password> -e "CREATE DATABASE kozmic;"
    mysql -u root -p <password> -e "GRANT ALL PRIVILEGES ON kozmic.* TO 'kozmic'@'%';"


Step 1: Register a new application on GitHub 
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Go to https://github.com/settings/applications/new and create an application.

Set the homepage URL to ``http://my-server-ip-or-addr`` and the authorization
callback URL to ``http://my-server-ip-or-addr/_auth/auth-callback``.

Step 2: Fill a Kozmic config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Download https://raw.github.com/aromanovich/kozmic-ci/master/docker/config.py-docker.

According to the first step, :setting:`SQLALCHEMY_DATABASE_URI` must be set to
``'mysql+pymysql://kozmic:@172.17.42.1/kozmic'`` and
:setting:`KOZMIC_REDIS_HOST` to ``'172.17.42.1'``.

:setting:`SERVER_NAME`, :setting:`SECRET_KEY`,
:setting:`KOZMIC_GITHUB_CLIENT_ID`, :setting:`KOZMIC_GITHUB_CLIENT_SECRET`
must also be set, see :ref:`configuration` section for details.

Step 2: Pull a Docker image
~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

    $ docker pull aromanovich/kozmic

The Dockerfile used to build ``aromanovich/kozmic``
is available on GitHub: https://github.com/aromanovich/kozmic-ci/tree/master/docker.

Step 2: Start a container
~~~~~~~~~~~~~~~~~~~~~~~~~
Create a directory that will contain Kozmic CI logs and then run:

::

    docker run -e=WORKER_CONCURRENCY=2 \
               -e=CONFIG="`cat ./config.py`" \
               -p=80:80 -p=8080:8080 \
               -v=/absolute/path/to/created/logs/directory/:/var/log/ \
               -privileged aromanovich/kozmic /run.sh

A few comments:

* ``WORKER_CONCURRENCY`` env variable must contain a number of workers that
  will run jobs
* ``CONFIG`` env variable must contain a Python code defining a ``Config``
  class inherited from ``kozmic.config.DefaultConfig``
* ``-p=80:80 -p=8080:8080`` binds the container ports to the host system
* ``-v=/absolute/path/to/created/logs/directory/:/var/log/`` mounts the logs
  directory from the host into the container which allows us to see what's
  happening inside the container
* ``-privileged`` key is required to allow running `Docker within Docker`_.

.. _Docker within Docker: http://blog.docker.io/2013/09/docker-can-now-run-within-docker/

After starting the container, take a look at the ``logs`` directory content and
make sure that it doesn't say any errors. That's it!

The Usual Way
-------------

The usual way is to not use Docker-based distribution, but manually deploy each
of the three components:

* A web application that implements UI and exposes webhooks (:mod:`kozmic`)
* A uWSGI-application that sends a job log into a websocket (:mod:`tailer`)
* A Celery-worker that runs jobs

A `Kozmic CI's Dockerfile`_ is pretty much self-documenting about how to do it.

It uses `Supervisor`_ for running all the components (see the last three
sections of `supervisor.conf`_) and `uWSGI`_ as an application server for
:mod:`kozmic` and :mod:`tailer` (see `kozmic-uwsgi.ini`_ and
`tailer-uwsgi.ini`_).

You will also have to use ``manage.py`` to run the database migrations::

    KOZMIC_CONFIG=kozmic.config_local.Config ./manage.py db upgrade


If you're planning to use Kozmic CI status images in GitHub README files,
they must be served through HTTPS to prevent GitHub from caching them
(see :setting:`KOZMIC_USE_HTTPS_FOR_BADGES` setting).

:mod:`tailer` **must** be run using uWSGI that is listed in its requirements
(``./requirements/tailer.txt``).

.. _Supervisor: http://supervisord.org/
.. _uWSGI: http://uwsgi-docs.readthedocs.org/en/latest/
.. _Kozmic CI's Dockerfile: https://github.com/aromanovich/kozmic-ci/tree/master/docker/Dockerfile
.. _supervisor.conf: https://github.com/aromanovich/kozmic-ci/blob/master/docker/files/supervisor.conf
.. _kozmic-uwsgi.ini: https://github.com/aromanovich/kozmic-ci/blob/master/docker/files/kozmic-uwsgi.ini
.. _tailer-uwsgi.ini: https://github.com/aromanovich/kozmic-ci/blob/master/docker/files/tailer-uwsgi.ini
