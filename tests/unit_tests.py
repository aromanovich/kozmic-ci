# coding: utf-8
import os
import time
import unittest
import tempfile
import subprocess

import httpretty
import pytest
import redis
import mock
from Crypto.PublicKey import RSA
from flask import current_app
from flask.ext.principal import Need
from flask.ext.webtest import SessionScope

import kozmic.builds.tasks
import kozmic.builds.views
from kozmic.models import db, User, Project, Build
from . import TestCase, factories, unit_fixtures as fixtures, func_fixtures


class TestUser(unittest.TestCase):
    @staticmethod
    @httpretty.httprettified
    def get_stub_for__get_gh_org_repos():
        """Returns a stub for :meth:`User.get_gh_org_repos`."""

        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/user/teams',
            fixtures.TEAMS_JSON)

        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/teams/267031/repos',
            fixtures.TEAM_267031_JSON)

        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/teams/297965/repos',
            fixtures.TEAM_297965_JSON)

        rv = User(gh_access_token='123').get_gh_org_repos()
        return mock.Mock(return_value=rv)

    @staticmethod
    @httpretty.httprettified
    def get_stub_for__get_gh_repos():
        """Returns a stub for :meth:`User.get_gh_repos`."""

        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/user/repos',
            fixtures.USER_REPOS_JSON)

        rv = User(gh_access_token='123').get_gh_repos()
        return mock.Mock(return_value=rv)

    def test_get_gh_org_repos(self):
        stub = self.get_stub_for__get_gh_org_repos()
        gh_orgs, gh_repos_by_org_id = stub.return_value

        assert len(gh_orgs) == 2
        pyconru_org, unistorage_org = \
            sorted(gh_orgs, key=lambda gh_org: gh_org.login)
        assert len(gh_repos_by_org_id[pyconru_org.id]) == 1
        assert len(gh_repos_by_org_id[unistorage_org.id]) == 6

    def test_get_gh_repos(self):
        stub = self.get_stub_for__get_gh_repos()
        assert len(stub.return_value) == 3


