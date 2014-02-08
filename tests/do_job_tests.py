# coding: utf-8
import os
import tempfile
import shutil
import contextlib

import mock
import docker
from flask.ext.webtest import SessionScope

import kozmic.builds.tasks
from kozmic.models import Project, DeployKey, Build, Job, TrackedFile
from . import TestCase, factories, utils


class TestDoJob(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.working_dir = tempfile.mkdtemp()
        repo_dir = os.path.join(self.working_dir, 'test-repo')
        self.prev_head_sha = utils.create_git_repo(repo_dir)
        self.head_sha = utils.add_commit_to_git_repo(repo_dir)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(
            owner=self.user,
            gh_clone_url='/kozmic/test-repo')  # NOTE

        self.hook = factories.HookFactory.create(
            project=self.project,
            docker_image='kozmic/ubuntu-base:12.04',
            install_script='#!/bin/bash\n'
                           'sudo su -c "mkdir /hello/ && echo \\"it works\\" > /hello/readme.txt"\n'
                           'echo "installed!"',
            build_script='cat /hello/readme.txt && echo "YEAH"')

    def _do_job(self, hook_call):
        @contextlib.contextmanager
        def create_temp_dir():
            working_dir = tempfile.mktemp()
            shutil.copytree(self.working_dir, working_dir)
            yield working_dir
            shutil.rmtree(working_dir)

        with SessionScope(self.db):
            with mock.patch.object(Build, 'set_status'), \
                 mock.patch.object(DeployKey, 'ensure') as ensure_deploy_key_mock, \
                 mock.patch.object(Job, 'get_cache_id', return_value='qwerty'), \
                 mock.patch('kozmic.builds.tasks.create_temp_dir', create_temp_dir):
                kozmic.builds.tasks.do_job(hook_call_id=hook_call.id)
        self.db.session.rollback()

        if hook_call.hook.project.is_public:
            assert not ensure_deploy_key_mock.called

        return Job.query.filter_by(hook_call=hook_call).first()

    def test_private_project(self):
        cache_id = 'qwerty'
        cached_image = 'kozmic-cache/{}'.format(cache_id)

        client = docker.Client()
        try:
            client.remove_image('kozmic-cache/qwerty')
        except:
            pass
        assert not client.images(cached_image)

        build = factories.BuildFactory.create(
            project=self.project,
            gh_commit_sha=self.prev_head_sha)
        hook_call = factories.HookCallFactory.create(
            hook=self.hook,
            build=build)

        job = self._do_job(hook_call)
        assert job.return_code == 0
        assert job.stdout == 'installed!\nit works\nYEAH\n'
        assert client.images(cached_image)

        build = factories.BuildFactory.create(
            project=self.project,
            gh_commit_sha=self.head_sha)
        hook_call = factories.HookCallFactory.create(
            hook=self.hook,
            build=build)

        job = self._do_job(hook_call)
        assert job.return_code == 0
        assert job.stdout == ('Skipping install script as tracked files '
                              'did not change...\n\nit works\nYEAH\n')

    def test_public_project(self):
        self.hook.install_script = ''
        self.hook.build_script = 'echo Hello!'
        self.project.is_public = True
        self.db.session.delete(self.project.deploy_key)
        self.db.session.commit()

        build = factories.BuildFactory.create(
            project=self.project,
            gh_commit_sha=self.prev_head_sha)
        hook_call = factories.HookCallFactory.create(
            hook=self.hook,
            build=build)

        job = self._do_job(hook_call)
        assert job.return_code == 0
        assert job.stdout == 'Hello!\n'

    def teardown_method(self, method):
        shutil.rmtree(self.working_dir)
        TestCase.teardown_method(self, method)
