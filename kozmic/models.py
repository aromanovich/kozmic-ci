# coding: utf-8
"""
kozmic.models
~~~~~~~~~~~~~
"""
import itertools
import datetime
import collections
import hashlib
import os.path
import logging

import github3
import sqlalchemy.dialects.mysql
import flask
from Crypto.PublicKey import RSA
from flask.ext.login import UserMixin
from flask.ext.principal import Identity, RoleNeed, UserNeed
from flask.ext.mail import Message
from werkzeug.utils import cached_property
from sqlalchemy.ext.declarative import declared_attr

from . import db, mail, perms, docker_utils
from .utils import JSONEncodedDict


logger = logging.getLogger(__name__)


MISSING_ID = -1


# TODO Remove when
# https://github.com/sigmavirus24/github3.py/commit/35b1f015f526ea881b804076fb111ffc025b2392
# will be on PyPI
def iter_collaborators(self, number=-1, etag=None):
    url = self._build_url('collaborators', base_url=self._api)
    return self._iter(int(number), url, github3.users.User, {}, etag)

github3.repos.Repository.iter_collaborators = iter_collaborators
# /TODO


class RepositoryBase(object):
    """A base repository class to be used by :class:`HasRepositories` mixin."""
    id = db.Column(db.Integer, primary_key=True)

    #: GitHub id
    gh_id = db.Column(db.Integer, nullable=False)
    #: GitHub name (i.e., kozmic)
    gh_name = db.Column(db.String(200), nullable=False)
    #: GitHub full name (i.e., aromanovich/kozmic)
    gh_full_name = db.Column(db.String(200), nullable=False)
    #: SSH clone url
    gh_ssh_clone_url = db.Column(db.String(200), nullable=False)
    #: HTTPS clone url
    gh_https_clone_url = db.Column(db.String(200), nullable=False)
    #: Is the repository public?
    is_public = db.Column(db.Boolean, nullable=False)

    @classmethod
    def from_gh_repo(cls, gh_repo):
        """Constructs an instance of `cls` from `gh_repo`.

        :type gh_repo: :class:`github3.repos.repo.Repository`
        """
        return cls(
            gh_id=gh_repo.id,
            gh_name=gh_repo.name,
            gh_full_name=gh_repo.full_name,
            gh_ssh_clone_url=gh_repo.ssh_url,
            gh_https_clone_url=gh_repo.clone_url,
            is_public=not gh_repo.private)


class HasRepositories(object):
    """Mixin that adds :attr:`repositories` relationship to the model.
    Repositories are stored in separate tables for each parent.
    :attr:`Repository` attribute contains model (inherited from
    :class:`RepositoryBase`) mapped to the parent's repositories table.

    This pattern is well described in
    `"Hand Coded Applications with SQLAlchemy" presentation
    <http://techspot.zzzeek.org/files/2012/hand_coded_with_sqla.key.pdf>`_
    by Mike Bayer.
    """
    @declared_attr
    def repositories(cls):
        parent_id = db.Column(
            '{}_id'.format(cls.__tablename__),
            db.Integer,
            db.ForeignKey('{}.id'.format(cls.__tablename__)),
            nullable=False)

        cls.Repository = type(
            '{}Repository'.format(cls.__name__),
            (RepositoryBase, db.Model),
            {
                '__tablename__': '{}_repository'.format(cls.__tablename__),
                'parent_id': parent_id,
            })
        return db.relationship(cls.Repository, backref='parent',
                               lazy='dynamic', cascade='all')


