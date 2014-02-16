System Overview
===============

What is Kozmic CI?
------------------

Kozmic CI is a Docker powered continuous integration platform integrated with
GitHub.

It is written in Python using Flask and Celery. It uses Docker for a job
isolation and dependencies caching, MySQL as a data storage, Redis as a pub-sub
implementation and uWSGI as a websockets framework.

Why is Kozmic CI?
-----------------

There are plenty of continuous integration tools out there. And they all have
their pros and cons.

Some of them are very powerful but rather complex to use, like Jenkins or
TeamCity. Sometimes something simpler will do just good. Travis CI seems a good
way to go until you don't want to use custom VM image to run jobs or
constantly find yourself littering the commit history trying to debug the
over-complicated .travis.yml.

Kozmic CI is intended to be somewhere in between: to be easy to set up on your
own server, configure and use, but flexible enough to be capable of performing
any kind of job.

And hey, it's Docker powered! Docker is cool! :)

Basics
------

Kozmic CI is tightly integrated with GitHub.

There are **users** and **projects**. Kozmic users correspond to GitHub users, Kozmic
projects correspond GitHub repositories.

A user can have either one of the following roles.

* An owner, can view, configure and delete the project
* A manager, can view and configure the project
* A member, can only view the project

Projects' memberships are determined by GitHub permissions.

* The owner is the user who created the project
* Managers are those users who can push and pull from the GitHub repository
* Members are those users who can only pull from the GitHub repository

A project can have one or more **hooks** which map one-to-one to GitHub webhooks.
A Kozmic hook defines a **job** to be performed when the corresponging GitHub
hook is triggered.

A Kozmic **build** is basically a set of the jobs triggered by the same GitHub
commit. If all the jobs have succeeded, the build is considered successful. If
any of the jobs has failed, the build is considered failed.
A build status is reported to GitHub as a Commit Status.

More About Hooks and Jobs
-------------------------

As it has been mentioned above, hooks describe jobs.

To configure a hook, you must specify a Docker **base image** and a **build script**.
A build script is just an executable.
It must start with a shebang sequence (i.e., ``#!/bin/bash``) and everything that
follows is completely up to you. You can use your favorite scripting language:
bash, Python, Perl, basically anything that present in the base image.

In short, what Kozmic CI will do is to pull that Docker image from Central
Registry and run the build script in it.
The job is considered successful when the build script exits with zero return code
and failed otherwise.

Also you can specify an **install script** and it's **tracked files**.

The install script is an executable, much like the build script.
Tracked files are a list of paths in the repository.

The install script runs before the build script.
The result of a running the install script, a Docker container, is promoted to a
Docker image and cached. During the next job, if neither the install script or it's
tracked filed have changed, the install script will be skipped and the cached
image will be reused for running the build script.

That provides a really powerful tool for caching dependencies.

Base Images
-----------

Kozmic CI runs builds in isolated Docker containers that offer a clean
environment for every build.

These containers are created using base images. A base image is a
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
~~~~~~~~~~~~
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
