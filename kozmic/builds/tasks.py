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
            read_timeout = 0.5
            iterations_without_read = 0
            while True:
                if self.is_stopped():
                    break
                reads, _, _ = select.select([tailf.stdout], [], [], read_timeout)
                if not reads:
                    iterations_without_read += 1
                    if iterations_without_read * read_timeout > self._kill_timeout:
                        message = 'Sorry, your build has stalled and been killed.\n'
                        with open(self._log_path, 'a') as log:
                            log.write(message)
                        self._publish([message])
                        self._kill_container()
                        return
                    continue
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
cd /kozmic/src && git checkout -q {sha}

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
    def __init__(self, rsa_private_key, passphrase, docker_image,
                 shell_code, build_dir, clone_url, sha, container_queue):
        threading.Thread.__init__(self)
        self._docker_image = docker_image
        self._shell_code = shell_code
        self._build_dir = build_dir
        self._rsa_private_key = rsa_private_key
        self._passphrase = passphrase
        self._clone_url = clone_url
        self._sha = sha
        self._container_queue = container_queue
        self.return_code = None
        self.exc_info = None

    def run(self):
        try:
            self._run()
        except:
            self.exc_info = sys.exc_info()

    def _run(self):
        logger.info('Builder has started.')

        build_dir_path = lambda f: os.path.join(self._build_dir, f)

        build_starter_sh_path = build_dir_path('build-starter.sh')
        build_starter_sh_content = BUILD_STARTER_SH.format(
            clone_url=pipes.quote(self._clone_url),
            sha=pipes.quote(self._sha))
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
            build_script.write(self._shell_code)
        os.chmod(build_script_path, 0o755)

        client = docker.Client()

        logger.info('Starting Docker process...')
        container = client.create_container(
            self._docker_image,
            command='bash /kozmic/build-starter.sh',
            volumes={'/kozmic': {}})

        self._container_queue.put(container, block=True, timeout=60)
        self._container_queue.join()

        client.start(container, binds={self._build_dir: '/kozmic'})
        logger.info('Docker process %s has started.', container)

        self.return_code = client.wait(container)
        logger.info(client.logs(container))
        logger.info('Docker process %s has finished with return code %i.',
                    container, self.return_code)

        logger.info('Builder has finished.')


def _do_build(task_request, hook, build, task_uuid):
    config = current_app.config
    redis_client = redis.StrictRedis(host=config['KOZMIC_REDIS_HOST'],
                                     port=config['KOZMIC_REDIS_PORT'],
                                     db=config['KOZMIC_REDIS_DATABASE'])

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
        channel = task_uuid

        try:
            log_path = os.path.join(build_dir, 'build.log')
            with open(log_path, 'w') as log:
                log.write('')
            os.chmod(log_path, 0o664)

            # Convert Windows line endings to Unix:
            build_script = '\n'.join(hook.build_script.splitlines())

            container_queue = Queue.Queue()
            builder = Builder(
                rsa_private_key=hook.project.rsa_private_key,
                clone_url=hook.project.gh_clone_url,
                passphrase=hook.project.passphrase,
                docker_image=docker_image,
                shell_code=build_script,
                sha=build.gh_commit_sha,
                build_dir=build_dir,
                container_queue=container_queue)
            builder.start()

            container = container_queue.get(True, 60)
            tailer = Tailer(
                log_path=log_path,
                redis_client=redis_client,
                channel=channel,
                container=container,
                kill_timeout=config['KOZMIC_STALL_TIMEOUT'])
            multiprocessing.util.Finalize(task_request, tailer.stop)
            tailer.start()
            container_queue.task_done()

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
    job = Job.query.get(id)
    assert 'Job#{} does not exist.'.format(id)
    if not job.is_finished():
        raise RestartError('Tried to restart %r which is not finished.', job)

    build_id = job.build_id
    hook_call_id = job.hook_call_id
    db.session.delete(job)
    do_build.apply(args=(hook_call_id,))


@celery.task
def do_build(hook_call_id):
    hook_call = HookCall.query.get(hook_call_id)
    assert hook_call, 'HookCall#{} does not exist.'.format(hook_call_id)
    build = hook_call.build

    job = Job(
        build=build,
        hook_call=hook_call,
        task_uuid=do_build.request.id)
    db.session.add(job)

    job.started()
    db.session.commit()

    return_code, exc_info, stdout = _do_build(
        do_build.request, hook_call.hook, build, job.task_uuid)

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
