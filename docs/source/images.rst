Base Images
===========

Overview
--------
Kozmic CI runs builds in isolated Docker containers that offer a clean
environment for every build.

These containers are created using base images. A :term:`base image` is a
Docker image that meets a :ref:`few requirements <test-image-requirements>`.

At this point Kozmic CI supports base images that are only hosted on
a `Central Registry`_ provided by the Docker project.

To tell Kozmic CI use particular base image for running a job, you must specify it's
repository name in the hook settings. Repository names look like
``<username>/<repo_name>``, i.e. ``kozmic/ubuntu-base``. You can also specify a tag
from that repository, i.e. ``kozmic/ubuntu-base:12.04``.

The specified base image will be pulled from the registry before
running the first job.

Kozmic CI provides a number of "official" base images: https://index.docker.io/u/kozmic/.
They are all built using `Trusted Build`_ service and their `Dockerfiles are
hosted on GitHub`_. If some of the base images is missing something,
or you built a base image for your own needs and think that it may be
useful for others -- please feel free to submit a pull request or open an issue.

.. _test-image-requirements:

Requirements
------------
Kozmic CI :term:`base image` must meet two requirements.

1. It must have the following packages installed:
  * ``bash``
  * ``sudo``
  * ``git``
  * ``openssh-client``
2. It must have a user named ``kozmic`` with sudo rights without password check.

.. _Central Registry: https://index.docker.io/
.. _Trusted Build: http://blog.docker.io/2013/11/introducing-trusted-builds/
.. _Dockerfiles are hosted on GitHub: https://github.com/aromanovich/kozmic-images
