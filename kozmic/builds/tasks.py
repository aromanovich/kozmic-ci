# coding: utf-8
"""
kozmic.builds.tasks
~~~~~~~~~~~~~~~~~~~

.. autofunction:: do_job(hook_call_id)
.. autofunction:: restart_job(id)
"""
import os
import sys
import time
import tempfile
import shutil
import contextlib
import threading
import logging
import pipes
import multiprocessing.util
import subprocess
import fcntl
import select
import Queue

import redis
from flask import current_app
from celery.utils.log import get_task_logger
from docker import APIError as DockerAPIError

from kozmic import db, celery, docker
from kozmic.models import Build, Job, HookCall
from kozmic.docker_utils import does_docker_image_exist
from . import get_ansi_to_html_converter


logger = get_task_logger(__name__)


@contextlib.contextmanager
def create_temp_dir():
    build_dir = tempfile.mkdtemp()
    yield build_dir
    shutil.rmtree(build_dir)


class Publisher(object):
    """
    :param redis_client: Redis client
    :type log_path: redis.Redis

    :param channel: pub/sub channel name
    :type channel: str
    """

    def __init__(self, redis_client, channel):
        self._redis_client = redis_client
        self._channel = channel
        self._ansi_converter = get_ansi_to_html_converter()

    def publish(self, lines):
        if isinstance(lines, basestring):
            lines = [lines]
        for line in lines:
            line = self._ansi_converter.convert(line, full=False) + '\n'
            self._redis_client.publish(self._channel, line)
            self._redis_client.rpush(self._channel, line)

    def finish(self):
        # Remove `channel` key to let `tailer` module
        # stop listening pubsub channel
        self._redis_client.delete(self._channel)


