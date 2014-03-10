# coding: utf-8
import copy
import datetime as dt

import furl
import mock
import httpretty
import github3.repos
import github3.git
from flask import url_for

import kozmic.builds.tasks
from kozmic.models import (User, DeployKey, Project, Membership, Hook,
                           HookCall, Build, Job, TrackedFile)
from . import TestCase, func_fixtures as fixtures
from . import factories, unit_tests


class TestUsers(TestCase):
    @httpretty.httprettified
    def test_github_sign_up(self):
        """User can sign up with GitHub."""
        assert User.query.count() == 0

        # Visit home page, follow the redirect, click sign up link
        r = self.w.get('/').maybe_follow().click('Sign up with GitHub')

        # Make sure that user is being redirected to GitHub and
        # location has right arguments
        assert r.status_code == 302
        location = furl.furl(r.headers['Location'])
        redirect_uri = location.args['redirect_uri']
        assert redirect_uri == url_for('auth.auth_callback')
        assert location.host == 'github.com'
        assert location.args['scope'] == 'repo'
        # ...now user supposed to go to GitHub and allow access to his repos.
        # Then GitHub will redirect him back to `redirect_uri` with
        # temporary `code`. `redirect_uri` will exchange that `code` for
        # `access_token` using https://github.com/login/oauth/access_token
        # endpoint.

        # Temporary code:
        code = '50ebfe0d4e52301fc157'
        # Access token:
        access_token = '526069daaa72e78b11c2c17bfe085783e765d77b'

        # Mock exchange GitHub endpoint to make it always return
        # our `access_token`
        httpretty.register_uri(
            httpretty.GET, 'https://github.com/login/oauth/access_token',
            'access_token={}&scope=repo&token_type=bearer'.format(access_token))
        # Mock user API call to return some valid JSON
        httpretty.register_uri(
            httpretty.GET, 'https://api.github.com/user', fixtures.USER_JSON)

        # Visit our `redirect_uri` (pretending being GitHub)
        with mock.patch.object(User, 'sync_memberships_with_github') as sync_mock:
            r = self.w.get('{}?code={}'.format(redirect_uri, code))
        sync_mock.assert_called_once_with()

        latest_requests = httpretty.httpretty.latest_requests

        assert len(latest_requests) == 2
        access_token_request, user_api_request = latest_requests

        # Make sure that `redirect_uri` has tried to exchange it's temporary
        # code to access token by hitting /login/oauth/access_token endpoint
        access_token_request_args = dict(furl.furl(access_token_request.path).args)
        assert access_token_request_args['code'] == code
        assert access_token_request_args['redirect_uri'] == redirect_uri

        # And has succeeded
        assert (user_api_request.headers['Authorization'] ==
                'token {}'.format(access_token))

        assert User.query.count() == 1
        user = User.query.first()
        assert user.gh_access_token == access_token
        assert user.email == fixtures.USER_DATA['email']
        assert user.gh_name == fixtures.USER_DATA['name']
        assert user.gh_id == fixtures.USER_DATA['id']
        assert user.gh_login == fixtures.USER_DATA['login']


