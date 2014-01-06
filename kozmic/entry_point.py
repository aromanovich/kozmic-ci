"""
kozmic.entry_point
~~~~~~~~~~~~~~~~~~
A module to be used as an ``-A`` argument for ``celery worker`` command.
Contains a :class:`celery.Celery` instance.
"""
from . import celery, create_app


app = create_app()  # This will configure `celery` instance