class User(HasRepositories, db.Model, UserMixin):
    """User account.

    .. attribute:: repositories

        Set of user repositories.

    .. attribute:: organizations

        Set of user organizations in which user has admin rights
        to at least one repository (see :class:`Organization`).
    """
    id = db.Column(db.Integer, primary_key=True)

    #: GitHub user id
    gh_id = db.Column(db.Integer, nullable=False, unique=True)
    #: GitHub user login
    gh_login = db.Column(db.String(200), nullable=False, unique=True)
    #: Human-readable GitHub name
    gh_name = db.Column(db.String(200), nullable=False)
    #: OAuth access token
    gh_access_token = db.Column(db.String(100), nullable=False)
    #: GitHub avatar URL
    gh_avatar_url = db.Column(db.String(500), nullable=False)
    #: The last time when the user's repositories and organizations
    #: were synced with GitHub
    repos_last_synchronized_at = db.Column(db.DateTime)
    #: E-mail address
    email = db.Column(db.String(1000))

    def __repr__(self):
        return (u'<User #{0.id} gh_id={0.gh_id} gh_login={0.gh_login}>'
                .format(self).encode('utf-8'))

    def get_identity(self):
        """Returns user's :class:`flask.ext.principal.Identity`."""
        identity = Identity(self.id)
        for membership in self.memberships:
            if membership.allows_management:
                need = perms.project_manager(membership.project_id)
            else:
                need = perms.project_member(membership.project_id)
            identity.provides.add(need)
        for project in self.owned_projects:
            identity.provides.add(perms.project_owner(project.id))
        return identity

    def get_available_projects(self, annotate_with_latest_builds=False):
        """Returns list of :class:`Projects` that user has access to.
        If `annotate_with_latest_builds` is specified, returns list of pairs
        (:class:`Projects`, :class:`Build`) where the second element is the
        latest project build or ``None`` if the project was never built.
        """
        q = self.owned_projects.union(self.projects)
        if annotate_with_latest_builds:
            q = q.outerjoin(Build).filter(db.or_(
                Build.id == None,
                Build.created_at == db.select([db.func.max(Build.created_at)])
                     .where(Build.project_id == Project.id).correlate(Project)
            )).order_by(Build.created_at.desc()).with_entities(Project, Build)
        return q.all()

    @cached_property
    def gh(self):
        """An authenticated GitHub session for this user.

        :type: :class:`github3.github.GitHub`
        """
        return github3.login(token=self.gh_access_token)

    def get_gh_org_repos(self):
        """Retrieves data from GitHub API and returns a pair of values:

        1. :class:`set` of :class:`github3.orgs.Organization` in which
           the current user has at least one repository with admin rights;
        2. :class:`dict` mapping these organization' ids to lists of
           :class:`github3.repo.Repository` to which the current user
           has admin access.

        :type gh: :class:`github3.github.GitHub` of the current user
        """
        gh_orgs = set()
        gh_repos_by_org_id = collections.defaultdict(list)

        for gh_team in self.gh.iter_user_teams():
            if gh_team.permission != 'admin':
                continue

            gh_org = github3.orgs.Organization(gh_team.to_json()['organization'])
            gh_orgs.add(gh_org)

            for gh_repo in gh_team.iter_repos():
                if gh_repo not in gh_repos_by_org_id[gh_org.id]:
                    # The same repo can be in multiple teams --
                    # append only if we haven't seen `gh_repo` before
                    gh_repos_by_org_id[gh_org.id].append(gh_repo)

        return gh_orgs, gh_repos_by_org_id

    def get_gh_repos(self):
        """Retrieves data from GitHub API and returns a list of
        the user owned repositories.

        :rtype: list of :class:`github3.repo.Repository`
        """
        return list(self.gh.iter_repos(type='owner'))

    def sync_memberships_with_github(self):
        """Does the same as :meth:`Project.sync_memberships_with_github`,
        but for the user. Returns True if there were not any GitHub errors;
        False otherwise.
        """
        assert self.id

        for membership in self.memberships:
            db.session.delete(membership)

        github_data = collections.defaultdict(lambda: False)

        try:
            for gh_team in self.gh.iter_user_teams():
                for gh_repo in gh_team.iter_repos():
                    github_data[gh_repo.id] |= gh_team.permission in ('admin', 'push')

            for gh_repo in self.gh.iter_repos(type='all'):
                # iter_repos lists only repositories owned by users, not ogranizations.
                # Type "all" means both repositories owned by the logged in user and
                # repositories owned by another users in which the logged in user
                # is a collaborator.
                # Collaborator of a user repository always have push rights:
                github_data[gh_repo.id] = True
        except github3.GitHubError as e:
            logger.warning(
                'Failed to synchronize {user!r}\'s memberships with GitHub '
                'due to {e!r}. Errors: {e.errors!r}'.format(user=self, e=e))
            return False

        for gh_repo_id, can_manage in github_data.iteritems():
            project = Project.query.filter_by(gh_id=gh_repo_id).first()
            if not project or project.owner.id == self.id:
                continue
            membership = Membership(
                project=project,
                user=self,
                allows_management=can_manage)
            db.session.add(membership)

        return True


