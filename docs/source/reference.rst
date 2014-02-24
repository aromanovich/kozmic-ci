Reference
=========
It's important to understand how jobs are performed in order to efficiently use
Kozmic CI features such as dependencies caching.

As it has been mentioned earlier, Kozmic CI uses Docker for a job isolation and
dependencies caching.

A job is defined by a hook. A hook consists of:

* Docker base image
* Build script
* Install script (optional)
* Tracked files (optional)

Job Workflow
------------
Here's what Kozmic CI does when GitHub triggers the hook.

* The Docker base image is pulled from the Central registry.
* If the install script is specified and it hasn't been run before or if the
  base image, the install script itself or some of tracked files have been
  changed, the install script is run and the resulting container is promoted to
  an image and cached.
  
  Otherwise this step is skipped.

* The build script is run in a Docker container created either from a cached
  image (if the install script is specified) or Docker base image.

If either the install script or the build script exits with a return code
different from zero, the job considered failed.

How Scripts Are Run
-------------------
Install scripts are processed the same way as build scripts. The only
difference is that a result of an install script, a container, is cached.

1. A container is created from that image. It's ``/kozmic`` directory is a
   volume and mounted to the host machine.
2. The script to be run is placed in that directory, along with some auxiliary
   files: a helper for running the script, a file to which the script output
   will be written, deploy key, etc.
3. If the project's repository is private, ``ssh-agent`` is started and
   the private deploy key is added to it.
4. The repository is cloned to ``/kozmic/src`` and the required commit is
   checked out.
5. Finally, the script is run in the ``/kozmic/src`` directory from the
   ``kozmic`` user. ``/kozmic`` directory and it's content owned by
   ``kozmic`` user.

.. note::

    Changes that the install script makes to the ``/kozmic`` directory will not
    be cached.

Examples
--------

MySQL and Python
++++++++++++++++
Suppose the project is written in Python and uses MySQL. Here's an example of
a hook configuration.

Docker base image: ``kozmic/ubuntu:12.04``.

Install script::

    #!/bin/bash
    set -e  # Exit if any command returns a non-zero status

    sudo su <<EOF
    pip install -r ./requirements/basic.txt
    pip install -r ./requirements/dev.txt
    EOF

Tracked files::

    requirements/basic.txt
    requirements/dev.txt

Build script::

    #!/bin/bash
    set -e

    sudo su <<EOF
    /usr/bin/mysqld_safe &
    sleep 3  # Give it time to start
    mysql -e 'create database rsstank_test character set utf8 collate utf8_general_ci;'
    EOF

    cp ./rsstank/config_local.py-kozmic ./rsstank/config_local.py
    ./test.sh

We run ``pip`` from root because it sets up packages system-wide.

MySQL is already set up in the ``kozmic/ubuntu:12.04`` image. It has to be
started manually before the tests, because Docker doesn't use Ubuntu's init
system.

MongoDB and Python
++++++++++++++++++
Here's another example for a project that uses MongoDB.

Docker base image: ``kozmic/debian:wheezy``.

Install script::

    #!/bin/bash
    set -e  # Exit if any command returns a non-zero status

    echo 'deb http://downloads-distro.mongodb.org/repo/debian-sysvinit dist 10gen' | \
        sudo tee /etc/apt/sources.list.d/mongodb.list
    sudo apt-get update
    sudo apt-get install -y --force-yes mongodb-10gen

    sudo pip install -r requirements/devel.txt

Tracked files::

    requirements/basic.txt
    requirements/dev.txt

Build script::

    #!/bin/bash
    set -e  # Exit if any command returns a non-zero status

    sudo /etc/init.d/mongodb start

    py.test --cov=adlift --cov-report=term