class TestUserDB(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user_1, self.user_2, self.user_3, self.user_4 = \
            factories.UserFactory.create_batch(4)

        factories.ProjectFactory.create_batch(3, owner=self.user_1)
        factories.ProjectFactory.create_batch(2, owner=self.user_2)
        factories.ProjectFactory.create_batch(1, owner=self.user_3)

        self.project_1, self.project_2, self.project_3, = self.user_1.owned_projects
        self.project_4, self.project_5 = self.user_2.owned_projects

        self.projects = {self.project_1, self.project_2, self.project_3,
                         self.project_4, self.project_5}

        self.user_1.projects.extend([self.project_4, self.project_5])
        db.session.commit()

    def test_get_available_projects(self):
        factories.BuildFactory.create_batch(5, project=self.project_1)
        factories.BuildFactory.create_batch(5, project=self.project_2)
        factories.BuildFactory.create_batch(3, project=self.project_4)

        rv = self.user_1.get_available_projects()
        assert set(rv) == self.projects

        rv = self.user_1.get_available_projects(annotate_with_latest_builds=True)
        assert set(rv) == {(self.project_1, self.project_1.latest_build),
                           (self.project_2, self.project_2.latest_build),
                           (self.project_3, None),
                           (self.project_4, self.project_4.latest_build),
                           (self.project_5, None)}

        assert set(self.user_2.get_available_projects()) == \
            {self.project_4, self.project_5}
        assert not self.user_4.get_available_projects()

    def test_get_identity(self):
        self.user_1.projects.extend([self.project_4, self.project_5])
        db.session.commit()

        identity = self.user_1.get_identity()
        assert identity.provides == {
            Need(method='project_owner', value=self.project_1.id),
            Need(method='project_owner', value=self.project_2.id),
            Need(method='project_owner', value=self.project_3.id),
            Need(method='project_manager', value=self.project_4.id),
            Need(method='project_manager', value=self.project_5.id),
        }

        identity = self.user_2.get_identity()
        assert identity.provides == {
            Need(method='project_owner', value=self.project_4.id),
            Need(method='project_owner', value=self.project_5.id),
        }

        identity = self.user_4.get_identity()
        assert not identity.provides


class TestBuildDB(TestCase):
    def test_get_ref_and_sha(self):
        get_ref_and_sha = kozmic.builds.views.get_ref_and_sha
        assert (get_ref_and_sha(func_fixtures.PULL_REQUEST_HOOK_CALL_DATA) ==
                (u'test', u'47fe2c74f6d46304830ed46afd59a53401b20b78'))
        assert (get_ref_and_sha(func_fixtures.PUSH_HOOK_CALL_DATA) ==
                (u'master', u'47fe2c74f6d46304830ed46afd59a53401b20b78'))

    def test_calculate_number(self):
        user = factories.UserFactory.create()
        project = factories.ProjectFactory.create(owner=user)

        build_1 = Build(
            project=project,
            gh_commit_sha='a' * 40,
            gh_commit_author='aromanovich',
            gh_commit_message='ok',
            gh_commit_ref='master',
            status='enqueued')
        build_1.calculate_number()
        db.session.add(build_1)
        db.session.commit()

        build_2 = Build(
            project=project,
            gh_commit_sha='b' * 40,
            gh_commit_author='aromanovich',
            gh_commit_message='ok',
            gh_commit_ref='master',
            status='enqueued')
        build_2.calculate_number()
        db.session.add(build_2)
        db.session.commit()

        assert build_1.number == 1
        assert build_2.number == 2


class TestHookDB(TestCase):
    def test_delete_cascade(self):
        """Tests that hook calls are preserved on hook delete."""
        user = factories.UserFactory.create()
        project = factories.ProjectFactory.create(owner=user)
        hook = factories.HookFactory.create(project=project)
        hook_calls = factories.HookCallFactory.create_batch(3, hook=hook)

        for hook_call in hook_calls:
            assert hook_call.hook_id == hook.id

        db.session.delete(hook)
        db.session.commit()

        for hook_call in hook_calls:
            assert hook_call.hook_id is None


KOZMIC_BLUES = '''
Time keeps movin' on,
Friends they turn away.
I keep movin' on
But I never found out why
I keep pushing so hard the dream,
I keep tryin' to make it right
Through another lonely day, whoaa.
'''.strip()


class TestTailer(TestCase):
    def test_tailer(self):
        config = current_app.config
        redis_client = redis.StrictRedis(host=config['KOZMIC_REDIS_HOST'],
                                         port=config['KOZMIC_REDIS_PORT'],
                                         db=config['KOZMIC_REDIS_DATABASE'])
        redis_client.delete('test')
        channel = redis_client.pubsub()
        channel.subscribe('test')
        listener = channel.listen()

        with tempfile.NamedTemporaryFile(mode='a+b') as f:
            tailer = kozmic.builds.tasks.Tailer(f.name, redis_client, 'test')
            tailer.start()
            time.sleep(.5)

            # Skip "subscribe" message that looks like this:
            # {'channel': 'test', 'data': 1L, 'pattern': None, 'type': 'subscribe'}
            listener.next()

            for line in KOZMIC_BLUES.split('\n'):
                f.write(line + '\n')
                f.flush()
                assert listener.next()['data'] == line + '\n'

        time.sleep(.5)
        assert KOZMIC_BLUES + '\n' == ''.join(redis_client.lrange('test', 0, -1))


CREATE_TEST_REPO_SH = '''
git init {repo_dir}
cd {repo_dir}
git config user.email "author@example.com>"
git config user.name "A U Thore"
echo "echo Hello!" > ./kozmic.sh
git add ./kozmic.sh
git commit -m "Initial commit"
'''


@pytest.mark.docker
class TestBuilder(TestCase):
    def _init_repo(self, repo_dir):
        subprocess.call(
            CREATE_TEST_REPO_SH.format(repo_dir=repo_dir), shell=True)
        return subprocess.check_output(
            'cd {} && git rev-parse HEAD'.format(repo_dir),
            shell=True
        ).strip()

    def _generate_private_key(self, passphrase):
        rsa_key = RSA.generate(1024)
        return rsa_key.exportKey(format='PEM', passphrase=passphrase)

    def test_builder(self):
        passphrase = 'passphrase'
        private_key = self._generate_private_key(passphrase)

        with kozmic.builds.tasks.create_temp_dir() as build_dir:
            sha = self._init_repo(os.path.join(build_dir, 'test-repo'))

            builder = kozmic.builds.tasks.Builder(
                rsa_private_key=private_key,
                passphrase=passphrase,
                docker_image='aromanovich/ubuntu-kozmic',
                shell_code='bash ./kozmic.sh',
                build_dir=build_dir,
                clone_url='/kozmic/test-repo',
                sha=sha)
            builder.run()

            log_path = os.path.join(build_dir, 'build.log')
            with open(log_path, 'r') as log:
                stdout = log.read().strip()

        assert builder.return_code == 0
        assert stdout == 'Hello!'

    def test_builder_with_wrong_passphrase(self):
        """Tests that Builder does not hang being called
        with a wrong passphrase.
        """
        with kozmic.builds.tasks.create_temp_dir() as build_dir:
            sha = self._init_repo(os.path.join(build_dir, 'test-repo'))

            builder = kozmic.builds.tasks.Builder(
                rsa_private_key=self._generate_private_key('passphrase'),
                passphrase='wrong-passphrase',
                docker_image='aromanovich/ubuntu-kozmic',
                shell_code='bash ./kozmic.sh',
                build_dir=build_dir,
                clone_url='/kozmic/test-repo',
                sha=sha)
            builder.run()

        assert builder.return_code == 1


class BuilderStub(kozmic.builds.tasks.Builder):
    def run(self):
        time.sleep(1)

        build_log_path = os.path.join(self._build_dir, 'build.log')
        with open(build_log_path, 'w') as build_log:
            build_log.write('Everything went great!\nGood bye.')

        self.return_code = 0


class TestBuildTask(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(owner=self.user)
        self.hook = factories.HookFactory.create(project=self.project)
        self.hook_call = factories.HookCallFactory.create(hook=self.hook)
        self.build = factories.BuildFactory.create(project=self.project)

    def test_do_build(self):
        with SessionScope(self.db):
            set_status_patcher = mock.patch.object(Build, 'set_status')
            builder_patcher = mock.patch('kozmic.builds.tasks.Builder', new=BuilderStub)
            tailer_patcher = mock.patch('kozmic.builds.tasks.Tailer')

            set_status_mock = set_status_patcher.start()
            builder_patcher.start()
            tailer_patcher.start()
            try:
                kozmic.builds.tasks.do_build(build_id=self.build.id,
                                             hook_call_id=self.hook_call.id)
            finally:
                tailer_patcher.stop()
                builder_patcher.stop()
                set_status_patcher.stop()
        self.db.session.rollback()

        assert self.build.steps.count() == 1
        build_step = self.build.steps.first()
        assert build_step.return_code == 0
        assert build_step.stdout == 'Everything went great!\nGood bye.'
        build_id = self.build.id
        set_status_mock.assert_has_calls([
            mock.call(
                'pending',
                description='Kozmic build #{} is pending.'.format(build_id)),
            mock.call(
                'success',
                description='Kozmic build #{} has passed.'.format(build_id)),
        ])