class Tailer(threading.Thread):
    """A daemon thread that waits for additional lines to be appended to a
    specified log file.
    Once there is a new line, it does the following:

    1. Translates ANSI sequences to HTML tags;
    2. Sends the line to a Redis pub/sub channel;
    3. Pushes it to Redis list of the same name.

    If the log file does not change for ``kill_timeout`` seconds,
    specified Docker container will be killed and corresponding message
    will be appended to the log file.

    Once the thread has finished, :attr:`has_killed_container` tells
    whether the :param:`container` has stopped by itself or been killed
    by a timeout.

    :param log_path: path to the log file to watch
    :type log_path: str

    :param publisher: publisher
    :type publisher: :class:`Publisher`

    :param container: container to kill
    :type сontainer: dictionary returned by :meth:`docker.Client.create_container`

    :param kill_timeout: number of seconds since the last log append after
                         which kill the container
    :type kill_timeout: int
    """
    daemon = True

    def __init__(self, log_path, publisher, container, kill_timeout=600):
        threading.Thread.__init__(self)
        self._stop = threading.Event()
        self._log_path = log_path
        self._publisher = publisher
        self._container = container
        self._kill_timeout = kill_timeout
        self._read_timeout = 0.5
        self.has_killed_container = False

    def stop(self):
        self._stop.set()

    def is_stopped(self):
        return self._stop.isSet()

    def _kill_container(self):
        logger.info('Tailer is killing %s', self._container)
        docker.kill(self._container)
        self.has_killed_container = True
        logger.info('%s has been killed.', self._container)

    def run(self):
        logger.info('Tailer has started. Log path: %s', self._log_path)

        tailf = subprocess.Popen(['/usr/bin/tail', '-f', self._log_path],
                                 stdout=subprocess.PIPE)
        try:
            fl = fcntl.fcntl(tailf.stdout, fcntl.F_GETFL)
            fcntl.fcntl(tailf.stdout, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            buf = ''
            iterations_without_read = 0
            while True:
                if self.is_stopped():
                    break
                reads, _, _ = select.select([tailf.stdout], [], [], self._read_timeout)
                if not reads:
                    iterations_without_read += 1
                    if iterations_without_read * self._read_timeout < self._kill_timeout:
                        continue
                    else:
                        self._kill_container()
                        return
                else:
                    iterations_without_read = 0

                buf += tailf.stdout.read()
                lines = buf.split('\n')

                if lines[-1] == '':
                    buf = ''
                else:
                    buf = lines[-1]
                lines = lines[:-1]

                self._publisher.publish(lines)
        finally:
            tailf.terminate()
            tailf.wait()


SCRIPT_STARTER_SH = '''
set -x
set -e
function cleanup {{  # escape
  # Files created during the build in /kozmic/ folder are owned by root
  # from the host point of view, because the Docker daemon runs from root.
  # As a result, Celery worker, which runs as normal user, can not delete
  # it's temporary folder that is mapped to /kozmic/ container's folder.

  # To work around this we give everyone write permissions to the
  # all /kozmic subfolders.

  # Note: `|| true` to be sure that we will not change
  # ./script.sh return code by running `chmod`

  chmod -Rf a+w $(find /kozmic -type d) || true
}}  # escape
trap cleanup EXIT

# Add GitHub to known hosts
ssh-keyscan -H github.com >> /etc/ssh/ssh_known_hosts

if [ -f /kozmic/id_rsa ] && [ -f /kozmic/askpass.sh ]; then
  # Start ssh-agent service...
  eval `ssh-agent -s`
  # ...and add private key to the agent, so we won't be asked
  # for passphrase during git clone. Let ssh-add read passphrase
  # by running askpass.sh for the security's sake.
  SSH_ASKPASS=/kozmic/askpass.sh DISPLAY=:0.0 nohup ssh-add /kozmic/id_rsa
  rm /kozmic/askpass.sh /kozmic/id_rsa
fi

git clone {clone_url} /kozmic/src
cd /kozmic/src && git checkout -q {commit_sha}

chown -R kozmic /kozmic
# Redirect stdout to the file being translated to the redis pubsub channel
TERM=xterm su kozmic -c "/kozmic/script.sh" &>> /kozmic/script.log
'''.strip()

ASKPASS_SH = '''
#!/bin/bash
if [[ "$1" == *"Bad passphrase, try again"* ]]; then
  # If we don't exit on "bad passphrase", ssh-add will
  # never stop calling this script.
  exit 1
fi

echo {passphrase}
'''.strip()


class Builder(threading.Thread):
    """A thread that starts a script in a container and waits
    for it to complete.

    One of the following attributes is not ``None`` once
    the thread has finished:

    .. attribute:: return_code

        Integer, a build script's return code if everything went well.

    .. attribute:: exc_info

        ``exc_info`` triple ``(type, value, traceback)``
        if something went wrong.

    :param docker: Docker client
    :type docker: :class:`docker.Client`

    :param message_queue: a queue to which put an identifier of the started
                          Docker container. Identifier is a dictionary returned
                          by :meth:`docker.Client.create_container`.
                          Builder will block until the message is acknowledged
                          by calling :meth:`Queue.Queue.task_done`.
    :type message_queue: :class:`Queue.Queue`

    :param deploy_key: a pair of strings (private key, passphrase)
    :type deploy_key: 2-tuple of strings

    :param docker_image: a name of Docker image to be used for
                         :attr:`build_script` execution. The image
                         has to be already pulled from the registry.
    :type docker_image: str

    :param working_dir: path of the directory to be mounted in container's
                        `/kozmic` path
    :type working_dir: str

    :param clone_url: SSH clone URL
    :type clone_url: str

    :param commit_sha: SHA of the commit to be checked out
    :type commit_sha: str
    """
    def __init__(self, docker, message_queue, docker_image, script,
                 working_dir, clone_url, commit_sha, deploy_key=None):
        threading.Thread.__init__(self)

        self._docker = docker
        self._message_queue = message_queue
        self._docker_image = docker_image
        self._build_script = script
        self._working_dir = working_dir
        self._clone_url = clone_url
        self._commit_sha = commit_sha

        self._rsa_private_key = None
        self._passphrase = None
        if deploy_key:
            self._rsa_private_key, self._passphrase = deploy_key

        self.return_code = None
        self.exc_info = None
        self.container = None

    def run(self):
        try:
            self.return_code = self._run()
        except:
            self.exc_info = sys.exc_info()

    def _run(self):
        logger.info('Builder has started.')

        working_dir_path = lambda f: os.path.join(self._working_dir, f)

        script_starter_sh_path = working_dir_path('script-starter.sh')
        script_starter_sh_content = SCRIPT_STARTER_SH.format(
            clone_url=pipes.quote(self._clone_url),
            commit_sha=pipes.quote(self._commit_sha))
        with open(script_starter_sh_path, 'w') as script_starter_sh:
            script_starter_sh.write(script_starter_sh_content)

        script_path = working_dir_path('script.sh')
        with open(script_path, 'w') as script:
            script.write(self._build_script)
        os.chmod(script_path, 0o755)

        log_path = working_dir_path('script.log')
        with open(log_path, 'w') as log:
            log.write('')
        os.chmod(log_path, 0o664)

        if self._rsa_private_key and self._passphrase:
            askpass_sh_path = working_dir_path('askpass.sh')
            askpass_sh_content = ASKPASS_SH.format(
                passphrase=pipes.quote(self._passphrase))
            with open(askpass_sh_path, 'w') as askpass_sh:
                askpass_sh.write(askpass_sh_content)
            os.chmod(askpass_sh_path, 0o100)

            id_rsa_path = working_dir_path('id_rsa')
            with open(id_rsa_path, 'w') as id_rsa:
                id_rsa.write(self._rsa_private_key)
            os.chmod(id_rsa_path, 0o400)

        logger.info('Starting Docker process...')
        self.container = self._docker.create_container(
            self._docker_image,
            command='bash /kozmic/script-starter.sh',
            volumes={'/kozmic': {}})

        self._message_queue.put(self.container, block=True, timeout=60)
        self._message_queue.join()

        self._docker.start(self.container, binds={self._working_dir: '/kozmic'})
        logger.info('Docker process %s has started.', self.container)

        return_code = self._docker.wait(self.container)
        logger.info('Docker process log: %s', self._docker.logs(self.container))
        logger.info('Docker process %s has finished with return code %i.',
                    self.container, return_code)
        logger.info('Builder has finished.')

        return return_code


@contextlib.contextmanager
def _run(publisher, stall_timeout, clone_url, commit_sha,
         docker_image, script, deploy_key=None, remove_container=True):
    yielded = False
    stdout = ''
    try:
        with create_temp_dir() as working_dir:
            message_queue = Queue.Queue()
            builder = Builder(
                docker=docker._get_current_object(),  # `docker` is a local proxy
                deploy_key=deploy_key,
                clone_url=clone_url,
                commit_sha=commit_sha,
                docker_image=docker_image,
                script=script,
                working_dir=working_dir,
                message_queue=message_queue)

            log_path = os.path.join(working_dir, 'script.log')
            stop_reason = ''
            try:
                # Start Builder and wait until it will create the container
                builder.start()
                container = message_queue.get(block=True, timeout=60)

                # Now the container id is known and we can pass it to Tailer
                tailer = Tailer(
                    log_path=log_path,
                    publisher=publisher,
                    container=container,
                    kill_timeout=stall_timeout)
                tailer.start()
                try:
                    # Tell Builder to continue and wait for it to finish
                    message_queue.task_done()
                    builder.join()
                finally:
                    tailer.stop()
                    if tailer.has_killed_container:
                        stop_reason = '\nSorry, your script has stalled and been killed.\n'
            finally:
                if builder.container and remove_container:
                    docker.remove_container(builder.container)

                if os.path.exists(log_path):
                    with open(log_path, 'r') as log:
                        stdout = log.read()

                assert ((builder.return_code is not None) ^
                        (builder.exc_info is not None))
                if builder.exc_info:
                    # Re-raise exception happened in builder
                    # (it will be catched in the outer try-except)
                    raise builder.exc_info[1], None, builder.exc_info[2]
                else:
                    try:
                        yield (builder.return_code,
                               stdout + stop_reason,
                               builder.container)
                    except:
                        raise
                    finally:
                        yielded = True  # otherwise we get "generator didn't
                                        # stop after throw()" error if nested
                                        # code raised exception
    except:
        stdout += ('\nSorry, something went wrong. We are notified of '
                   'the issue and will fix it soon.')
        if not yielded:
            yield 1, stdout, None
        raise


class RestartError(Exception):
    pass


@celery.task
def restart_job(id):
    """A Celery task that restarts a job.

    :param id: int, :class:`Job` identifier
    """
    job = Job.query.get(id)
    assert 'Job#{} does not exist.'.format(id)
    if not job.is_finished():
        raise RestartError('Tried to restart %r which is not finished.', job)

    db.session.delete(job)
    # Run do_job task synchronously:
    do_job.apply(args=(job.hook_call_id,))


@celery.task
def do_job(hook_call_id):
    """A Celery task that does a job specified by a hook call.

    Creates a :class:`Job` instance and executes a build script prescribed
    by a triggered :class:`Hook`. Also sends job output to :attr:`Job.task_uuid`
    Redis pub-sub channel and updates build status.

    :param hook_call_id: int, :class:`HookCall` identifier
    """
    hook_call = HookCall.query.get(hook_call_id)
    assert hook_call, 'HookCall#{} does not exist.'.format(hook_call_id)

    job = Job(
        build=hook_call.build,
        hook_call=hook_call,
        task_uuid=do_job.request.id)
    db.session.add(job)
    job.started()
    db.session.commit()

    hook = hook_call.hook
    project = hook.project
    config = current_app.config

    redis_client = redis.StrictRedis(host=config['KOZMIC_REDIS_HOST'],
                                     port=config['KOZMIC_REDIS_PORT'],
                                     db=config['KOZMIC_REDIS_DATABASE'])
    publisher = Publisher(redis_client=redis_client, channel=job.task_uuid)

    stdout = ''
    try:
        kwargs = dict(
            publisher=publisher,
            stall_timeout=config['KOZMIC_STALL_TIMEOUT'],
            clone_url=(project.gh_https_clone_url if project.is_public else
                       project.gh_ssh_clone_url),
            commit_sha=hook_call.build.gh_commit_sha)

        message = 'Pulling "{}" Docker image...'.format(hook.docker_image)
        logger.info(message)
        publisher.publish(message)
        stdout = message + '\n'

        try:
            docker.pull(hook.docker_image)
            # Make sure that image has been successfully pulled by calling
            # `inspect_image` on it:
            docker.inspect_image(hook.docker_image)
        except DockerAPIError as e:
            logger.info('Failed to pull %s: %s.', hook.docker_image, e)
            job.finished(1)
            job.stdout = str(e)
            db.session.commit()
            return
        else:
            logger.info('%s image has been pulled.', hook.docker_image)

        if not project.is_public:
            project.deploy_key.ensure()

        if not project.is_public:
            kwargs['deploy_key'] = (
                project.deploy_key.rsa_private_key,
                project.passphrase)

        if job.hook_call.hook.install_script:
            cached_image = 'kozmic-cache/{}'.format(job.get_cache_id())
            cached_image_tag = str(project.id)
            if does_docker_image_exist(cached_image, cached_image_tag):
                install_stdout = ('Skipping install script as tracked files '
                                  'did not change...')
                publisher.publish(install_stdout)
                stdout += install_stdout + '\n'
            else:
                with _run(docker_image=hook.docker_image,
                          script=hook.install_script,
                          remove_container=False,
                          **kwargs) as (return_code, install_stdout, container):
                    stdout += install_stdout
                    if return_code == 0:
                        # Install script has finished successfully. So we
                        # promote the resulting container to an image that
                        # we will use for running the build script in
                        # this and consequent jobs
                        docker.commit(container['Id'], repository=cached_image,
                                      tag=cached_image_tag)
                        docker.remove_container(container)
                    else:
                        job.finished(return_code)
                        job.stdout = stdout
                        db.session.commit()
                        return
                assert docker.images(cached_image)
            docker_image = cached_image + ':' + cached_image_tag
        else:
            docker_image = job.hook_call.hook.docker_image

        with _run(docker_image=docker_image,
                  script=hook.build_script,
                  remove_container=True,
                  **kwargs) as (return_code, build_stdout, container):
            job.finished(return_code)
            job.stdout = stdout + build_stdout
            db.session.commit()
            return
    finally:
        publisher.finish()
