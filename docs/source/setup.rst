Installation: the Fast Way
==========================

Kozmic CI offers a Docker-based single-node distribution.

It has some limitations (no HTTPS support; cached Docker images are
stored inside the container and will be lost after it's death;
and it is a single node configuration, after all), but it's
the fastest and easiest way to get started.

The basic prerequisites you’ll need in order to set it up:

* Ubuntu 13.04
* MySQL
* Redis
* Docker > 0.7.0

Step 1: Register a new application on GitHub 
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Go to https://github.com/settings/applications/new and create an application.

Set the homepage URL to ``http://my-server-ip-or-addr`` and the authorization
callback URL to ``http://my-server-ip-or-addr/_auth/auth-callback``.

Step 2: Fill a Kozmic config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Download https://raw.github.com/aromanovich/kozmic-ci/master/docker/config.py-docker.

Change MySQL- and Redis-related variables according to your setup, specify a
secret key, a client id and a client secret of your GitHub application.

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
