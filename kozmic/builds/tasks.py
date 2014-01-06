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

import tailf
import docker
import redis
from flask import current_app
from celery.utils.log import get_task_logger

from kozmic import db, celery
from kozmic.models import Build, Job, HookCall
from . import get_ansi_to_html_converter


logger = get_task_logger(__name__)


@contextlib.contextmanager
def create_temp_dir():
    build_dir = tempfile.mkdtemp()
    yield build_dir
    shutil.rmtree(build_dir)


class Tailer(threading.Thread):
    """A daemon thread that watches for additional lines to be appended to a
    specified log file.
    Once there is a new line, it translates ANSI sequences to HTML tags and:

    1. Sends the line to a Redis pub/sub channel;
    2. Pushes it to Redis list of the same name.

    If the log does not change for ``kill_timeout`` seconds, specified Docker
    container will be killed and corresponding message will be published
    to the log.

    :param log_path: path to the log file to watch
    :type log_path: str

    :param redis_client: Redis client
    :type log_path: redis.Redis

    :param channel: pub/sub channel name
    :type channel: str

    :param container: container to kill
    :type сontainer: dictionary returned by :meth:`docker.Client.create_container`

    :param kill_timeout: number of seconds since the last log append after
                         which kill the container
    :type kill_timeout: int
    """
    daemon = True

    def __init__(self, log_path, redis_client, channel, container, kill_timeout=600):
        threading.Thread.__init__(self)
        self._stop = threading.Event()
        self._log_path = log_path
        self._redis_client = redis_client
        self._channel = channel
        self._container = container
        self._kill_timeout = kill_timeout
        self._ansi_converter = get_ansi_to_html_converter()
        self._read_timeout = 0.5

    def stop(self):
        self._stop.set()

    def is_stopped(self):
        return self._stop.isSet()

    def _publish(self, lines):
        for line in lines:
            line = self._ansi_converter.convert(line, full=False) + '\n'
            self._redis_client.publish(self._channel, line)
            self._redis_client.rpush(self._channel, line)

    def _kill_container(self):
        client = docker.Client()
        logger.info('Tailer is killing %s', self._container)
        client.kill(self._container)
        logger.info('%s has been killed.', self._container)

    def run(self):
        logger.info(
            'Tailer has started. Log path: %s; channel name: %s.',
            self._log_path, self._channel)
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
                    message = 'Sorry, your build has stalled and been killed.\n'
                    with open(self._log_path, 'a') as log:
                        log.write(message)
                    self._publish([message])
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

                self._publish(lines)
        finally:
            tailf.terminate()
            tailf.wait()


