Contributing
============

This document is far from extensive, but hopefully it gives an idea of how to
deploy a development version of Kozmic CI and get started.

* Clone the source code from GitHub repository: https://github.com/aromanovich/kozmic-ci

* Install the Python dependencies using pip::
    
    pip install -r requirements/kozmic.txt
    pip install -r requirements/tailer.txt
    pip install -r requirements/dev.txt

* Take a look at :ref:`configuration` variables and fill the configuration
  file ``kozmic/config_local.py`` using ``kozmic/config_local.py-dist`` as an
  example.

Running the components
----------------------
* Run the development server::

    KOZMIC_CONFIG=kozmic.config_local.DevelopmentConfig ./manage.py runserver

* Run the Celery worker::

    KOZMIC_CONFIG=kozmic.config_local.DevelopmentConfig \
    celery worker -A kozmic.entry_point.celery -l debug

* Run the tailer component::
   
    KOZMIC_CONFIG=kozmic.config_local.DevelopmentConfig \
    uwsgi --http-socket :8080 --gevent 5 --gevent-monkey-patch -H ~/Envs/kozmic/ \
          --module tailer:app
   
  Note that tailer app has to be run using uWSGI that is listed in
  ``requirements/tailer.txt``. If you use a virtual environment (which is
  strongly advised), path to it must be specified using ``-H`` argument.

Running tests
-------------
* Run all tests: ``./test.sh``
* Run tests that don't require Docker: ``./test.sh -m "not docker"``
* Run the particular test: ``./test.sh -k TestUserDB``

Working with the database
-------------------------
``./manage.py db`` provides an interface to `Alembic`_, a database migration
tool.  Run ``./manage.py db --help`` to figure out what commands it has. The
most useful are:

* Apply database migrations::

    KOZMIC_CONFIG=kozmic.config_local.DevelopmentConfig ./manage.py db upgrade

* Automatically generate a new migration::

    KOZMIC_CONFIG=kozmic.config_local.DevelopmentConfig ./manage.py db migrate

Compiling the documentation
---------------------------
::

    cd docs
    KOZMIC_CONFIG=kozmic.config_local.DevelopmentConfig make html

.. _Alembic: http://alembic.readthedocs.org/en/latest/index.html
