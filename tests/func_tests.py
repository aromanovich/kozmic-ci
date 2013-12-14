# coding: utf-8
import copy

import furl
import mock
import httpretty
import github3.repos
import github3.git
from flask import url_for

import kozmic.builds.tasks
from kozmic.models import User, Project, Hook, HookCall, Build, BuildStep
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
        r = self.w.get('{}?code={}'.format(redirect_uri, code))

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
        assert user.gh_name == fixtures.USER_DATA['name']
        assert user.gh_id == fixtures.USER_DATA['id']
        assert user.gh_login == fixtures.USER_DATA['login']


class TestProjects(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user_1, self.user_2 = factories.UserFactory.create_batch(2)

        self.user_1_project = factories.ProjectFactory.create(owner=self.user_1)

        self.user_2_repo = factories.UserRepositoryFactory.create(parent=self.user_2)
        self.user_2_org = factories.OrganizationFactory.create(user=self.user_2)
        self.user_2_org_repo = \
            factories.OrganizationRepositoryFactory.create(parent=self.user_2_org)

    def test_repos_sync(self):
        """User can sync repositories from GitHub."""
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
        assert (user.organizations.filter_by(gh_login='pyconru')
                    .first().repositories.count() == 1)
        assert (user.organizations.filter_by(gh_login='unistorage')
                    .first().repositories.count() == 6)
        assert user.repos_last_synchronized_at

    def test_project_creation(self):
        """User can create a project from repository."""
        self.login(user_id=self.user_2.id)

        r = self.w.get('/').maybe_follow().click('Repositories')

        form_id = 'org-repo-{}'.format(self.user_2_org_repo.id)

        # Mock GitHub API call to add deploy key and submit the form
        gh_repo_mock = mock.Mock()
        gh_repo_mock.create_key = mock.Mock(
            return_value=github3.users.Key(fixtures.DEPLOY_KEY_DATA))

        with mock.patch.object(Project, 'gh', gh_repo_mock):
            r = r.forms[form_id].submit().follow()

        assert self.user_2.owned_projects.count() == 1
        project = self.user_2.owned_projects.first()
        assert project.gh_id == self.user_2_org_repo.gh_id
        assert project.gh_name == self.user_2_org_repo.gh_name
        assert project.gh_full_name == self.user_2_org_repo.gh_full_name
        assert project.gh_login == self.user_2_org_repo.parent.gh_login
        assert project.gh_key_id == fixtures.DEPLOY_KEY_DATA['id']
        assert project.rsa_public_key.startswith('ssh-rsa ')
        assert project.rsa_private_key.startswith('-----BEGIN RSA PRIVATE KEY-----')


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
            assert hook.build_script in settings_page

    def test_manager_can_add_hook(self):
        """Manager can add a project hook."""
        self.login(user_id=self.user.id)

        settings_page = self.get_project_settings_page(self.project)
        hook_form = settings_page.click('Add a new hook').form

        # Fill the hook creation form
        hook_data = {
            'title': 'Tests on debian-7',
            'build_script': './kozmic.sh',
            'docker_image': 'debian-7',
        }
        for field, value in hook_data.items():
            hook_form[field] = value

        # Mock GitHub API call and submit the form
        gh_repo_mock = mock.Mock()
        gh_repo_mock.create_hook = mock.Mock(
            return_value=github3.repos.hook.Hook(fixtures.HOOK_DATA))

        with mock.patch.object(Project, 'gh', gh_repo_mock):
            hook_form.submit()

        # Ensure that hook has been created with the right data
        assert self.project.hooks.count() == 1
        hook = self.project.hooks.first()
        assert hook.title == hook_data['title']
        assert hook.build_script == hook_data['build_script']
        assert hook.docker_image == hook_data['docker_image']

        # And GitHub API has been called with the right arguments
        assert gh_repo_mock.create_hook.call_count == 1
        args, kwargs = gh_repo_mock.create_hook.call_args
        assert kwargs == {
            'active': True,
            'config': {
                'url': url_for('builds.hook', id=hook.id, _external=True),
                'content_type': 'json',
            },
            'events': ['push', 'pull_request'],
            'name': 'web',
        }

        # Mock GitHub API call to raise an exception and submit the form again
        gh_repo_mock = mock.Mock()
        gh_repo_mock.create_hook.side_effect = self._github_error_side_effect
        with mock.patch.object(Project, 'gh', gh_repo_mock):
            r = hook_form.submit()

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
        hook_form = settings_page.click(linkid=link_id).form
        hook_form['title'] == hook_1.title
        hook_form['title'] = 'PEP 8 check'
        hook_form['build_script'] = 'pep8 app.py'
        hook_form.submit()

        # Ensure the changes are saved
        assert hook_1.title == 'PEP 8 check'
        assert hook_1.build_script == 'pep8 app.py'

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

        self.project.members.extend([self.ramm, self.vsokolov])
        self.db.session.commit()

        settings_page = self.get_project_settings_page(self.project)
        member_divs = settings_page.lxml.cssselect('.members .member')
        assert len(member_divs) == 3
        assert 'aromanovich' in member_divs[0].text_content()
        assert 'ramm' in member_divs[1].text_content()
        assert 'vsokolov' in member_divs[2].text_content()

    def test_manager_can_add_member(self):
        """Manager can add a member to a project."""
        self.login(user_id=self.aromanovich.id)

        assert self.project.members.count() == 0

        member_form = (self.get_project_settings_page(self.project)
                           .click('Add a new member').form)

        member_form['gh_login'] = 'johndoe'
        assert member_form.submit().flashes == [
            ('warning', 'User with GitHub login "johndoe" was not found.')
        ]

        member_form['gh_login'] = 'ramm'
        member_form.submit().follow()
        member_form['gh_login'] = 'vsokolov'
        member_form.submit().follow()

        assert self.project.members.count() == 2

    def test_manager_can_delete_member(self):
        """Manager can delete a project member."""
        self.login(user_id=self.aromanovich.id)

        self.project.members.extend([self.ramm, self.vsokolov])
        self.db.session.commit()

        settings_page = self.get_project_settings_page(self.project)

        form_id = 'delete-member-{}'.format(self.ramm.id)
        settings_page.forms[form_id].submit().follow()

        assert self.ramm not in self.project.members


class TestGitHubHook(TestCase):
    def setup_method(self, method):
        TestCase.setup_method(self, method)

        self.user = factories.UserFactory.create()
        self.project = factories.ProjectFactory.create(owner=self.user)
        self.hook = factories.HookFactory.create(project=self.project)

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

        with mock.patch.object(Project, 'gh', gh_repo_mock):
            with mock.patch('kozmic.builds.tasks.do_build') as do_build_mock:
                r = self.w.post_json(
                    url_for('builds.hook', id=self.hook.id, _external=True),
                    fixtures.PULL_REQUEST_HOOK_CALL_DATA)

        assert r.status_code == 200
        assert r.body == 'Thanks'

        gh_repo_mock.git_commit.assert_called_once_with(head_sha)

        assert self.hook.calls.count() == 1
        assert self.project.builds.count() == 1

        hook_call = self.hook.calls.first()

        build = self.project.builds.first()
        assert self.project.builds.count() == 1
        assert build.status == 'enqueued'
        assert build.number == 1
        assert build.gh_commit_ref == 'test'
        assert build.gh_commit_sha == head_sha
        assert build.gh_commit_message == commit_data['message']
        assert build.gh_commit_author == commit_data['author']['name']

        do_build_mock.delay.assert_called_once_with(
            build_id=build.id, hook_call_id=hook_call.id)

    def test_consecutive_hook_calls(self):
        commit_data = fixtures.COMMIT_47fe2_DATA
        gh_repo_mock = self._create_gh_repo_mock(commit_data)
        head_sha = commit_data['sha']

        with mock.patch.object(Project, 'gh', gh_repo_mock):
            push_hook_call_data = copy.deepcopy(fixtures.PUSH_HOOK_CALL_DATA)
            push_hook_call_data['ref'] = 'refs/heads/{}'.format(
                fixtures.PULL_REQUEST_HOOK_CALL_DATA['pull_request']['head']['ref'])

            with mock.patch('kozmic.builds.tasks.do_build') as do_build_mock:
                r = self.w.post_json(
                    url_for('builds.hook', id=self.hook.id, _external=True),
                    push_hook_call_data)
                r = self.w.post_json(
                    url_for('builds.hook', id=self.hook.id, _external=True),
                    fixtures.PULL_REQUEST_HOOK_CALL_DATA)

        build = self.project.builds.first()
        hook_call = self.hook.calls.first()

        assert self.project.builds.count() == 1
        assert self.hook.calls.count() == 1
        assert build.number == 1  # Make sure that second hook call hasn't
                                  # increased build number
        # And `do_build` was called only once
        do_build_mock.delay.assert_called_once_with(
            build_id=build.id, hook_call_id=hook_call.id)