class Organization(HasRepositories, db.Model):
    """Stores a set of organization repositories that a user has
    admin access to.

    Different Kozmic users, but members of the same GitHub organization,
    will have their own :class:`Organization` entries with possibly different
    sets of repositories (because they are possibly members of different teams).

    .. attribute:: repositories
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    #: GitHub organization id
    gh_id = db.Column(db.Integer, nullable=False, index=True)
    #: GitHub organization login
    gh_login = db.Column(db.String(200), nullable=False)
    #: Human-readable GitHub name
    gh_name = db.Column(db.String(200), nullable=False)
    #: :class:`User` whose admin rights is reflected by this organization
    user = db.relationship(
        'User', backref=db.backref('organizations', lazy='dynamic'))


class Membership(db.Model):
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)

    created_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.datetime.utcnow)
    allows_management = db.Column(db.Boolean, nullable=False, default=False)
    user = db.relationship(
        'User', backref=db.backref('memberships', lazy='dynamic'))
    project = db.relationship(
        'Project', backref=db.backref('memberships', lazy='dynamic', cascade='all'))

    def __repr__(self):
        return (u'<Membership {0!r} {1!r}>'
                .format(self.user, self.project).encode('utf-8'))


class DeployKey(db.Model):
    """An RSA deploy key pair."""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'),
                           nullable=False)

    #: GitHub deploy key id
    gh_id = db.Column(db.Integer, nullable=False)
    #: RSA private deploy key in PEM format encrypted with the app secret key
    rsa_private_key = db.Column(db.Text, nullable=False)
    #: RSA public deploy key in OpenSSH format
    rsa_public_key = db.Column(db.Text, nullable=False)

    def __init__(self, passphrase, key_size=2048):
        rsa_key = RSA.generate(key_size)
        self.rsa_private_key = rsa_key.exportKey(format='PEM', passphrase=passphrase)
        self.rsa_public_key = rsa_key.publickey().exportKey(format='OpenSSH')

    def _get_gh_key(self):
        return (None if self.gh_id in (None, MISSING_ID) else
                self.project.gh.key(self.gh_id))

    def ensure(self):
        """If the corresponding GitHub deploy key does not exist, creates it.
        Returns True if there weren't GitHub API errors; False otherwise.
        """
        try:
            gh_key = self._get_gh_key()
            if gh_key:
                return True
            gh_key = self.project.gh.create_key('Kozmic CI key', self.rsa_public_key)
            self.gh_id = gh_key.id
        except github3.GitHubError as e:
            logger.warning(
                'DeployKey.ensure call has failed due to {e!r}. '
                'Errors: {e.errors!r}'.format(project=self.project, e=e))
            return False
        else:
            return True

    def delete(self):
        """Deletes the public key from GitHub. Returns True if it has been
        successfully deleted (or was missing); False otherwise.
        """
        db.session.delete(self)

        try:
            gh_key = self._get_gh_key()
            if not gh_key:
                return True
            gh_key.delete()
        except github3.GitHubError as e:
            logger.warning(
                'DeployKey.delete call has failed due to {e!r}. '
                'Errors: {e.errors!r}'.format(project=self.project, e=e))
            return False
        else:
            return True


class Project(db.Model):
    """Project is a GitHub repository that is being watched by
    Kozmic CI.
    """
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    #: GitHub repo id
    gh_id = db.Column(db.Integer, nullable=False, unique=True)
    #: GitHub repo name (i.e., kozmic)
    gh_name = db.Column(db.String(200), nullable=False)
    #: GitHub repo full name (i.e., aromanovich/kozmic)
    gh_full_name = db.Column(db.String(200), nullable=False)
    #: GitHub repo owner (user or organization) login
    gh_login = db.Column(db.String(200), nullable=False)
    #: SSH repo clone url
    gh_ssh_clone_url = db.Column(db.String(200), nullable=False)
    #: HTTPS clone url
    gh_https_clone_url = db.Column(db.String(200), nullable=False)
    #: Is the project's repository public?
    is_public = db.Column(db.Boolean, nullable=False)

    #: Deploy key
    deploy_key = db.relationship(
        'DeployKey', cascade='all', uselist=False,
        backref=db.backref('project'))
    #: Project members
    members = db.relationship(
        'User', secondary=Membership.__tablename__, lazy='dynamic', viewonly=True,
        backref=db.backref('projects', lazy='dynamic', viewonly=True))
    #: Project owner
    owner = db.relationship(
        'User', backref=db.backref('owned_projects', lazy='dynamic'))

    def __repr__(self):
        return (u'<Project #{0.id} "{0.gh_full_name}">'
                .format(self).encode('utf-8'))

    @property
    def passphrase(self):
        secret_key_w_salt = '{}:{}'.format(
            self.gh_id, flask.current_app.config['SECRET_KEY'])
        return hashlib.sha256(secret_key_w_salt).hexdigest()

    @cached_property
    def gh(self):
        """Project's GitHub.

        :type: :class:`github3.repos.Repository`
        """
        return self.owner.gh.repository(self.gh_login, self.gh_name)

    def delete(self):
        """Deletes the project and it's corresponding GitHub entities such as
        hooks, deploy key, etc. Returns True if they all have been
        successfully deleted (or were missing); False otherwise.
        """
        db.session.delete(self)

        rv = True
        if not self.is_public:
            rv &= self.deploy_key.delete()
        for hook in self.hooks:
            rv &= hook.delete()
            if not rv:
                break
        return rv

    def get_latest_build(self, ref=None):
        """
        :rtype: :class:`Build`
        """
        builds = self.builds.order_by(Build.number.desc())
        if ref:
            builds = builds.filter_by(gh_commit_ref=ref)
        return builds.first()

    def sync_memberships_with_github(self):
        """Synchronizes project members with GitHub.

        GitHub _repository members_ with admin and push rights become
        :term:`project managers`, other _repository members_ become
        :term:`project members`.

        Returns True if there were not any GitHub errors; False otherwise.
        """
        for membership in self.memberships:
            db.session.delete(membership)

        github_data = collections.defaultdict(lambda: False)

        try:
            if self.gh.owner.type == 'Organization':
                gh_teams = self.gh.iter_teams()
                # The Owners team is not listed in /repos/:org/:repo/teams and
                # it is "expected behaviour currently", but it's members
                # definitely have admin access to the repository.
                # The workaround is to find the Owners team "manually" by
                # iterating through all the organization teams.
                for gh_team in self.owner.gh.organization(self.gh.owner.login).iter_teams():
                    # Note: owners team can not be renamed, so it's completely
                    # OK to search for it by name
                    if gh_team.name == 'Owners':
                        gh_teams = itertools.chain([gh_team], gh_teams)

                for gh_team in gh_teams:
                    for gh_user in gh_team.iter_members():
                        github_data[gh_user.id] |= gh_team.permission in ('admin', 'push')

            elif self.gh.owner.type == 'User':
                for gh_user in self.gh.iter_collaborators():
                    # Collaborator of a user repository always have push right
                    github_data[gh_user.id] = True
        except github3.GitHubError as e:
            logger.warning(
                'Failed to synchronize {project!r}\'s memberships with GitHub '
                'due to {e!r}. Errors: {e.errors!r}'.format(project=self, e=e))
            return False

        for gh_user_id, can_manage in github_data.iteritems():
            user = User.query.filter_by(gh_id=gh_user_id).first()
            if not user or user.id == self.owner.id:
                continue
            membership = Membership(
                project=self,
                user=user,
                allows_management=can_manage)
            db.session.add(membership)

        return True


class Hook(db.Model):
    """Reflects a GitHub hook."""
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'),
                           nullable=False)

    #: GitHub hook id
    gh_id = db.Column(db.Integer, nullable=False)
    #: Title
    title = db.Column(db.String(200), nullable=False)
    #: Install script
    install_script = db.Column(db.Text)
    #: Script to be run at hook call
    build_script = db.Column(db.Text, nullable=False)
    #: Name of a Docker image to run build script in
    #: (for example, "ubuntu" or "aromanovich/ubuntu-kozmic").
    #: Specified docker image is pulled from index.docker.io before build
    docker_image = db.Column(db.String(200), nullable=False)
    #: Project
    project = db.relationship(
        Project, backref=db.backref('hooks', lazy='dynamic', cascade='all'))

    def ensure(self):
        """If the corresponding GitHub hook does not exist, creates it.
        If it exists, but has wrong configuration, re-configures it.
        Returns True if there weren't GitHub API errors; False otherwise.
        """
        assert self.id

        events = ['push', 'pull_request']
        config = {
            'url': flask.url_for('builds.hook', id=self.id, _external=True),
            'content_type': 'json',
        }

        try:
            gh_hook = (self.project.gh.hook(self.gh_id)
                       if self.gh_id not in (None, MISSING_ID) else None)
            if gh_hook:
                if gh_hook.events != events or gh_hook.config != config:
                    gh_hook.edit(config=config, events=events)
            else:
                gh_hook = self.project.gh.create_hook(
                    name='web', config=config, events=events, active=True)
        except github3.GitHubError as e:
            logger.warning(
                'GitHub API call to create {project!r}\'s hook has failed. '
                'The exception is "{e!r} and with errors {e.errors!r}.".'.format(
                    project=self.project, e=e))
            return False
        else:
            self.gh_id = gh_hook.id
            return True

    def delete(self):
        """Deletes the project hook. Returns True if it's corresponding GitHub
        hook is missing or has been successfully deleted; False otherwise.
        """
        db.session.delete(self)

        try:
            gh_hook = self.project.gh.hook(self.gh_id)
            if not gh_hook:
                # Probably it was deleted manually using GitHub interface, it's OK
                return True

            gh_hook.delete()
        except github3.GitHubError as exc:
            logger.warning(
                'GitHub API call to delete {hook!r} has failed. '
                'The exception is "{exc!r} and it\'s errors are '
                '{errors!r}.".'.format(hook=self, exc=exc, errors=exc.errors))
            return False
        else:
            return True


class TrackedFile(db.Model):
    """Reflecs a :term:`tracked file`."""
    __table_args__ = (
        db.UniqueConstraint('hook_id', 'path',
                            name='unique_tracked_file_within_hook'),
    )

    id = db.Column(db.Integer, primary_key=True)
    hook_id = db.Column(db.Integer, db.ForeignKey('hook.id'), nullable=False)

    #: Path within git repository
    # Specify utf8_bin for case-sensitive collation
    path = db.Column(db.String(250, collation='utf8_bin'), nullable=False)
    #: Hook
    hook = db.relationship(
        Hook, backref=db.backref('tracked_files', lazy='dynamic', cascade='all'))


class Build(db.Model):
    """Reflects a project commit that triggered a project hook."""
    __table_args__ = (
        db.UniqueConstraint('project_id', 'gh_commit_ref', 'gh_commit_sha',
                            name='unique_ref_and_sha_within_project'),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'),
                           nullable=False)

    #: Build number (within a project)
    number = db.Column(db.Integer, nullable=False, index=True)
    #: Commit reference (branch on which the commit was pushed)
    gh_commit_ref = db.Column(db.String(200), nullable=False)
    #: Commit SHA
    gh_commit_sha = db.Column(db.String(40), nullable=False)
    #: Commit author
    gh_commit_author = db.Column(db.String(200), nullable=False)
    #: Commit message
    gh_commit_message = db.Column(db.String(2000), nullable=False)
    #: Created at
    created_at = db.Column(db.DateTime, nullable=False, index=True,
                           default=datetime.datetime.utcnow)
    #: Build status, one of the following strings:
    #: 'enqueued', 'success', 'pending', 'failure', 'error'
    status = db.Column(db.String(40), nullable=False)
    #: Project
    project = db.relationship(
        Project, backref=db.backref('builds', lazy='dynamic', cascade='all'))

    def calculate_number(self):
        """Computes and sets :attr:`number`."""
        last_number = self.project.builds.with_entities(
            db.func.max(Build.number)).scalar() or 0
        self.number = last_number + 1

    @property
    def started_at(self):
        """Time the first job has started or None if there is
        no started jobs yet.
        """
        started_ats = filter(bool, [job.started_at for job in self.jobs])
        return started_ats and min(started_ats) or None

    @property
    def finished_at(self):
        """Time the last job has finished or None if there is
        no finished jobs yet.
        """
        finished_ats = filter(bool, [job.finished_at for job in self.jobs])
        return finished_ats and min(finished_ats) or None

    def set_status(self, status, target_url='', description=''):
        """Sets :attr:`status` and posts it on GitHub."""
        assert status in ('enqueued', 'success', 'pending', 'failure', 'error')

        if self.status == status:
            return
        self.status = status

        if self.status != 'enqueued':
            self.project.gh.create_status(
                self.gh_commit_sha,
                status,
                target_url=target_url or self.url,
                description=description)

        if (flask.current_app.config['KOZMIC_ENABLE_EMAIL_NOTIFICATIONS'] and
                self.status in ('failure', 'error')):
            header_template = u'[{status}] {project}#{build_number} ({ref} — {sha})'
            html_template = '<p><a href="{url}">{description}</a></p>'

            header = header_template.format(
                status=self.status,
                project=self.project.gh_full_name,
                build_number=self.number,
                sha=self.gh_commit_sha[:8],
                ref=self.gh_commit_ref)
            html = html_template.format(
                url=target_url or self.url,
                description=description or 'The build has failed.')
            members = [self.project.owner] + self.project.members.all()
            recipients = [member.email for member in members if member.email]

            if recipients:
                message = Message(
                    header,
                    html=html,
                    recipients=recipients)
                mail.send(message)

    @property
    def url(self):
        return flask.url_for(
            'projects.build', project_id=self.project.id, id=self.id)

    def get_github_com_commit_url(self):
        return ('https://github.com/{0.project.gh_full_name}/'
                'commit/{0.gh_commit_sha}'.format(self))


class HookCall(db.Model):
    """Reflects a fact that GitHub triggered a project hook."""
    __table_args__ = (
        db.UniqueConstraint('build_id', 'hook_id',
                            name='unique_hook_call_within_build'),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Allow hook_id be null because we don't want to lose all the hook calls
    # data when a manager deletes the hook
    hook_id = db.Column(db.Integer, db.ForeignKey('hook.id', ondelete='SET NULL'))
    build_id = db.Column(db.Integer, db.ForeignKey('build.id'), nullable=False)

    #: Created at
    created_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.datetime.utcnow)
    #: JSON payload from a GitHub webhook request
    gh_payload = db.deferred(db.Column(JSONEncodedDict, nullable=False))
    #: Hook
    hook = db.relationship(Hook, backref=db.backref('calls', lazy='dynamic'))
    #: Build
    build = db.relationship(
        Build, backref=db.backref('hook_calls', lazy='dynamic', cascade='all'))


class Job(db.Model):
    """A job that caused by a hook call."""
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.Integer, db.ForeignKey('build.id'),
                         nullable=False)
    hook_call_id = db.Column(db.Integer, db.ForeignKey('hook_call.id'),
                             nullable=False)

    #: Time the job has started or None
    started_at = db.Column(db.DateTime)
    #: Time the job has finished or None
    finished_at = db.Column(db.DateTime)
    #: Return code
    return_code = db.Column(db.Integer)
    #: Job log
    stdout = db.deferred(db.Column(sqlalchemy.dialects.mysql.MEDIUMBLOB))
    #: uuid of a Celery task that is running a job
    task_uuid = db.Column(db.String(36))
    #: :class:`Build`
    build = db.relationship(
        Build, backref=db.backref('jobs', lazy='dynamic', cascade='all'))
    #: :class:`HookCall`
    hook_call = db.relationship('HookCall')

    def __repr__(self):
        return u'<Job #{0.id}>'.format(self).encode('utf-8')

    def get_cache_id(self):
        """Returns a string that can be used for tagging a Docker image
        built from the install script.
        A cache id changes whenever the base Docker image, the install
        script or any of the :term:`tracked files` is changed.

        .. note::

            Requires that Docker is running and Docker base image
            (:attr:`self.hook_call.hook.docker_image`) is pulled.
        """
        hook = self.hook_call.hook
        gh = self.build.project.gh
        commit_sha = self.build.gh_commit_sha

        docker_image_id = docker_utils.get_docker_image_id(
            *hook.docker_image.rsplit(':'))
        assert docker_image_id
        hash_parts = [docker_image_id, hook.install_script]

        for tracked_file in hook.tracked_files.order_by(TrackedFile.path):
            path = tracked_file.path
            # GitHub API wants to see paths relative to the repo directory
            # ("./basic.txt" does not work, whereas "basic.txt" does)
            path = os.path.relpath(path, start='.')
            if path == '.':
                # Special case: os.path.relpath('.', start='.') returns ".",
                # but GitHub API wants to see "/" or "".
                path = ''

            contents = gh.contents(path, ref=commit_sha)
            if isinstance(contents, dict):
                # `contents` represents a directory. Add all its entries
                # to the hash
                for file_path, file_contents in contents.iteritems():
                    hash_parts.append(file_path + file_contents.sha)
            elif contents:
                # `contents` represents a regular file
                hash_parts.append(path + contents.sha)
            else:
                # `path` does not exist. But it's still necessary to include
                # it in the hash to be able to detect file removals
                hash_parts.append(path)

        return hashlib.sha256(''.join(hash_parts)).hexdigest()

    def started(self):
        """Sets :attr:`started_at` and updates :attr:`build` status.
        **Must** be called when the job is started.
        """
        self.started_at = datetime.datetime.utcnow()
        self.finished_at = None
        description = 'Kozmic build #{0} is pending'.format(self.build.number)
        self.build.set_status('pending', description=description)

    def finished(self, return_code):
        """Sets :attr:`finished_at` and updates :attr:`build` status.
        **Must** be called when the job is finished.
        """
        self.return_code = return_code
        self.finished_at = datetime.datetime.utcnow()

        if return_code != 0:
            description = (
                'Kozmic build #{0} has failed '
                'because of the "{1}" job'.format(
                    self.build.number,
                    self.hook_call.hook.title))
            self.build.set_status('failure', description=description)
            return

        jobs = self.build.jobs
        all_other_jobs_finished = all(job.finished_at for job in jobs
                                      if job.id != self.id)
        all_other_jobs_succeeded = all(job.return_code == 0 for job in jobs
                                       if job.id != self.id)
        if all_other_jobs_finished and all_other_jobs_succeeded:
            description = 'Kozmic build #{0} has passed'.format(self.build.number)
            self.build.set_status('success', description=description)
            return

    @property
    def tailer_url(self):
        """URL of a websocket that streams a job log in realtime."""
        return flask.current_app.config['TAILER_URL_TEMPLATE'].format(
            job_id=self.task_uuid)

    @property
    def permanent_url(self):
        """A permanent URL of the job."""
        return flask.url_for('.job', project_id=self.build.project.id,
                             build_id=self.build.id, id=self.id)

    def is_finished(self):
        """Is the job finished?"""
        return self.status in ('success', 'failure', 'error')

    @property
    def status(self):
        """One of the following values: 'enqueued', 'success', 'pending',
        'failure', 'error'.
        """
        if not self.started_at:
            return 'enqueued'
        elif self.started_at and not self.finished_at:
            return 'pending'
        elif self.finished_at:
            if self.return_code == 0:
                return 'success'
            else:
                return 'failure'