BUILD_STARTER_SH = '''
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
  # ./build-script return code by running `chmod`

  chmod -Rf a+w $(find /kozmic -type d) || true
}}  # escape
trap cleanup EXIT

# Add GitHub to known hosts
ssh-keyscan -H github.com >> /etc/ssh/ssh_known_hosts
# Start ssh-agent service...
eval `ssh-agent -s`
# ...and add private key to the agent, so we won't be asked
# for passphrase on git clone. Let ssh-add read passphrase
# by running askpass.sh for the security's sake.
SSH_ASKPASS=/kozmic/askpass.sh DISPLAY=:0.0 nohup ssh-add /kozmic/id_rsa
rm /kozmic/askpass.sh /kozmic/id_rsa

git clone {clone_url} /kozmic/src
cd /kozmic/src && git checkout -q {commit_sha}

groupadd -f admin
useradd -m -d /home/kozmic -G admin -s /bin/bash kozmic
chown -R kozmic /kozmic
# Redirect stdout to the file being translated to the redis pubsub channel
TERM=xterm su kozmic -c "/kozmic/build-script.sh" &> /kozmic/build.log
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
    """A thread that starts build script in a container and waits
    for it to complete.

    One of the following attributes is not ``None`` once
    the thread has finished:

    .. attribute:: return_code

        Integer, a build script's return code if everything went well.

    .. attribute:: exc_info

        ``exc_info`` triple ``(type, value, traceback)``
        if something went wrong.

    :param message_queue: a queue to which put an identifier of the started
                          Docker container. Identifier is a dictionary returned
                          by :meth:`docker.Client.create_container`.
                          Builder will block until the message is acknowledged
                          by calling :meth:`Queue.Queue.task_done`.
    :type message_queue: :class:`Queue.Queue`

    :param rsa_private_key: deploy private key
    :type rsa_private_key: str

    :param passphrase: passphrase for :attr:`rsa_private_key`
    :type passphrase: str

    :param docker_image: a name of Docker image to be used for
                         :attr:`build_script` execution. The image
                         has to be already pulled from the registry.
    :type docker_image: str

    :param build_dir: path of the directory to be mounted in container's
                      `/kozmic` path
    :type build_dir: str

    :param clone_url: SSH clone URL
    :type clone_url: str

    :param commit_sha: SHA of the commit to be checked out
    :type commit_sha: str
    """
    def __init__(self, message_queue, rsa_private_key, passphrase,
                 docker_image, build_script, build_dir, clone_url, commit_sha):
        threading.Thread.__init__(self)
        self._rsa_private_key = rsa_private_key
        self._passphrase = passphrase
        self._docker_image = docker_image
        self._build_script = build_script
        self._build_dir = build_dir
        self._clone_url = clone_url
        self._commit_sha = commit_sha
        self._message_queue = message_queue
        self.return_code = None
        self.exc_info = None

    def run(self):
        try:
            self.return_code = self._run()
        except:
            self.exc_info = sys.exc_info()

    def _run(self):
        logger.info('Builder has started.')

        build_dir_path = lambda f: os.path.join(self._build_dir, f)

        build_starter_sh_path = build_dir_path('build-starter.sh')
        build_starter_sh_content = BUILD_STARTER_SH.format(
            clone_url=pipes.quote(self._clone_url),
            commit_sha=pipes.quote(self._commit_sha))
        with open(build_starter_sh_path, 'w') as build_starter_sh:
            build_starter_sh.write(build_starter_sh_content)

        askpass_sh_path = build_dir_path('askpass.sh')
        askpass_sh_content = ASKPASS_SH.format(
            passphrase=pipes.quote(self._passphrase))
        with open(askpass_sh_path, 'w') as askpass_sh:
            askpass_sh.write(askpass_sh_content)
        os.chmod(askpass_sh_path, 0o100)

        id_rsa_path = build_dir_path('id_rsa')
        with open(id_rsa_path, 'w') as id_rsa:
            id_rsa.write(self._rsa_private_key)
        os.chmod(id_rsa_path, 0o400)

        build_script_path = build_dir_path('build-script.sh')
        with open(build_script_path, 'w') as build_script:
            build_script.write(self._build_script)
        os.chmod(build_script_path, 0o755)

        log_path = build_dir_path('build.log')
        with open(log_path, 'w') as log:
            log.write('')
        os.chmod(log_path, 0o664)

        client = docker.Client()

        logger.info('Starting Docker process...')
        container = client.create_container(
            self._docker_image,
            command='bash /kozmic/build-starter.sh',
            volumes={'/kozmic': {}})

        self._message_queue.put(container, block=True, timeout=60)
        self._message_queue.join()

        client.start(container, binds={self._build_dir: '/kozmic'})
        logger.info('Docker process %s has started.', container)

        return_code = client.wait(container)
        logger.info('Docker process log: %s', client.logs(container))
        client.remove_container(container)
        logger.info('Docker process %s has finished with return code %i.',
                    container, return_code)
        logger.info('Builder has finished.')

        return return_code


def _do_job(task_request, hook_call, channel):
    """
    :param task_request: :class:`celery.app.task.Context` of current task
    :param hook_call: :class:`HookCall` that triggered the job
    :param channel: Redis pub-sub channel name
    """
    config = current_app.config
    redis_client = redis.StrictRedis(host=config['KOZMIC_REDIS_HOST'],
                                     port=config['KOZMIC_REDIS_PORT'],
                                     db=config['KOZMIC_REDIS_DATABASE'])
    hook = hook_call.hook
    docker_image = hook.docker_image

    client = docker.Client()
    logger.info('Pulling %s image...', docker_image)
    try:
        client.pull(docker_image)
        # Make sure that image has been successfully pulled by calling
        # `inspect_image` on it:
        client.inspect_image(docker_image)
    except docker.APIError as e:
        logger.info('Failed to pull %s: %s.', docker_image, e)
        return 1, None, str(e)
    else:
        logger.info('%s image has been pulled.', docker_image)

    with create_temp_dir() as build_dir:
        log_path = os.path.join(build_dir, 'build.log')
        try:
            message_queue = Queue.Queue()
            builder = Builder(
                rsa_private_key=hook.project.rsa_private_key,
                passphrase=hook.project.passphrase,
                clone_url=hook.project.gh_clone_url,
                commit_sha=hook_call.build.gh_commit_sha,
                docker_image=docker_image,
                build_script=hook.build_script,
                build_dir=build_dir,
                message_queue=message_queue)

            # Start Builder and wait until it will not start the container
            builder.start()
            container = message_queue.get(block=True, timeout=60)

            # Now the container id is known and we can pass it to Tailer
            tailer = Tailer(
                log_path=log_path,
                redis_client=redis_client,
                channel=channel,
                container=container,
                kill_timeout=config['KOZMIC_STALL_TIMEOUT'])
            # Tailer is a daemon process. Stop it when Celery task
            # quits by binding a finalizer on Celery task context
            f = multiprocessing.util.Finalize(task_request, tailer.stop)
            tailer.start()

            # Tell Builder to continue and wait for it to finish
            message_queue.task_done()
            builder.join()

            stdout = ''
            if os.path.exists(log_path):
                with open(log_path, 'r') as log:
                    stdout = log.read()
        finally:
            # Always remove `channel` key to let `tailer` module
            # stop listening pubsub channel
            redis_client.delete(channel)

    return builder.return_code, builder.exc_info, stdout


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

    return_code, exc_info, stdout = _do_job(
        do_job.request, hook_call, job.task_uuid)
    if exc_info:
        job.finished(1)
        stdout += ('\nSorry, something went wrong. We are notified of the '
                   'issue and we will fix it soon.')
    else:
        job.finished(return_code)
    job.stdout = stdout
    db.session.commit()

    if exc_info:
        raise exc_info[1], None, exc_info[2]
