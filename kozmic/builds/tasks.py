import os
import time
import tempfile
import shutil
import contextlib
import threading
import logging
import pipes

import tailf
import docker
import redis
from flask import current_app
from celery.utils.log import get_task_logger

from kozmic import db, celery
from kozmic.models import Build, BuildStep, HookCall


logger = get_task_logger(__name__)


@contextlib.contextmanager
def create_temp_dir():
    build_dir = tempfile.mkdtemp()
    yield build_dir
    shutil.rmtree(build_dir)


class Tailer(threading.Thread):
    daemon = True

    def __init__(self, log_path, redis_client, channel):
        threading.Thread.__init__(self)
        self._log_path = log_path
        self._redis_client = redis_client
        self._channel = channel

    def run(self):
        logger.info(
            'Tailer has started. Log path: %s; channel name: %s.',
            self._log_path, self._channel)
        for line in tailf.tailf(self._log_path):
            line += '\n'
            self._redis_client.publish(self._channel, line)
            self._redis_client.rpush(self._channel, line)


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

  chmod -R a+w $(find /kozmic -type d)
}}  # escape
trap cleanup EXIT

cd kozmic
# Add GitHub to known hosts
ssh-keyscan -H github.com >> /etc/ssh/ssh_known_hosts

# Start ssh-agent service...
eval `ssh-agent -s`
# ...and add private key to the agent, so we won't be asked
# for passphrase on git clone. Let ssh-add read passphrase
# by running askpass.sh for the security's sake.
SSH_ASKPASS=./askpass.sh DISPLAY=:0.0 nohup ssh-add ./id_rsa
rm ./askpass.sh ./id_rsa

git clone {clone_url} ./src
cd ./src && git checkout -q {sha}

# Disable stdout buffering and redirect it to the file
# being tailed to the redis pubsub channel
stdbuf -o0 bash ../build-script.sh > ../build.log
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
                 shell_code, build_dir, clone_url, sha):
        threading.Thread.__init__(self)
        self._docker_image = docker_image
        self._shell_code = shell_code
        self._build_dir = build_dir
        self._rsa_private_key = rsa_private_key
        self._passphrase = passphrase
        self._clone_url = clone_url
        self._sha = sha
        self.return_code = None

    def run(self):
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
        os.chmod(askpass_sh_path, 100)

        id_rsa_path = build_dir_path('id_rsa')
        with open(id_rsa_path, 'w') as id_rsa:
            id_rsa.write(self._rsa_private_key)
        os.chmod(id_rsa_path, 400)

        build_script_path = build_dir_path('build-script.sh')
        with open(build_script_path, 'w') as build_script:
            build_script.write(self._shell_code)

        client = docker.Client()

        logger.info('Pulling %s image...', self._docker_image)
        client.pull(self._docker_image)
        logger.info('%s image has been pulled.', self._docker_image)

        container = client.create_container(
            self._docker_image,
            command='bash /kozmic/build-starter.sh',
            volumes={'/kozmic': {}})
        client.start(container, binds={self._build_dir: '/kozmic'})

        logger.info('Docker process %s has started.', container)
        self.return_code = client.wait(container)
        logger.info(client.logs(container))
        logger.info('Docker process %s has finished with return code %i.',
                    container, self.return_code)

        logger.info('Builder has finished.')


def _do_build(hook, build, task_uuid):
    config = current_app.config
    redis_client = redis.StrictRedis(host=config['KOZMIC_REDIS_HOST'],
                                     port=config['KOZMIC_REDIS_PORT'],
                                     db=config['KOZMIC_REDIS_DATABASE'])

    with create_temp_dir() as build_dir:
        channel = task_uuid

        try:
            log_path = os.path.join(build_dir, 'build.log')
            tailer = Tailer(
                log_path=log_path,
                redis_client=redis_client,
                channel=channel)
            tailer.start()

            builder = Builder(
                rsa_private_key=hook.project.rsa_private_key,
                clone_url=hook.project.gh_clone_url,
                passphrase=hook.project.passphrase,
                docker_image=hook.docker_image,
                shell_code=hook.build_script,
                sha=build.gh_commit_sha,
                build_dir=build_dir)
            builder.start()
            builder.join()
            
            stdout = ''
            if os.path.exists(log_path):
                with open(log_path, 'r') as log:
                    stdout = log.read()
        finally:
            # Always remove `channel` key to let `tailer` module
            # stop listening pubsub channel
            redis_client.delete(channel)

    return builder.return_code, stdout


@celery.task
def do_build(build_id, hook_call_id):
    hook_call = HookCall.query.get(hook_call_id)
    assert hook_call, 'HookCall#{} does not exist.'.format(hook_call_id)

    build = Build.query.get(build_id)
    assert build, 'Build#{} does not exist.'.format(build_id)

    hook = hook_call.hook

    step = BuildStep(
        build=build,
        hook_call=hook_call,
        task_uuid=do_build.request.id)
    db.session.add(step)
    step.started()
    db.session.commit()

    return_code, stdout = _do_build(
        hook, build, do_build.request.id)

    step.finished(return_code)
    step.stdout = stdout
    db.session.commit()