class TestProjects(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user_1, self.user_2 = factories.UserFactory.create_batch(2)

        self.user_1_project = factories.ProjectFactory.create(owner=self.user_1)

        self.user_2_repo = factories.UserRepositoryFactory.create(
            parent=self.user_2, is_public=True)
        self.user_2_org = factories.OrganizationFactory.create(user=self.user_2)
        self.user_2_org_repo = factories.OrganizationRepositoryFactory.create(
            parent=self.user_2_org)

    def test_projects_sync(self):
        """User can sync projects with GitHub."""
        self.login(user_id=self.user_1.id)
        with mock.patch.object(User, 'sync_memberships_with_github') as sync_mock:
            self.w.get('/').maybe_follow().forms['sync-user-memberships'].submit()
        sync_mock.assert_called_once_with()

    def test_repos_sync_and_view(self):
        """User can sync and view repositories from GitHub."""
        user = self.user_1
        self.login(user_id=user.id)

        # Replace User `get_gh_org_repos` and `get_gh_repos` methods with
        # stubs that don't hit GitHub API
        get_gh_org_repos_stub = unit_tests.TestUser.get_stub_for__get_gh_org_repos()
        get_gh_repos_stub = unit_tests.TestUser.get_stub_for__get_gh_repos()
        with mock.patch.object(User, 'get_gh_org_repos', get_gh_org_repos_stub):
            with mock.patch.object(User, 'get_gh_repos', get_gh_repos_stub):
                r = self.w.get(url_for('repos.sync'))

        # Make sure that database reflects data provided by the stubs
        assert user.repositories.count() == 3
        assert user.organizations.count() == 2
        assert (set(org.gh_login for org in user.organizations) ==
                {'pyconru', 'unistorage'})
        pyconru_repos = user.organizations.filter_by(
            gh_login='pyconru').first().repositories
        unistorage_repos = user.organizations.filter_by(
            gh_login='unistorage').first().repositories
        assert pyconru_repos.count() == 1
        assert unistorage_repos.count() == 6
        assert unistorage_repos.filter_by(is_public=True).count() == 4
        assert user.repos_last_synchronized_at

        # Make sure that all the repositories are listed
        data = self.w.get('/repositories/').context['repositories_by_owner']

        assert set(data[user.gh_login]) == {
            (repo.gh_id, repo.gh_full_name) for repo in user.repositories
        }
        assert set(data['pyconru']) == {
            (repo.gh_id, repo.gh_full_name) for repo in pyconru_repos
        }
        assert set(data['unistorage']) == {
            (repo.gh_id, repo.gh_full_name) for repo in unistorage_repos
        }

        # Create projects for some of the repositories
        project_1 = factories.ProjectFactory.create(
            owner=self.user_1,
            gh_id=user.repositories[1].gh_id)
        project_2 = factories.ProjectFactory.create(
            owner=self.user_2,
            gh_id=pyconru_repos[0].gh_id)
        project_3 = factories.ProjectFactory.create(
            owner=self.user_1,
            gh_id=unistorage_repos[3].gh_id)

        # And make sure that repositories for which projects were
        # created are not listed
        data = self.w.get('/repositories/').context['repositories_by_owner']

        assert 'pyconru' not in data
        assert set(data[user.gh_login]) == {
            (repo.gh_id, repo.gh_full_name) for repo in user.repositories
            if repo.gh_id != project_1.gh_id
        }
        assert set(data['unistorage']) == {
            (repo.gh_id, repo.gh_full_name) for repo in unistorage_repos
            if repo.gh_id != project_3.gh_id
        }

    def test_project_creation(self):
        """User can create a project from repository."""
        self.login(user_id=self.user_2.id)

        r = self.w.get('/').maybe_follow().click('New Project')

        def ensure_stub(self):
            self.gh_id = 123
            return True
        with mock.patch.object(Project, 'sync_memberships_with_github') as sync_mock, \
             mock.patch.object(DeployKey, 'ensure', side_effect=ensure_stub,
                               autospec=True) as ensure_deploy_key_mock:
                form_id = 'create-project-{}'.format(self.user_2_org_repo.gh_id)
                r.forms[form_id].submit().follow()
        # The repository is private, make sure a deploy key was created
        ensure_deploy_key_mock.assert_called_once_with(mock.ANY)
        sync_mock.assert_called_once_with()

        assert self.user_2.owned_projects.count() == 1
        project = self.user_2.owned_projects.filter_by(
            gh_id=self.user_2_org_repo.gh_id).first()
        assert project.deploy_key
        assert not project.is_public
        assert project.gh_id == self.user_2_org_repo.gh_id
        assert project.gh_name == self.user_2_org_repo.gh_name
        assert project.gh_full_name == self.user_2_org_repo.gh_full_name
        assert project.gh_login == self.user_2_org_repo.parent.gh_login
        assert project.deploy_key.rsa_public_key.startswith('ssh-rsa ')
        assert project.deploy_key.rsa_private_key.startswith(
            '-----BEGIN RSA PRIVATE KEY-----')

        with mock.patch.object(Project, 'sync_memberships_with_github') as sync_mock, \
             mock.patch.object(DeployKey, 'ensure') as ensure_deploy_key_mock:
                form_id = 'create-project-{}'.format(self.user_2_repo.gh_id)
                r.forms[form_id].submit().follow()
        # The repository is public, make sure a deploy key wasn't created
        assert not ensure_deploy_key_mock.called
        sync_mock.assert_called_once_with()

        assert self.user_2.owned_projects.count() == 2
        project = self.user_2.owned_projects.filter_by(
            gh_id=self.user_2_repo.gh_id).first()
        assert not project.deploy_key
        assert project.is_public

    def test_project_deletion(self):
        """User can delete an owned project."""
        project = factories.ProjectFactory.create(owner=self.user_1)
        project_id = project.id
        factories.MembershipFactory.create(user=self.user_2, project=project)

        def get_settings_page(project):
            return self.w.get('/').maybe_follow().click(
                project.gh_full_name).maybe_follow().click('Settings')

        self.login(user_id=self.user_2.id)
        r = get_settings_page(project)
        assert 'delete-project' not in r.forms
        with mock.patch('flask.ext.wtf.csrf.validate_csrf', return_value=True):
            r = self.w.post(
                url_for('projects.delete_project', id=project.id), status='*')
            assert r.status_code == 403

        self.login(user_id=self.user_1.id)
        r = get_settings_page(project)
        form = r.forms['delete-project']
        # Imitate JS logic:
        form.action = url_for(
            'projects.delete_project', id=project.id, _external=False)
        assert form.action in r

        with mock.patch.object(Project, 'gh'):
            form.submit().follow()

        assert not Project.query.get(project_id)


class TestHooksManagement(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(owner=self.user)

    @staticmethod
    def _github_error_side_effect(*args, **kwargs):
        raise github3.GitHubError(mock.Mock())

    def get_project_settings_page(self, project):
        return (self.w.get('/').maybe_follow()
                      .click(project.gh_full_name).maybe_follow()
                      .click('Settings'))

    def test_manager_can_see_hooks(self):
        """Manager can see project hooks."""
        self.login(user_id=self.user.id)

        # See no hooks configured
        settings_page = self.get_project_settings_page(self.project)
        assert 'Hooks haven\'t been configured yet.' in settings_page

        # Add some hooks
        hooks = factories.HookFactory.create_batch(3, project=self.project)

        # See all the hooks configured
        settings_page = self.get_project_settings_page(self.project)
        assert 'Hooks haven\'t been configured yet.' not in settings_page
        for hook in hooks:
            assert hook.title in settings_page

    def test_manager_can_add_hook(self):
        """Manager can add a project hook."""
        self.login(user_id=self.user.id)

        settings_page = self.get_project_settings_page(self.project)
        hook_form = settings_page.click('Add a new hook').forms['hook-form']

        # Fill the hook creation form
        hook_data = {
            'title': 'Tests on debian-7',
            'install_script': '#!/bin/bash\r\necho 123 > /test.txt',
            'build_script': '#!/bin/bash\r\n./kozmic.sh',
            'docker_image': 'debian-7',
        }
        for field, value in hook_data.items():
            hook_form[field] = value

        with mock.patch.object(Hook, 'ensure', return_value=True) as ensure_mock:
            r = hook_form.submit().follow()

        ensure_mock.assert_called_once_with()

        # Ensure that hook has been created with the right data
        assert self.project.hooks.count() == 1
        hook = self.project.hooks.first()
        assert hook.title == hook_data['title']
        assert hook.install_script == '#!/bin/bash\necho 123 > /test.txt'
        assert hook.build_script == '#!/bin/bash\n./kozmic.sh'
        assert hook.docker_image == hook_data['docker_image']

        # Pretend that there was a GitHub error
        with mock.patch.object(Hook, 'ensure', return_value=False) as ensure_mock:
            r = hook_form.submit()

        ensure_mock.assert_called_once_with()

        # Make sure that user gets the warning
        assert r.flashes == [
            ('warning', 'Sorry, failed to create a hook. Please try again later.')
        ]

    def test_manager_can_edit_hook(self):
        """Manager can edit a project hook."""
        hooks = factories.HookFactory.create_batch(3, project=self.project)
        hook_1 = hooks[1]

        self.login(user_id=self.user.id)
        settings_page = self.get_project_settings_page(self.project)

        # Fill the hook form
        link_id = 'edit-hook-{}'.format(hook_1.id)
        hook_form = settings_page.click(linkid=link_id).forms['hook-form']
        hook_form['title'] == hook_1.title
        hook_form['title'] = 'PEP 8 check'
        hook_form['build_script'] = '#!/bin/sh\r\npep8 app.py'
        hook_form.submit()

        # Ensure the changes are saved
        assert hook_1.title == 'PEP 8 check'
        assert hook_1.build_script == '#!/bin/sh\npep8 app.py'

        # Trying to submit form without required field
        hook_form['title'] = ''
        assert 'This field is required' in hook_form.submit()

    def test_manager_can_delete_hook(self):
        """Manager can delete a project hook."""
        hooks = factories.HookFactory.create_batch(3, project=self.project)
        hook_1, hook_2, _ = hooks

        self.login(user_id=self.user.id)
        settings_page = self.get_project_settings_page(self.project)

        hook_1_deletion_form = settings_page.forms[
            'delete-hook-{}'.format(hook_1.id)]
        hook_2_deletion_form = settings_page.forms[
            'delete-hook-{}'.format(hook_2.id)]

        # Case 1:
        # Mock hook.delete() to raise GitHubError
        gh_repo_mock = mock.Mock()
        gh_hook_mock = gh_repo_mock.hook.return_value
        gh_hook_mock.delete.side_effect = self._github_error_side_effect
        with mock.patch.object(Project, 'gh', gh_repo_mock):
            hook_1_deletion_form.submit().follow()
        # Ensure that `hook_1` is still there
        assert hook_1 in self.project.hooks

        # Case 2:
        # Mock gh.hook() to return None (suppose user deleted hook manually
        # using GitHub settings)
        gh_repo_mock = mock.Mock()
        gh_repo_mock.hook.return_value = None
        with mock.patch.object(Project, 'gh', gh_repo_mock):
            hook_1_deletion_form.submit().follow()
        # In that case hook must be deleted from db
        assert hook_1 not in self.project.hooks

        # Case 3:
        # Regular situation: `gh_repo.hook()` returns gh_hook,
        # `gh_hook.delete()` call is successful
        gh_repo_mock = mock.Mock()
        gh_hook_mock = gh_repo_mock.hook.return_value
        with mock.patch.object(Project, 'gh', gh_repo_mock):
            hook_2_deletion_form.submit().follow()
        # Ensure that hook is deleted...
        assert hook_2 not in self.project.hooks
        # ...the view called `.hook(id)` to get the GitHub hook
        gh_repo_mock.hook.assert_called_once_with(hook_2.gh_id)
        # ...and then called `delete` on it
        gh_hook_mock.delete.assert_called_once_with()

    def test_manager_can_change_tracked_files_in_hook_settings(self):
        """Manager can change the traked files."""
        hook = factories.HookFactory.create(project=self.project)
        self.login(user_id=self.user.id)
        settings_page = self.get_project_settings_page(self.project)
        link_id = 'edit-hook-{}'.format(hook.id)

        hook_form = settings_page.click(linkid=link_id).forms['hook-form']
        hook_form['tracked_files'] = ''
        hook_form.submit()

        assert not hook.tracked_files.all()

        hook_form = settings_page.click(linkid=link_id).forms['hook-form']
        hook_form['tracked_files'] = ('./requirements/basic.txt\n'
                                      'requirements/basic.txt\n'
                                      '././a/../requirements/dev.txt')
        hook_form.submit()

        assert set(tracked_file.path for tracked_file in hook.tracked_files) == {
            'requirements/basic.txt',
            'requirements/dev.txt',
        }

        hook_form = settings_page.click(linkid=link_id).forms['hook-form']
        assert set(hook_form['tracked_files'].value.splitlines()) == {
            'requirements/basic.txt',
            'requirements/dev.txt',
        }
        hook_form['tracked_files'] = (hook_form['tracked_files'].value +
                                      '\nPumpurum.txt\npumpurum.txt')
        hook_form.submit()

        assert set(tracked_file.path for tracked_file in hook.tracked_files) == {
            'requirements/basic.txt',
            'requirements/dev.txt',
            'pumpurum.txt',
            'Pumpurum.txt',
        }


class TestMembersManagement(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.aromanovich = factories.UserFactory.create(
            gh_login='aromanovich', gh_name='Anton')
        self.ramm = factories.UserFactory.create(
            gh_login='ramm', gh_name='Danila')
        self.vsokolov = factories.UserFactory.create(
            gh_login='vsokolov', gh_name='Victor')

        self.project = factories.ProjectFactory.create(owner=self.aromanovich)

    def get_project_settings_page(self, project):
        return (self.w.get('/').maybe_follow()
                      .click(project.gh_full_name).maybe_follow()
                      .click('Settings'))

    def test_manager_can_see_members(self):
        """Manager can see project members."""
        self.login(user_id=self.aromanovich.id)

        settings_page = self.get_project_settings_page(self.project)
        member_divs = settings_page.lxml.cssselect('.members .member')
        assert len(member_divs) == 1
        assert 'aromanovich' in member_divs[0].text_content()

        for user in [self.ramm, self.vsokolov]:
            factories.MembershipFactory.create(user=user, project=self.project)

        settings_page = self.get_project_settings_page(self.project)
        member_divs = settings_page.lxml.cssselect('.members .member')
        assert len(member_divs) == 3
        assert 'aromanovich' in member_divs[0].text_content()
        assert 'ramm' in member_divs[1].text_content()
        assert 'vsokolov' in member_divs[2].text_content()

    def test_manager_can_sync_members_with_github(self):
        """Manager can sync members with GitHub."""
        factories.MembershipFactory.create(
            user=self.vsokolov, project=self.project)
        factories.MembershipFactory.create(
            user=self.ramm, project=self.project, allows_management=True)

        self.login(user_id=self.vsokolov.id)
        settings_page = self.get_project_settings_page(self.project)
        assert 'sync-project-memberships' not in settings_page.forms

        self.login(user_id=self.ramm.id)
        settings_page = self.get_project_settings_page(self.project)
        with mock.patch.object(Project, 'sync_memberships_with_github') as sync_mock:
            settings_page.forms['sync-project-memberships'].submit()
        sync_mock.assert_called_once_with()


class TestGitHubHooks(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(owner=self.user)
        self.hook_1 = factories.HookFactory.create(project=self.project)
        self.hook_2 = factories.HookFactory.create(project=self.project)

    def _create_gh_repo_mock(self, commit_data):
        gh_repo_mock = mock.Mock()
        gh_repo_mock.git_commit.return_value = github3.git.Commit(commit_data)
        assert (fixtures.PULL_REQUEST_HOOK_CALL_DATA['pull_request']['head']['sha'] ==
                commit_data['sha'])
        return gh_repo_mock

    def test_github_pull_request_hook(self):
        commit_data = fixtures.COMMIT_47fe2_DATA
        gh_repo_mock = self._create_gh_repo_mock(commit_data)
        head_sha = commit_data['sha']

        with mock.patch.object(Project, 'gh', gh_repo_mock), \
             mock.patch('kozmic.builds.tasks.do_job') as do_job_mock:
            r = self.w.post_json(
                url_for('builds.hook', id=self.hook_1.id, _external=True),
                fixtures.PULL_REQUEST_HOOK_CALL_DATA)

        assert r.status_code == 200
        assert r.body == 'OK'

        gh_repo_mock.git_commit.assert_called_once_with(head_sha)

        assert self.hook_1.calls.count() == 1
        assert self.project.builds.count() == 1

        hook_call = self.hook_1.calls.first()

        build = self.project.builds.first()
        assert self.project.builds.count() == 1
        assert build.status == 'enqueued'
        assert build.number == 1
        assert build.gh_commit_ref == 'test'
        assert build.gh_commit_sha == head_sha
        assert build.gh_commit_message == commit_data['message']
        assert build.gh_commit_author == commit_data['author']['name']

        do_job_mock.delay.assert_called_once_with(hook_call_id=hook_call.id)

    def test_github_ping_event(self):
        with mock.patch.object(Project, 'gh'), \
             mock.patch('kozmic.builds.tasks.do_job') as do_job_mock:
            url = url_for('builds.hook', id=self.hook_1.id, _external=True)
            r = self.w.post_json(url, {
                'zen': 'Hello!',
                'hook_id': self.hook_1.gh_id
            })
            assert r.body == 'OK'

            r = self.w.post_json(url, {
                'zen': 'Hello!',
                'hook_id': self.hook_1.gh_id + 123
            }, expect_errors=True)
            assert r.body == 'Wrong hook URL'

    def test_consecutive_hook_calls(self):
        commit_data = fixtures.COMMIT_47fe2_DATA
        gh_repo_mock = self._create_gh_repo_mock(commit_data)
        head_sha = commit_data['sha']

        with mock.patch.object(Project, 'gh', gh_repo_mock), \
             mock.patch('kozmic.builds.tasks.do_job') as do_job_mock:
            push_hook_call_data = copy.deepcopy(fixtures.PUSH_HOOK_CALL_DATA)
            push_hook_call_data['ref'] = 'refs/heads/{}'.format(
                fixtures.PULL_REQUEST_HOOK_CALL_DATA['pull_request']['head']['ref'])

            for hook in (self.hook_1, self.hook_2):
                self.w.post_json(
                    url_for('builds.hook', id=hook.id, _external=True),
                    push_hook_call_data)
            self.w.post_json(
                url_for('builds.hook', id=self.hook_1.id, _external=True),
                fixtures.PULL_REQUEST_HOOK_CALL_DATA)

        build = self.project.builds.first()
        hook_call_1 = self.hook_1.calls.first()
        hook_call_2 = self.hook_2.calls.first()

        assert self.project.builds.count() == 1
        assert self.hook_1.calls.count() == 1
        assert self.hook_2.calls.count() == 1
        assert build.number == 1  # Make sure that second hook call hasn't
                                  # increased build number
        assert do_job_mock.delay.call_count == 2
        assert mock.call(hook_call_id=hook_call_1.id) in do_job_mock.delay.call_args_list
        assert mock.call(hook_call_id=hook_call_2.id) in do_job_mock.delay.call_args_list


class TestBadges(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(
            owner=self.user,
            gh_login='aromanovich',
            gh_name='flask-webtest')

    def test_basics(self):
        r = self.w.get('/badges/aromanovich/flask-webtest/master')
        assert r.status_code == 307
        assert r.location == 'https://kozmic.test/static/img/badges/success.png'

        self.build = factories.BuildFactory.create(
            project=self.project,
            status='failure',
            gh_commit_ref='feature-branch')

        # master branch is still "success"
        r = self.w.get('/badges/aromanovich/flask-webtest/master')
        assert r.status_code == 307
        assert r.location == 'https://kozmic.test/static/img/badges/success.png'

        # feature-branch is "failure"
        r = self.w.get('/badges/aromanovich/flask-webtest/feature-branch')
        assert r.status_code == 307
        assert r.location == 'https://kozmic.test/static/img/badges/failure.png'


class TestBuilds(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(owner=self.user)
        self.build = factories.BuildFactory.create(project=self.project)
        self.hook = factories.HookFactory.create(project=self.project)
        self.hook_call = factories.HookCallFactory.create(
            hook=self.hook, build=self.build)

    def test_basics(self):
        self.job = factories.JobFactory.create(
            build=self.build,
            hook_call=self.hook_call,
            started_at=dt.datetime.utcnow() - dt.timedelta(minutes=2),
            finished_at=dt.datetime.utcnow(),
            stdout='[4mHello![24m')

        self.login(user_id=self.user.id)
        r = self.w.get(url_for('projects.build', project_id=self.project.id,
                               id=self.build.id))
        assert '<span class="ansi4">Hello!</span>' in r

    def test_restart(self):
        job = factories.JobFactory.create(
            build=self.build,
            hook_call=self.hook_call,
            started_at=dt.datetime.utcnow() - dt.timedelta(minutes=2),
            finished_at=dt.datetime.utcnow(),
            stdout='[4mHello![24m')
        job.build.status = 'success'
        self.db.session.commit()
        assert job.is_finished()

        self.login(user_id=self.user.id)
        r = self.w.get(url_for('projects.build', project_id=self.project.id,
                               id=self.build.id))
        with mock.patch('kozmic.projects.views.restart_job') as restart_job_mock:
            r.click('Restart').follow()
        restart_job_mock.delay.assert_called_once_with(job.id)
        assert job.build.status == 'enqueued'
